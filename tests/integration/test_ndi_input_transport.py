"""Integration tests for NDIInputTransport."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from avatar.processors.ndi_input_transport import (
    MockNDIInputTransport,
    NDIInputTransport,
)
from pipecat.frames.frames import InputImageRawFrame
from pipecat.processors.frame_processor import FrameDirection


class TestNDIInputTransportInit:
    """Tests for NDI transport initialization."""

    def test_default_configuration(self) -> None:
        """Test default NDI configuration."""
        # Mock GStreamer availability
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport()
                assert transport.ndi_source_name == "MY_SOURCE"
                assert transport.fps == 1
                assert transport.width == 640
                assert transport.height == 360

    def test_custom_configuration(self) -> None:
        """Test custom NDI configuration."""
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport(
                    ndi_source_name="CAMERA_1",
                    fps=5,
                    width=1280,
                    height=720,
                )
                assert transport.ndi_source_name == "CAMERA_1"
                assert transport.fps == 5
                assert transport.width == 1280
                assert transport.height == 720

    def test_raises_without_gstreamer(self) -> None:
        """Test that initialization fails without GStreamer."""
        with patch(
            "avatar.processors.ndi_input_transport.GST_AVAILABLE", False
        ):
            with pytest.raises(RuntimeError) as exc_info:
                NDIInputTransport()
            assert "GStreamer is required" in str(exc_info.value)


class TestNDIInputTransportPipeline:
    """Tests for GStreamer pipeline construction."""

    def test_pipeline_string_default(self) -> None:
        """Test default pipeline string construction."""
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport()
                pipeline_str = transport._build_pipeline_string()

                assert 'ndisrc ndi-name="MY_SOURCE"' in pipeline_str
                assert "videoconvert" in pipeline_str
                assert "videoscale" in pipeline_str
                assert "width=640,height=360" in pipeline_str
                assert "framerate=1/1" in pipeline_str
                assert "format=RGB" in pipeline_str
                assert "appsink" in pipeline_str

    def test_pipeline_string_custom_fps(self) -> None:
        """Test pipeline with custom frame rate."""
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport(fps=30)
                pipeline_str = transport._build_pipeline_string()

                assert "framerate=30/1" in pipeline_str

    def test_pipeline_string_no_scaling(self) -> None:
        """Test pipeline without scaling (width=0)."""
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport(width=0, height=0)
                pipeline_str = transport._build_pipeline_string()

                assert "videoscale" not in pipeline_str


class TestMockNDIInputTransport:
    """Tests for MockNDIInputTransport."""

    @pytest.fixture
    def mock_transport(self) -> MockNDIInputTransport:
        """Create mock transport for testing."""
        return MockNDIInputTransport(fps=10, width=320, height=240)

    def test_init(self, mock_transport: MockNDIInputTransport) -> None:
        """Test mock transport initialization."""
        assert mock_transport.fps == 10
        assert mock_transport.width == 320
        assert mock_transport.height == 240
        assert mock_transport._running is False

    @pytest.mark.asyncio
    async def test_start_creates_task(
        self, mock_transport: MockNDIInputTransport
    ) -> None:
        """Test that start creates frame generation task."""
        await mock_transport.start()

        assert mock_transport._running is True
        assert mock_transport._task is not None

        await mock_transport.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(
        self, mock_transport: MockNDIInputTransport
    ) -> None:
        """Test that stop cancels frame generation task."""
        await mock_transport.start()
        await mock_transport.stop()

        assert mock_transport._running is False
        assert mock_transport._task is None

    @pytest.mark.asyncio
    async def test_generates_frames(
        self, mock_transport: MockNDIInputTransport
    ) -> None:
        """Test that mock transport generates frames."""
        frames_received: list[InputImageRawFrame] = []

        async def capture_frame(frame, direction):
            if isinstance(frame, InputImageRawFrame):
                frames_received.append(frame)

        mock_transport.push_frame = capture_frame

        await mock_transport.start()

        # Wait for a few frames (10 fps = 100ms per frame)
        await asyncio.sleep(0.35)

        await mock_transport.stop()

        # Should have received at least 2 frames
        assert len(frames_received) >= 2

        # Check frame properties
        frame = frames_received[0]
        assert frame.size == (320, 240)
        assert frame.format == "RGB"
        assert len(frame.image) == 320 * 240 * 3  # RGB

    @pytest.mark.asyncio
    async def test_frame_content_changes(
        self, mock_transport: MockNDIInputTransport
    ) -> None:
        """Test that frame content changes over time."""
        frames_received: list[InputImageRawFrame] = []

        async def capture_frame(frame, direction):
            if isinstance(frame, InputImageRawFrame):
                frames_received.append(frame)

        mock_transport.push_frame = capture_frame

        await mock_transport.start()
        await asyncio.sleep(0.25)
        await mock_transport.stop()

        # Frames should have different content
        if len(frames_received) >= 2:
            assert frames_received[0].image != frames_received[1].image

    @pytest.mark.asyncio
    async def test_frames_generated_counter(
        self, mock_transport: MockNDIInputTransport
    ) -> None:
        """Test frames generated counter."""
        mock_transport.push_frame = AsyncMock()

        await mock_transport.start()
        await asyncio.sleep(0.35)
        await mock_transport.stop()

        assert mock_transport._frames_generated >= 2


class TestNDIInputTransportStats:
    """Tests for transport statistics."""

    def test_get_stats(self) -> None:
        """Test get_stats returns configuration."""
        with patch.dict("sys.modules", {"gi": MagicMock()}):
            with patch(
                "avatar.processors.ndi_input_transport.GST_AVAILABLE", True
            ):
                transport = NDIInputTransport(
                    ndi_source_name="TEST",
                    fps=5,
                    width=800,
                    height=600,
                )

                stats = transport.get_stats()

                assert stats["frames_received"] == 0
                assert stats["ndi_source"] == "TEST"
                assert stats["fps"] == 5
                assert stats["resolution"] == "800x600"


class TestNDIInputTransportIntegration:
    """Integration tests simulating real usage patterns."""

    @pytest.mark.asyncio
    async def test_mock_transport_in_pipeline(self) -> None:
        """Test mock transport generates correct frame format for pipeline."""
        transport = MockNDIInputTransport(fps=10, width=640, height=360)

        frames: list[InputImageRawFrame] = []

        async def collect_frame(frame, direction):
            if isinstance(frame, InputImageRawFrame):
                frames.append(frame)

        transport.push_frame = collect_frame

        await transport.start()
        await asyncio.sleep(0.15)
        await transport.stop()

        # Verify frames are valid for vision processing
        assert len(frames) >= 1

        frame = frames[0]
        assert isinstance(frame.image, bytes)
        assert frame.size[0] == 640
        assert frame.size[1] == 360
        assert frame.format == "RGB"

        # Verify pixel data size
        expected_size = 640 * 360 * 3  # RGB = 3 bytes per pixel
        assert len(frame.image) == expected_size

    @pytest.mark.asyncio
    async def test_high_fps_generation(self) -> None:
        """Test high FPS mock generation doesn't cause issues."""
        transport = MockNDIInputTransport(fps=30, width=160, height=120)
        transport.push_frame = AsyncMock()

        await transport.start()
        await asyncio.sleep(0.2)  # Should generate ~6 frames
        await transport.stop()

        # Should have generated multiple frames without errors
        assert transport._frames_generated >= 4

    @pytest.mark.asyncio
    async def test_frame_passthrough(self) -> None:
        """Test that process_frame passes through other frames."""
        transport = MockNDIInputTransport()

        passed_frames = []

        async def capture(frame, direction):
            passed_frames.append((frame, direction))

        transport.push_frame = capture

        # Create a different type of frame
        from pipecat.frames.frames import TextFrame
        text_frame = TextFrame(text="test")

        await transport.process_frame(text_frame, FrameDirection.DOWNSTREAM)

        # Frame should be passed through
        assert len(passed_frames) == 1
        assert passed_frames[0][0] == text_frame
        assert passed_frames[0][1] == FrameDirection.DOWNSTREAM
