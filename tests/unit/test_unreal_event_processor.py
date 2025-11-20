"""Unit tests for UnrealEventProcessor."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from avatar.processors.unreal_event_processor import UnrealEventProcessor
from pipecat.frames.frames import (
    Frame,
    StartInterruptionFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection


@pytest.fixture
def processor() -> UnrealEventProcessor:
    """Create a processor instance for testing."""
    return UnrealEventProcessor(
        uri="ws://localhost:8765",
        reconnect_delay=0.1,
        max_reconnect_delay=1.0,
    )


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.open = True
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    ws.wait_closed = AsyncMock()
    return ws


class TestUnrealEventProcessorInit:
    """Tests for processor initialization."""

    def test_default_uri(self) -> None:
        """Test default WebSocket URI."""
        processor = UnrealEventProcessor()
        assert processor.uri == "ws://localhost:8765"

    def test_custom_uri(self) -> None:
        """Test custom WebSocket URI."""
        processor = UnrealEventProcessor(uri="ws://192.168.1.100:9000")
        assert processor.uri == "ws://192.168.1.100:9000"

    def test_reconnect_delays(self) -> None:
        """Test reconnection delay configuration."""
        processor = UnrealEventProcessor(
            reconnect_delay=2.0,
            max_reconnect_delay=60.0,
        )
        assert processor.reconnect_delay == 2.0
        assert processor.max_reconnect_delay == 60.0

    def test_initial_state(self) -> None:
        """Test initial processor state."""
        processor = UnrealEventProcessor()
        assert processor._websocket is None
        assert processor._connection_task is None
        assert processor._running is False


class TestUnrealEventProcessorLifecycle:
    """Tests for processor start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_connection_task(
        self, processor: UnrealEventProcessor
    ) -> None:
        """Test that start() creates a connection task."""
        with patch("websockets.connect", new_callable=AsyncMock):
            await processor.start()
            assert processor._running is True
            assert processor._connection_task is not None
            await processor.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_connection_task(
        self, processor: UnrealEventProcessor
    ) -> None:
        """Test that stop() cancels the connection task."""
        with patch("websockets.connect", new_callable=AsyncMock):
            await processor.start()
            await processor.stop()
            assert processor._running is False
            assert processor._websocket is None


