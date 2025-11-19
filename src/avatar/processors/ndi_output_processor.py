"""NDIOutputProcessor - Receives NDI from Unreal and outputs to Daily.

This processor receives NDI video (and optionally audio) from Unreal Engine
containing the MetaHuman avatar with lip-sync animation, and converts it to
Pipecat frames for output to Daily transport.

Based on AgentNDIProcessor from Gamma project.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np

from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# NDI SDK imports - optional dependency
try:
    import os
    from pathlib import Path

    # Try to find NDI SDK
    ndi_sdk_paths = [
        Path("/home/gieidi-prime/Agents/Claude/Aleph/NDI SDK for Linux"),
        Path("/opt/ndi-sdk"),
        Path.home() / "NDI SDK for Linux",
    ]

    for sdk_path in ndi_sdk_paths:
        if sdk_path.exists():
            os.environ["NDI_SDK_DIR"] = str(sdk_path)
            lib_path = sdk_path / "lib" / "x86_64-linux-gnu"
            if lib_path.exists():
                current_ld = os.environ.get("LD_LIBRARY_PATH", "")
                os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{current_ld}"
            break

    import NDIlib as ndi
    NDI_AVAILABLE = True
    logger.info("NDI SDK loaded successfully")
except ImportError as e:
    NDI_AVAILABLE = False
    logger.warning(f"NDI not available: {e}")


# Constants
NDI_SAMPLE_RATE = 16000
CHUNK_DURATION_MS = 20


class NDIOutputProcessor(FrameProcessor):
    """Processor that receives NDI from Unreal and outputs to pipeline.

    This processor connects to an NDI source (Unreal Engine with MetaHuman),
    captures video and audio frames, and pushes them as OutputImageRawFrame
    and OutputAudioRawFrame for the Daily transport to send to users.

    Attributes:
        source_name: NDI source name to connect to.
        source_ip: IP address of NDI source.
        use_ndi_audio: Whether to forward NDI audio to output.
    """

    def __init__(
        self,
        source_name: str = "UE5_Metahuman",
        source_ip: str = "192.168.1.14",
        use_ndi_audio: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the NDI output processor.

        Args:
            source_name: NDI source name to connect to.
            source_ip: IP address of NDI source.
            use_ndi_audio: Whether to forward NDI audio.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)

        if not NDI_AVAILABLE:
            logger.warning(
                "NDI not available. Install NDI SDK and NDIlib Python bindings."
            )

        self.source_name = source_name
        self.source_ip = source_ip
        self.use_ndi_audio = use_ndi_audio

        self._ndi_recv = None
        self._running = False
        self._task: asyncio.Task | None = None

        # Statistics
        self._video_frames = 0
        self._audio_frames = 0
        self._start_time = 0.0
        self._last_stats_time = 0.0

    async def start_ndi(self) -> None:
        """Start NDI reception."""
        if not NDI_AVAILABLE:
            logger.error("Cannot start NDI: SDK not available")
            return

        if self._running:
            logger.warning("NDI already running")
            return

        # Initialize NDI
        if not ndi.initialize():
            logger.error("Failed to initialize NDI")
            return

        logger.info("NDI initialized")

        # Create receiver
        source = ndi.Source()
        source.ndi_name = self.source_name.encode("utf-8")
        if self.source_ip:
            source.url_address = f"{self.source_ip}:5961".encode("utf-8")

        create_settings = ndi.RecvCreateV3()
        create_settings.source_to_connect_to = source
        create_settings.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST

        self._ndi_recv = ndi.recv_create_v3(create_settings)
        if not self._ndi_recv:
            logger.error("Failed to create NDI receiver")
            return

        logger.info(f"NDI connected to {self.source_ip} - {self.source_name}")
        logger.info(f"Audio mode: {'NDI forwarding' if self.use_ndi_audio else 'disabled'}")

        self._running = True
        self._start_time = time.time()
        self._last_stats_time = time.time()

        # Start processing task
        self._task = asyncio.create_task(self._process_ndi())
        logger.info("NDI processing started")

    async def stop_ndi(self) -> None:
        """Stop NDI reception."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._ndi_recv:
            ndi.recv_destroy(self._ndi_recv)
            self._ndi_recv = None

        logger.info(
            f"NDI stopped. Video: {self._video_frames} frames, "
            f"Audio: {self._audio_frames} frames"
        )

    async def _process_ndi(self) -> None:
        """Process NDI stream in background task."""
        if not self._ndi_recv:
            return

        samples_per_chunk = int(NDI_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

        logger.info(f"Processing NDI - Audio: {NDI_SAMPLE_RATE}Hz @ {CHUNK_DURATION_MS}ms chunks")

        while self._running:
            try:
                # Capture frame with short timeout for low latency
                result = ndi.recv_capture_v2(self._ndi_recv, 1)  # 1ms timeout

                if result:
                    frame_type, video_frame, audio_frame, _ = result

                    # Process video frame
                    if frame_type == ndi.FRAME_TYPE_VIDEO and video_frame:
                        await self._process_video_frame(video_frame)
                        ndi.recv_free_video_v2(self._ndi_recv, video_frame)

                    # Process audio frame
                    elif frame_type == ndi.FRAME_TYPE_AUDIO and audio_frame:
                        if self.use_ndi_audio:
                            await self._process_audio_frame(audio_frame, samples_per_chunk)
                        ndi.recv_free_audio_v2(self._ndi_recv, audio_frame)

                # Log stats periodically
                current_time = time.time()
                if current_time - self._last_stats_time >= 5.0:
                    self._log_stats()
                    self._last_stats_time = current_time

                # Yield control
                if result:
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(0.001)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"NDI processing error: {e}")
                await asyncio.sleep(0.01)

    async def _process_video_frame(self, video_frame: Any) -> None:
        """Process and push video frame.

        Args:
            video_frame: NDI video frame.
        """
        if not hasattr(video_frame, "data") or video_frame.data is None:
            return

        video_data = video_frame.data

        if not isinstance(video_data, np.ndarray) or len(video_data.shape) < 2:
            return

        height, width = video_data.shape[:2]

        # Convert BGR to RGB if needed
        if len(video_data.shape) == 3 and video_data.shape[2] >= 3:
            rgb_data = video_data[:, :, [2, 1, 0]]

            image_frame = OutputImageRawFrame(
                image=rgb_data.tobytes(),
                size=(width, height),
                format="RGB",
            )

            await self.push_frame(image_frame, FrameDirection.DOWNSTREAM)
            self._video_frames += 1

            if self._video_frames == 1:
                logger.info(f"First video frame: {width}x{height}")

    async def _process_audio_frame(
        self, audio_frame: Any, samples_per_chunk: int
    ) -> None:
        """Process and push audio frame.

        Args:
            audio_frame: NDI audio frame.
            samples_per_chunk: Expected samples per chunk.
        """
        if not hasattr(audio_frame, "data") or audio_frame.data is None:
            return

        audio_data = audio_frame.data

        if not isinstance(audio_data, np.ndarray):
            return

        num_channels = getattr(audio_frame, "no_channels", 2)

        # Log first frame info
        if self._audio_frames == 0:
            sample_rate = getattr(audio_frame, "sample_rate", NDI_SAMPLE_RATE)
            logger.info(
                f"First audio frame: {sample_rate}Hz, {num_channels}ch, "
                f"dtype={audio_data.dtype}"
            )

        # Extract mono
        if num_channels > 1:
            if len(audio_data.shape) == 2:
                audio_mono = audio_data[0]
            else:
                audio_mono = audio_data[::num_channels]
        else:
            audio_mono = audio_data

        # Convert to float32 if needed
        if audio_mono.dtype != np.float32:
            audio_mono = audio_mono.astype(np.float32)

        # Adjust size to match chunk
        if len(audio_mono) != samples_per_chunk:
            if len(audio_mono) > samples_per_chunk:
                audio_mono = audio_mono[:samples_per_chunk]
            else:
                padding = samples_per_chunk - len(audio_mono)
                audio_mono = np.pad(audio_mono, (0, padding))

        # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
        audio_int16 = (audio_mono * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        audio_out = OutputAudioRawFrame(
            audio=audio_bytes,
            sample_rate=NDI_SAMPLE_RATE,
            num_channels=1,
        )

        await self.push_frame(audio_out, FrameDirection.DOWNSTREAM)
        self._audio_frames += 1

    def _log_stats(self) -> None:
        """Log periodic statistics."""
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return

        video_fps = self._video_frames / elapsed
        audio_rate = self._audio_frames / elapsed

        logger.info(
            f"NDI Stats - Video: {video_fps:.1f} FPS, "
            f"Audio: {audio_rate:.1f} chunks/s, "
            f"Total: {self._video_frames} frames, {self._audio_frames} audio"
        )

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        """Process frames (pass-through).

        Args:
            frame: The frame to process.
            direction: The direction of frame flow.
        """
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    def get_stats(self) -> dict[str, Any]:
        """Get processor statistics.

        Returns:
            Dictionary with video_frames, audio_frames, and running time.
        """
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "video_frames": self._video_frames,
            "audio_frames": self._audio_frames,
            "running_time": elapsed,
            "video_fps": self._video_frames / elapsed if elapsed > 0 else 0,
            "source": f"{self.source_name}@{self.source_ip}",
        }

    @property
    def is_running(self) -> bool:
        """Check if NDI reception is running.

        Returns:
            True if running, False otherwise.
        """
        return self._running
