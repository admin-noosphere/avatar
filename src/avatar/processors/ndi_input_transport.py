"""NDIInputTransport - GStreamer-based NDI video input for Pipecat.

This transport ingests video from NDI sources using GStreamer and converts
it to InputImageRawFrame for use in vision-enabled pipelines (e.g., GPT-4V).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipecat.frames.frames import InputImageRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# GStreamer imports - optional dependency
try:
    import gi
    gi.require_version("Gst", "1.0")
    gi.require_version("GstApp", "1.0")
    from gi.repository import Gst, GstApp, GLib
    GST_AVAILABLE = True
except (ImportError, ValueError) as e:
    GST_AVAILABLE = False
    logger.warning(f"GStreamer not available: {e}")


class NDIInputTransport(FrameProcessor):
    """GStreamer-based NDI video input transport.

    This processor ingests video from an NDI source, converts it to RGB format,
    and emits InputImageRawFrame for downstream vision processing.

    The GStreamer pipeline handles:
    - NDI source connection
    - Color space conversion (UYVY/I420 → RGB)
    - Frame rate decimation (to reduce CPU load)
    - Resolution scaling (optional)

    Attributes:
        ndi_source_name: NDI source name to connect to.
        fps: Target frame rate after decimation.
        width: Target frame width (0 = original).
        height: Target frame height (0 = original).
    """

    def __init__(
        self,
        ndi_source_name: str = "MY_SOURCE",
        fps: int = 1,
        width: int = 640,
        height: int = 360,
        **kwargs: Any,
    ) -> None:
        """Initialize the NDI input transport.

        Args:
            ndi_source_name: NDI source name to connect to.
            fps: Target frame rate (1 = one frame per second).
            width: Target frame width (0 to keep original).
            height: Target frame height (0 to keep original).
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)

        if not GST_AVAILABLE:
            raise RuntimeError(
                "GStreamer is required for NDI input. "
                "Install with: pip install PyGObject"
            )

        self.ndi_source_name = ndi_source_name
        self.fps = fps
        self.width = width
        self.height = height

        self._pipeline: Gst.Pipeline | None = None
        self._appsink: GstApp.AppSink | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._frames_received = 0

    def _build_pipeline_string(self) -> str:
        """Build GStreamer pipeline string.

        Returns:
            GStreamer pipeline description string.
        """
        # Base pipeline: NDI source → video conversion
        pipeline_parts = [
            f'ndisrc ndi-name="{self.ndi_source_name}"',
            "! videoconvert",
        ]

        # Optional scaling
        if self.width > 0 and self.height > 0:
            pipeline_parts.append(
                f"! videoscale ! video/x-raw,width={self.width},height={self.height}"
            )

        # Frame rate decimation
        pipeline_parts.append(
            f"! videorate ! video/x-raw,framerate={self.fps}/1"
        )

        # Final conversion to RGB and appsink
        pipeline_parts.extend([
            "! videoconvert ! video/x-raw,format=RGB",
            "! appsink name=sink emit-signals=True sync=False drop=True max-buffers=1",
        ])

        return " ".join(pipeline_parts)

    async def start(self) -> None:
        """Start the NDI input transport and GStreamer pipeline."""
        await super().start()

        # Initialize GStreamer
        Gst.init(None)

        # Build and parse pipeline
        pipeline_str = self._build_pipeline_string()
        logger.info(f"GStreamer pipeline: {pipeline_str}")

        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except GLib.Error as e:
            raise RuntimeError(f"Failed to create GStreamer pipeline: {e}")

        # Get appsink element
        self._appsink = self._pipeline.get_by_name("sink")
        if not self._appsink:
            raise RuntimeError("Failed to get appsink from pipeline")

        # Connect signal for new samples
        self._appsink.connect("new-sample", self._on_new_sample)

        # Store event loop for thread-safe frame pushing
        self._loop = asyncio.get_event_loop()
        self._running = True

        # Start pipeline
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer pipeline")

        logger.info(
            f"NDIInputTransport started: {self.ndi_source_name} "
            f"@ {self.fps} fps, {self.width}x{self.height}"
        )

    async def stop(self) -> None:
        """Stop the GStreamer pipeline and cleanup."""
        self._running = False

        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

        self._appsink = None

        await super().stop()

        logger.info(
            f"NDIInputTransport stopped. Frames received: {self._frames_received}"
        )

    def _on_new_sample(self, sink: GstApp.AppSink) -> Gst.FlowReturn:
        """Handle new sample from GStreamer (called from GStreamer thread).

        Args:
            sink: The appsink element.

        Returns:
            GStreamer flow return status.
        """
        if not self._running:
            return Gst.FlowReturn.EOS

        # Pull sample from sink
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        # Get buffer and caps
        buf = sample.get_buffer()
        caps = sample.get_caps()

        if not buf or not caps:
            return Gst.FlowReturn.ERROR

        # Extract frame dimensions from caps
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")

        # Map buffer to get pixel data
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR

        try:
            # Copy pixel data (GStreamer buffer may be reused)
            image_data = bytes(map_info.data)

            # Create Pipecat frame
            frame = InputImageRawFrame(
                image=image_data,
                size=(width, height),
                format="RGB",
            )

            self._frames_received += 1

            # Push frame to pipeline (thread-safe)
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._push_video_frame(frame),
                    self._loop,
                )

        finally:
            buf.unmap(map_info)

        return Gst.FlowReturn.OK

    async def _push_video_frame(self, frame: InputImageRawFrame) -> None:
        """Push video frame to the pipeline.

        Args:
            frame: The video frame to push.
        """
        await self.push_frame(frame, FrameDirection.DOWNSTREAM)

        if self._frames_received % 10 == 0:
            logger.debug(f"NDI frames received: {self._frames_received}")

    async def process_frame(
        self, frame: Any, direction: FrameDirection
    ) -> None:
        """Process incoming frames (pass-through for this transport).

        Args:
            frame: The frame to process.
            direction: The direction of frame flow.
        """
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    @property
    def is_running(self) -> bool:
        """Check if the transport is running.

        Returns:
            True if running, False otherwise.
        """
        return self._running

    def get_stats(self) -> dict[str, Any]:
        """Get transport statistics.

        Returns:
            Dictionary with frames_received and configuration.
        """
        return {
            "frames_received": self._frames_received,
            "ndi_source": self.ndi_source_name,
            "fps": self.fps,
            "resolution": f"{self.width}x{self.height}",
        }


