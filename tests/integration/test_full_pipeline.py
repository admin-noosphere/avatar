"""Integration tests for the complete Avatar pipeline.

These tests validate the full flow from input to output using mocks.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "claude_dev"))

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.frames.frames import (
    OutputAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer

# Test audio size
TEST_AUDIO_SIZE = 1024

from mock_daily_transport import (
    MockDailyTransport,
    MockDailyInput,
    MockDailyOutput,
    MockSTTService,
    MockLLMService,
    MockTTSService,
)


class TestParallelPipelineBranching:
    """Test that ParallelPipeline correctly splits frames to both branches."""

    @pytest.mark.asyncio
    async def test_frames_reach_both_branches(self) -> None:
        """Test that frames are sent to both branches of ParallelPipeline."""
        # Create mock socket for audio processor
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto = MagicMock(return_value=None)
        mock_sock.close = MagicMock()
        mock_sock.setblocking = MagicMock()
        mock_sock.setsockopt = MagicMock()

        # Create processors
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Start audio processor and inject mock socket
        await audio_processor.start()
        audio_processor._socket = mock_sock

        # Mock WebSocket for event processor
        event_processor._websocket = AsyncMock()
        event_processor._websocket.open = True
        event_processor._websocket.send = AsyncMock()

        # Track forwarded frames
        event_forwarded = []
        audio_forwarded = []

        async def event_push(frame, direction):
            event_forwarded.append(frame)

        async def audio_push(frame, direction):
            audio_forwarded.append(frame)

        event_processor.push_frame = event_push
        audio_processor.push_frame = audio_push

        # Send frames
        tts_start = TTSStartedFrame()
        audio_frame = OutputAudioRawFrame(
            audio=b'\x00' * TEST_AUDIO_SIZE,  # Use exact chunk size
            sample_rate=24000,
            num_channels=1,
        )
        tts_stop = TTSStoppedFrame()

        # Process through event processor (forwards all frames)
        await event_processor.process_frame(tts_start, FrameDirection.DOWNSTREAM)
        await event_processor.process_frame(audio_frame, FrameDirection.DOWNSTREAM)
        await event_processor.process_frame(tts_stop, FrameDirection.DOWNSTREAM)

        # Process through audio processor
        await audio_processor.process_frame(tts_start, FrameDirection.DOWNSTREAM)
        await audio_processor.process_frame(audio_frame, FrameDirection.DOWNSTREAM)
        await audio_processor.process_frame(tts_stop, FrameDirection.DOWNSTREAM)

        # Wait for async processing (audio ~21ms + 200ms safety padding)
        await asyncio.sleep(0.3)

        # Event processor forwards all frames
        assert len(event_forwarded) == 3

        # Audio processor only forwards non-audio frames (start + stop)
        # Note: TTSStoppedFrame is released after audio duration + safety padding
        assert len(audio_forwarded) == 2  # start and stop (audio not forwarded)

        # Verify WebSocket was called for TTS events
        # Each event sends 2 messages: start sends (start_speaking + start_audio_stream)
        # stop sends (end_audio_stream + stop_speaking)
        assert event_processor._websocket.send.call_count == 4

        # Verify UDP was called for audio
        assert mock_sock.sendto.call_count >= 1

        await audio_processor.stop()


class TestMockServices:
    """Test mock services work correctly."""

    @pytest.mark.asyncio
    async def test_mock_tts_generates_audio(self) -> None:
        """Test MockTTSService generates audio frames."""
        tts = MockTTSService(sample_rate=24000)

        frames_received = []

        async def capture(frame, direction):
            frames_received.append(frame)

        tts.push_frame = capture

        # Send text
        text_frame = TextFrame(text="Hello world")
        await tts.process_frame(text_frame, FrameDirection.DOWNSTREAM)

        # Should have: TTSStarted, audio chunks, TTSStopped
        assert len(frames_received) >= 3

        # First should be TTSStarted
        assert isinstance(frames_received[0], TTSStartedFrame)

        # Last should be TTSStopped
        assert isinstance(frames_received[-1], TTSStoppedFrame)

        # Middle should be audio
        audio_frames = [f for f in frames_received if isinstance(f, OutputAudioRawFrame)]
        assert len(audio_frames) > 0

    @pytest.mark.asyncio
    async def test_mock_daily_output_captures_frames(self) -> None:
        """Test MockDailyOutput captures all frames."""
        output = MockDailyOutput()

        # Send various frames
        await output.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        for i in range(5):
            audio = OutputAudioRawFrame(
                audio=b'\x00' * 100,
                sample_rate=24000,
                num_channels=1,
            )
            await output.process_frame(audio, FrameDirection.DOWNSTREAM)

        await output.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

        # Verify capture
        stats = output.get_stats()
        assert stats["audio_frames"] == 5
        assert stats["total_frames"] == 7  # start + 5 audio + stop


class TestUnrealProcessorsIntegration:
    """Test Unreal processors working together."""

    @pytest.mark.asyncio
    async def test_tts_flow_sends_correct_events(self) -> None:
        """Test that TTS flow sends correct WebSocket events."""
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.send = AsyncMock()
        event_processor._websocket = mock_ws
        event_processor.push_frame = AsyncMock()

        # Simulate TTS flow
        await event_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        # Send some audio (event processor should pass through)
        for _ in range(10):
            audio = OutputAudioRawFrame(
                audio=b'\x00' * 100,
                sample_rate=24000,
                num_channels=1,
            )
            await event_processor.process_frame(audio, FrameDirection.DOWNSTREAM)

        await event_processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

        # Verify WebSocket calls (4 total: start_speaking, start_audio_stream, end_audio_stream, stop_speaking)
        assert mock_ws.send.call_count == 4

        # Check message content
        import json
        calls = mock_ws.send.call_args_list

        start_msg = json.loads(calls[0][0][0])
        assert start_msg["type"] == "start_speaking"

        stream_start_msg = json.loads(calls[1][0][0])
        assert stream_start_msg["type"] == "start_audio_stream"

        stream_end_msg = json.loads(calls[2][0][0])
        assert stream_end_msg["type"] == "end_audio_stream"

        stop_msg = json.loads(calls[3][0][0])
        assert stop_msg["type"] == "stop_speaking"

    @pytest.mark.asyncio
    async def test_audio_streamer_sends_all_chunks(self) -> None:
        """Test that audio streamer sends all audio chunks via UDP."""
        # Create mock socket
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto = MagicMock(return_value=None)
        mock_sock.close = MagicMock()
        mock_sock.setblocking = MagicMock()
        mock_sock.setsockopt = MagicMock()

        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Start processor and inject mock socket
        await audio_processor.start()
        audio_processor._socket = mock_sock
        audio_processor.push_frame = AsyncMock()

        # Start an utterance first (required for queue system)
        await audio_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        # Send audio chunks (use exact chunk size for predictable behavior)
        num_chunks = 10
        for _ in range(num_chunks):
            audio = OutputAudioRawFrame(
                audio=b'\x00' * TEST_AUDIO_SIZE,
                sample_rate=24000,
                num_channels=1,
            )
            await audio_processor.process_frame(audio, FrameDirection.DOWNSTREAM)

        # Wait for async streaming to process
        await asyncio.sleep(0.3)

        # Verify all chunks sent
        assert mock_sock.sendto.call_count == num_chunks

        # Verify stats
        stats = audio_processor.get_stats()
        assert stats["packets_sent"] == num_chunks

        await audio_processor.stop()


class TestEndToEndFlow:
    """Test complete end-to-end flow with mocks."""

    @pytest.mark.asyncio
    async def test_text_to_unreal_flow(self) -> None:
        """Test flow from text input to Unreal output."""
        # Create mock socket
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto = MagicMock(return_value=None)
        mock_sock.close = MagicMock()
        mock_sock.setblocking = MagicMock()
        mock_sock.setsockopt = MagicMock()

        # Create mock TTS
        tts = MockTTSService(sample_rate=24000)

        # Create Unreal processors
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Mock WebSocket
        event_processor._websocket = AsyncMock()
        event_processor._websocket.open = True
        event_processor._websocket.send = AsyncMock()

        # Start audio processor and inject mock socket
        await audio_processor.start()
        audio_processor._socket = mock_sock

        # Collect frames at each stage
        tts_output = []
        event_output = []
        audio_output = []

        async def tts_push(frame, direction):
            tts_output.append(frame)
            # Forward to event processor
            await event_processor.process_frame(frame, direction)

        async def event_push(frame, direction):
            event_output.append(frame)
            # Forward to audio processor
            await audio_processor.process_frame(frame, direction)

        async def audio_push(frame, direction):
            audio_output.append(frame)

        tts.push_frame = tts_push
        event_processor.push_frame = event_push
        audio_processor.push_frame = audio_push

        # Process text
        text = TextFrame(text="Bonjour comment allez vous")
        await tts.process_frame(text, FrameDirection.DOWNSTREAM)

        # Wait for async streaming to complete
        # MockTTSService generates ~400ms of audio (4 words × 100ms)
        # At 75 FPS that's ~30 chunks, needs at least 400ms + buffer time
        await asyncio.sleep(1.0)

        # Verify TTS generated frames
        assert len(tts_output) > 0
        assert isinstance(tts_output[0], TTSStartedFrame)
        assert isinstance(tts_output[-1], TTSStoppedFrame)

        # Verify event processor received all
        assert len(event_output) == len(tts_output)

        # Verify WebSocket events (4 total)
        assert event_processor._websocket.send.call_count == 4

        # Audio processor only forwards non-audio frames
        # (TTSStartedFrame + TTSStoppedFrame, no OutputAudioRawFrames)
        assert len(audio_output) == 2

        # Verify audio was sent via UDP
        assert mock_sock.sendto.call_count > 0

        await audio_processor.stop()


class TestErrorHandling:
    """Test error handling in pipeline."""

    @pytest.mark.asyncio
    async def test_websocket_disconnection_handling(self) -> None:
        """Test that WebSocket disconnection doesn't crash pipeline."""
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")

        # No WebSocket connected
        event_processor._websocket = None
        event_processor.push_frame = AsyncMock()

        # Should not raise
        await event_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        # Frame should still be forwarded
        event_processor.push_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_udp_buffer_overflow_handling(self) -> None:
        """Test that UDP buffer overflow is handled gracefully."""
        # Create mock socket that raises BlockingIOError
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto = MagicMock(side_effect=BlockingIOError())
        mock_sock.close = MagicMock()
        mock_sock.setblocking = MagicMock()
        mock_sock.setsockopt = MagicMock()

        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Start processor and inject mock socket
        await audio_processor.start()
        audio_processor._socket = mock_sock
        audio_processor.push_frame = AsyncMock()

        # Start an utterance first (required for queue system)
        await audio_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        # Should not raise
        audio = OutputAudioRawFrame(
            audio=b'\x00' * TEST_AUDIO_SIZE,
            sample_rate=24000,
            num_channels=1,
        )
        await audio_processor.process_frame(audio, FrameDirection.DOWNSTREAM)

        # Wait for async processing
        await asyncio.sleep(0.05)

        # Packet should be counted as dropped
        assert audio_processor._packets_dropped >= 1

        await audio_processor.stop()