class TestUnrealEventProcessorFrameHandling:
    """Tests for frame processing and WebSocket commands."""

    @pytest.mark.asyncio
    async def test_tts_started_sends_start_speaking(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test that TTSStartedFrame triggers start_speaking command."""
        processor._websocket = mock_websocket

        # Create a mock for push_frame
        processor.push_frame = AsyncMock()

        frame = TTSStartedFrame()
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Verify WebSocket messages (2 calls: start_speaking + start_audio_stream)
        assert mock_websocket.send.call_count == 2
        calls = mock_websocket.send.call_args_list

        start_msg = json.loads(calls[0][0][0])
        assert start_msg["type"] == "start_speaking"
        assert start_msg["category"] == "SPEAKING_NEUTRAL"

        stream_msg = json.loads(calls[1][0][0])
        assert stream_msg["type"] == "start_audio_stream"

        # Verify frame was forwarded
        processor.push_frame.assert_called_once_with(
            frame, FrameDirection.DOWNSTREAM
        )

    @pytest.mark.asyncio
    async def test_tts_stopped_sends_stop_speaking(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test that TTSStoppedFrame triggers stop_speaking command."""
        processor._websocket = mock_websocket
        processor.push_frame = AsyncMock()

        frame = TTSStoppedFrame()
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Verify WebSocket messages (2 calls: end_audio_stream + stop_speaking)
        assert mock_websocket.send.call_count == 2
        calls = mock_websocket.send.call_args_list

        stream_end_msg = json.loads(calls[0][0][0])
        assert stream_end_msg["type"] == "end_audio_stream"

        stop_msg = json.loads(calls[1][0][0])
        assert stop_msg["type"] == "stop_speaking"

    @pytest.mark.asyncio
    async def test_interruption_sends_stop_speaking(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test that interruption handling sends stop_speaking.

        Note: StartInterruptionFrame requires TaskManager to be initialized
        which only happens in a full Pipeline context. We test the handler
        logic directly instead.
        """
        processor._websocket = mock_websocket

        # Test the internal command that would be sent on interruption
        await processor._send_command({"type": "stop_speaking"})

        # Verify WebSocket message
        mock_websocket.send.assert_called_once()
        sent_data = json.loads(mock_websocket.send.call_args[0][0])
        assert sent_data["type"] == "stop_speaking"

    @pytest.mark.asyncio
    async def test_unrelated_frame_passes_through(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test that unrelated frames pass through without WebSocket calls."""
        processor._websocket = mock_websocket
        processor.push_frame = AsyncMock()

        frame = TextFrame(text="Hello")
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # No WebSocket message sent
        mock_websocket.send.assert_not_called()

        # Frame still forwarded
        processor.push_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_without_connection_logs_warning(
        self, processor: UnrealEventProcessor
    ) -> None:
        """Test that sending without connection doesn't raise."""
        processor._websocket = None
        processor.push_frame = AsyncMock()

        # Should not raise
        frame = TTSStartedFrame()
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)


class TestUnrealEventProcessorConnection:
    """Tests for WebSocket connection handling."""

    @pytest.mark.asyncio
    async def test_connection_established(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test WebSocket connection is established."""

        async def connect_context(*args, **kwargs):
            """Mock async context manager for websockets.connect."""
            return mock_websocket

        with patch("websockets.connect") as mock_connect:
            # Set up the async context manager
            mock_connect.return_value.__aenter__ = AsyncMock(
                return_value=mock_websocket
            )
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            # Make wait_closed return immediately but then hang
            mock_websocket.wait_closed = AsyncMock(
                side_effect=asyncio.CancelledError
            )

            await processor.start()
            await asyncio.sleep(0.01)  # Let connection task run

            # Processor should be running
            assert processor._running is True

            await processor.stop()

    @pytest.mark.asyncio
    async def test_is_connected_property(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test is_connected property."""
        assert processor.is_connected is False

        processor._websocket = mock_websocket
        mock_websocket.open = True
        assert processor.is_connected is True

        mock_websocket.open = False
        assert processor.is_connected is False


class TestUnrealEventProcessorContextualAnimation:
    """Tests for contextual animation control."""

    @pytest.mark.asyncio
    async def test_send_contextual_animation(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test sending contextual animation command."""
        processor._websocket = mock_websocket

        await processor.send_contextual_animation("happy", 0.8)

        mock_websocket.send.assert_called_once()
        sent_data = json.loads(mock_websocket.send.call_args[0][0])
        assert sent_data["type"] == "contextual_animation"
        assert sent_data["emotion"] == "happy"
        assert sent_data["intensity"] == 0.8

    @pytest.mark.asyncio
    async def test_contextual_animation_clamps_intensity(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test that intensity is clamped to 0.0-1.0 range."""
        processor._websocket = mock_websocket

        # Test clamping high value
        await processor.send_contextual_animation("angry", 1.5)
        sent_data = json.loads(mock_websocket.send.call_args[0][0])
        assert sent_data["intensity"] == 1.0

        # Test clamping low value
        await processor.send_contextual_animation("sad", -0.5)
        sent_data = json.loads(mock_websocket.send.call_args[0][0])
        assert sent_data["intensity"] == 0.0

    @pytest.mark.asyncio
    async def test_all_emotions(
        self, processor: UnrealEventProcessor, mock_websocket: AsyncMock
    ) -> None:
        """Test all supported emotions."""
        processor._websocket = mock_websocket

        emotions = ["neutral", "happy", "sad", "angry", "surprised"]
        for emotion in emotions:
            await processor.send_contextual_animation(emotion, 0.5)
            sent_data = json.loads(mock_websocket.send.call_args[0][0])
            assert sent_data["emotion"] == emotion