class MockNDIInputTransport(FrameProcessor):
    """Mock NDI transport for testing without GStreamer.

    Generates synthetic video frames at the specified rate for testing
    the pipeline without actual NDI hardware.
    """

    def __init__(
        self,
        fps: int = 1,
        width: int = 640,
        height: int = 360,
        **kwargs: Any,
    ) -> None:
        """Initialize mock NDI transport.

        Args:
            fps: Frame generation rate.
            width: Frame width.
            height: Frame height.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self.fps = fps
        self.width = width
        self.height = height

        self._running = False
        self._task: asyncio.Task | None = None
        self._frames_generated = 0

    async def start(self) -> None:
        """Start generating mock frames."""
        self._running = True
        self._task = asyncio.create_task(self._generate_frames())
        logger.info(
            f"MockNDIInputTransport started @ {self.fps} fps, "
            f"{self.width}x{self.height}"
        )

    async def stop(self) -> None:
        """Stop generating frames."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(
            f"MockNDIInputTransport stopped. "
            f"Frames generated: {self._frames_generated}"
        )

    async def _generate_frames(self) -> None:
        """Generate synthetic video frames."""
        interval = 1.0 / self.fps

        while self._running:
            # Create a simple colored frame (changes over time)
            color_value = (self._frames_generated * 10) % 256
            pixel = bytes([color_value, 128, 255 - color_value])
            image_data = pixel * (self.width * self.height)

            frame = InputImageRawFrame(
                image=image_data,
                size=(self.width, self.height),
                format="RGB",
            )

            await self.push_frame(frame, FrameDirection.DOWNSTREAM)
            self._frames_generated += 1

            if self._frames_generated % 10 == 0:
                logger.debug(f"Mock frames generated: {self._frames_generated}")

            await asyncio.sleep(interval)

    async def process_frame(
        self, frame: Any, direction: FrameDirection
    ) -> None:
        """Process incoming frames (pass-through).

        Args:
            frame: The frame to process.
            direction: The direction of frame flow.
        """
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
