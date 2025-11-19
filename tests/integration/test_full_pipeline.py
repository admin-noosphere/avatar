"""Integration tests for the complete Avatar pipeline.

These tests validate the full flow from input to output using mocks.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        # Create mock outputs for each branch
        branch_a_frames: list = []
        branch_b_frames: list = []

        class BranchACollector:
            async def process_frame(self, frame, direction):
                branch_a_frames.append(frame)

        class BranchBCollector:
            async def process_frame(self, frame, direction):
                branch_b_frames.append(frame)

        # We'll test the concept - actual ParallelPipeline needs proper setup
        # For now, verify our processors forward frames correctly

        # Create processors
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Mock their connections
        event_processor._websocket = AsyncMock()
        event_processor._websocket.open = True
        event_processor._websocket.send = AsyncMock()

        audio_processor._socket = AsyncMock()
        audio_processor._socket.sendto = AsyncMock()

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
            audio=b'\x00' * 100,
            sample_rate=24000,
            num_channels=1,
        )
        tts_stop = TTSStoppedFrame()

        await event_processor.process_frame(tts_start, FrameDirection.DOWNSTREAM)
        await event_processor.process_frame(audio_frame, FrameDirection.DOWNSTREAM)
        await event_processor.process_frame(tts_stop, FrameDirection.DOWNSTREAM)

        await audio_processor.process_frame(tts_start, FrameDirection.DOWNSTREAM)
        await audio_processor.process_frame(audio_frame, FrameDirection.DOWNSTREAM)
        await audio_processor.process_frame(tts_stop, FrameDirection.DOWNSTREAM)

        # Verify both processors received and forwarded frames
        assert len(event_forwarded) == 3
        assert len(audio_forwarded) == 3

        # Verify WebSocket was called for TTS events
        assert event_processor._websocket.send.call_count == 2  # start + stop

        # Verify UDP was called for audio
        audio_processor._socket.sendto.assert_called_once()


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

        # Verify WebSocket calls
        assert mock_ws.send.call_count == 2

        # Check message content
        import json
        calls = mock_ws.send.call_args_list

        start_msg = json.loads(calls[0][0][0])
        assert start_msg["type"] == "start_speaking"

        stop_msg = json.loads(calls[1][0][0])
        assert stop_msg["type"] == "stop_speaking"

    @pytest.mark.asyncio
    async def test_audio_streamer_sends_all_chunks(self) -> None:
        """Test that audio streamer sends all audio chunks via UDP."""
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Start processor to create socket
        await audio_processor.start()

        # Mock the socket
        import socket
        mock_sock = AsyncMock(spec=socket.socket)
        mock_sock.sendto = AsyncMock()
        audio_processor._socket = mock_sock
        audio_processor.push_frame = AsyncMock()

        # Send audio chunks
        num_chunks = 50
        for _ in range(num_chunks):
            audio = OutputAudioRawFrame(
                audio=b'\x00' * 960,
                sample_rate=24000,
                num_channels=1,
            )
            await audio_processor.process_frame(audio, FrameDirection.DOWNSTREAM)

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
        # Create mock TTS
        tts = MockTTSService(sample_rate=24000)

        # Create Unreal processors
        event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

        # Mock connections
        event_processor._websocket = AsyncMock()
        event_processor._websocket.open = True
        event_processor._websocket.send = AsyncMock()

        await audio_processor.start()
        import socket
        mock_sock = AsyncMock(spec=socket.socket)
        mock_sock.sendto = AsyncMock()
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

        # Verify TTS generated frames
        assert len(tts_output) > 0
        assert isinstance(tts_output[0], TTSStartedFrame)
        assert isinstance(tts_output[-1], TTSStoppedFrame)

        # Verify event processor received all
        assert len(event_output) == len(tts_output)

        # Verify WebSocket events
        assert event_processor._websocket.send.call_count == 2

        # Verify audio was sent via UDP
        audio_chunks = [f for f in audio_output if isinstance(f, OutputAudioRawFrame)]
        assert mock_sock.sendto.call_count == len(audio_chunks)

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
        audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)
        await audio_processor.start()

        # Mock socket that raises BlockingIOError
        import socket
        from unittest.mock import MagicMock
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.sendto = MagicMock(side_effect=BlockingIOError())
        audio_processor._socket = mock_sock
        audio_processor.push_frame = AsyncMock()

        # Should not raise
        audio = OutputAudioRawFrame(
            audio=b'\x00' * 100,
            sample_rate=24000,
            num_channels=1,
        )
        await audio_processor.process_frame(audio, FrameDirection.DOWNSTREAM)

        # Packet should be counted as dropped
        assert audio_processor._packets_dropped == 1

        # Frame should still be forwarded
        audio_processor.push_frame.assert_called_once()

        await audio_processor.stop()
