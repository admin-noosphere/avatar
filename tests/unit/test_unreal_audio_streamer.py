"""Unit tests for UnrealAudioStreamer."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from avatar.processors.unreal_audio_streamer import (
    ChunkedAudioStreamer,
    UnrealAudioStreamer,
)

# Test audio size (was TEST_AUDIO_SIZE = 640)
TEST_AUDIO_SIZE = 1024
from pipecat.frames.frames import (
    OutputAudioRawFrame,
    TextFrame,
    TTSStoppedFrame,
    StartInterruptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection


@pytest.fixture
def processor() -> UnrealAudioStreamer:
    """Create a processor instance for testing."""
    return UnrealAudioStreamer(
        host="127.0.0.1",
        port=8080,
    )


@pytest.fixture
def mock_socket() -> MagicMock:
    """Create a mock UDP socket."""
    sock = MagicMock(spec=socket.socket)
    sock.sendto = MagicMock(return_value=None)
    sock.close = MagicMock()
    sock.setblocking = MagicMock()
    sock.setsockopt = MagicMock()
    return sock


class TestUnrealAudioStreamerInit:
    """Tests for processor initialization."""

    def test_default_host_port(self) -> None:
        """Test default host and port."""
        processor = UnrealAudioStreamer()
        assert processor.host == "192.168.1.14"
        assert processor.port == 8080

    def test_custom_host_port(self) -> None:
        """Test custom host and port configuration."""
        processor = UnrealAudioStreamer(host="10.0.0.1", port=9000)
        assert processor.host == "10.0.0.1"
        assert processor.port == 9000
        assert processor._target == ("10.0.0.1", 9000)

    def test_initial_state(self) -> None:
        """Test initial processor state."""
        processor = UnrealAudioStreamer()
        assert processor._socket is None
        assert processor._bytes_sent == 0
        assert processor._packets_sent == 0
        assert processor._packets_dropped == 0
        assert processor._pending_stop_task is None


class TestUnrealAudioStreamerLifecycle:
    """Tests for processor start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_socket(
        self, processor: UnrealAudioStreamer
    ) -> None:
        """Test that start() creates a UDP socket."""
        await processor.start()

        assert processor._socket is not None
        assert processor._socket.type == socket.SOCK_DGRAM
        assert processor.is_streaming is True

        await processor.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_socket(
        self, processor: UnrealAudioStreamer
    ) -> None:
        """Test that stop() closes the socket."""
        await processor.start()
        sock = processor._socket

        await processor.stop()

        assert processor._socket is None
        assert processor.is_streaming is False

    @pytest.mark.asyncio
    async def test_stats_reset_on_start(
        self, processor: UnrealAudioStreamer
    ) -> None:
        """Test that stats are reset on start."""
        processor._bytes_sent = 1000
        processor._packets_sent = 100
        processor._packets_dropped = 10

        await processor.start()

        assert processor._bytes_sent == 0
        assert processor._packets_sent == 0
        assert processor._packets_dropped == 0

        await processor.stop()


class TestUnrealAudioStreamerFrameHandling:
    """Tests for frame processing and UDP streaming."""

    @pytest.mark.asyncio
    async def test_audio_frame_queued_and_sent(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that OutputAudioRawFrame is queued and sent via UDP."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first (required for queue system)
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send exactly one chunk worth of audio
            audio_data = b"\x00\x01" * (TEST_AUDIO_SIZE // 2)  # 640 bytes
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for async streaming to process
            await asyncio.sleep(0.05)

            # Verify UDP sendto called
            assert mock_socket.sendto.call_count >= 1

            # Verify stats updated
            assert processor._bytes_sent > 0
            assert processor._packets_sent >= 1

            await processor.stop()

    @pytest.mark.asyncio
    async def test_unrelated_frame_passes_through(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that unrelated frames pass through without UDP calls."""
        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            frame = TextFrame(text="Hello")
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # No UDP send for text frames
            mock_socket.sendto.assert_not_called()

            # Frame still forwarded
            processor.push_frame.assert_called()

            await processor.stop()

    @pytest.mark.asyncio
    async def test_tts_stopped_frame_held(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that TTSStoppedFrame is delayed based on audio duration plus padding."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send some audio (creates duration)
            audio_data = b"\x00" * 4800  # 100ms of audio at 24kHz
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Send stop frame - should create pending task
            stop_frame = TTSStoppedFrame()
            await processor.process_frame(stop_frame, FrameDirection.DOWNSTREAM)

            # Frame should be held (pending task exists)
            assert processor._pending_stop_task is not None

            # Wait for release (100ms audio + 200ms padding = 300ms)
            await asyncio.sleep(0.35)

            # Should be released now
            assert processor._pending_stop_task is None or processor._pending_stop_task.done()
            # push_frame called for: start, stop
            assert processor.push_frame.call_count >= 2

            await processor.stop()

    @pytest.mark.asyncio
    async def test_interruption_clears_buffer(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that interruption cancels pending stop task."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance with audio
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
            audio_data = b"\x00" * 4800  # 100ms of audio
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Send stop frame to create pending task
            await processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
            assert processor._pending_stop_task is not None

            # Send interruption
            interrupt = StartInterruptionFrame()
            await processor.process_frame(interrupt, FrameDirection.DOWNSTREAM)

            # Pending task should be cancelled
            assert processor._pending_stop_task is None

            await processor.stop()

    @pytest.mark.asyncio
    async def test_blocking_io_error_handled(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that BlockingIOError is handled gracefully."""
        from pipecat.frames.frames import TTSStartedFrame

        mock_socket.sendto.side_effect = BlockingIOError()

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send audio that will fail
            audio_data = b"\x00" * TEST_AUDIO_SIZE
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for async streaming to attempt send
            await asyncio.sleep(0.05)

            # Stats should show dropped packet
            assert processor._packets_dropped >= 1
            assert processor._packets_sent == 0

            await processor.stop()

    @pytest.mark.asyncio
    async def test_os_error_handled(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that OSError is handled gracefully."""
        from pipecat.frames.frames import TTSStartedFrame

        mock_socket.sendto.side_effect = OSError("Network unreachable")

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            audio_data = b"\x00" * TEST_AUDIO_SIZE
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

            # Should not raise
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.05)

            await processor.stop()

    @pytest.mark.asyncio
    async def test_queue_without_start_does_not_send(
        self, processor: UnrealAudioStreamer
    ) -> None:
        """Test that audio queued without start() doesn't crash."""
        processor.push_frame = AsyncMock()

        audio_data = b"\x00" * 100
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

        # Should not raise
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)


class TestUnrealAudioStreamerStats:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_get_stats(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test get_stats returns correct values."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send some audio (5 chunks worth)
            for i in range(5):
                audio_data = b"\x00" * TEST_AUDIO_SIZE
                frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
                await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for async processing
            await asyncio.sleep(0.2)

            stats = processor.get_stats()

            assert stats["packets_sent"] == 5
            assert stats["bytes_sent"] == 5 * TEST_AUDIO_SIZE
            assert stats["packets_dropped"] == 0
            assert "audio_duration_ms" in stats

            await processor.stop()

    def test_is_streaming_property(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test is_streaming property."""
        assert processor.is_streaming is False

        processor._socket = mock_socket
        assert processor.is_streaming is True


class TestChunkedAudioStreamer:
    """Tests for ChunkedAudioStreamer variant."""

    @pytest.fixture
    def chunked_processor(self) -> ChunkedAudioStreamer:
        """Create a chunked processor for testing."""
        return ChunkedAudioStreamer(
            host="127.0.0.1",
            port=8080,
            chunk_size=1024,
        )

    def test_chunk_size_configuration(self) -> None:
        """Test chunk size configuration."""
        processor = ChunkedAudioStreamer(chunk_size=2048)
        assert processor.chunk_size == 2048

    @pytest.mark.asyncio
    async def test_small_audio_buffered(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that small audio is buffered until chunk size reached."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await chunked_processor.start()
            chunked_processor.push_frame = AsyncMock()

            # Start an utterance first
            await chunked_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send less than chunk size
            audio_data = b"\x00" * 500
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Buffer should have data
            assert len(chunked_processor._buffer) == 500

            await chunked_processor.stop()

    @pytest.mark.asyncio
    async def test_chunk_sent_when_full(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that chunk is sent when buffer reaches chunk size."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await chunked_processor.start()
            chunked_processor.push_frame = AsyncMock()

            # Start an utterance first
            await chunked_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send more than chunk size
            audio_data = b"\x00" * 1500
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for processing
            await asyncio.sleep(0.1)

            # Should send chunks
            assert mock_socket.sendto.call_count >= 1

            # Remaining should be buffered
            assert len(chunked_processor._buffer) == 476  # 1500 - 1024

            await chunked_processor.stop()

    @pytest.mark.asyncio
    async def test_multiple_chunks_sent(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that multiple chunks are sent for large audio."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await chunked_processor.start()
            chunked_processor.push_frame = AsyncMock()

            # Start an utterance first
            await chunked_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send enough for 3 chunks (3 * 1024 = 3072 bytes of chunked data)
            audio_data = b"\x00" * 3500
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for processing
            await asyncio.sleep(0.2)

            # Should send multiple chunks (accounting for 640-byte sub-chunking)
            assert mock_socket.sendto.call_count >= 3
            assert len(chunked_processor._buffer) == 428  # 3500 - 3*1024

            await chunked_processor.stop()

    @pytest.mark.asyncio
    async def test_buffer_flushed_on_stop(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that remaining buffer is flushed on stop."""
        with patch("socket.socket", return_value=mock_socket):
            await chunked_processor.start()
            chunked_processor.push_frame = AsyncMock()

            # Add data to buffer directly
            chunked_processor._buffer = bytearray(b"\x00" * 500)

            await chunked_processor.stop()

            # Buffer should be flushed via queue
            assert len(chunked_processor._buffer) == 0


class TestIntegrationScenarios:
    """Integration-style tests for realistic scenarios."""

    @pytest.mark.asyncio
    async def test_continuous_audio_streaming(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test continuous streaming of audio packets."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Simulate 10 audio frames (like real-time streaming)
            # Using exact chunk size for predictable behavior
            for _ in range(10):
                audio_data = b"\x00" * TEST_AUDIO_SIZE
                frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
                await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for async streaming to process all
            await asyncio.sleep(0.3)

            assert mock_socket.sendto.call_count == 10
            assert processor._packets_sent == 10
            assert processor._bytes_sent == 10 * TEST_AUDIO_SIZE

            await processor.stop()

    @pytest.mark.asyncio
    async def test_mixed_packet_drops(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test handling of intermittent packet drops with retry logic."""
        from pipecat.frames.frames import TTSStartedFrame

        # Simulate persistent failures (all retries fail)
        # BlockingIOError on every call so retries also fail
        mock_socket.sendto.side_effect = BlockingIOError()

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            processor.push_frame = AsyncMock()

            # Start an utterance first
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            for _ in range(5):
                audio_data = b"\x00" * TEST_AUDIO_SIZE
                frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
                await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

            # Wait for async processing
            await asyncio.sleep(0.3)

            # All packets should be dropped (retries all failed)
            assert processor._packets_sent == 0
            assert processor._packets_dropped == 5

            await processor.stop()

    @pytest.mark.asyncio
    async def test_stop_frame_sync(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that TTSStoppedFrame waits for audio to finish plus safety padding."""
        from pipecat.frames.frames import TTSStartedFrame

        with patch("socket.socket", return_value=mock_socket):
            await processor.start()
            pushed_frames = []

            async def capture_push(frame, direction):
                pushed_frames.append(frame)

            processor.push_frame = capture_push

            # Start utterance
            await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

            # Send audio (creates duration) - 5*1024 bytes at 24kHz = ~106ms
            audio_data = b"\x00" * (TEST_AUDIO_SIZE * 5)
            audio_frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(audio_frame, FrameDirection.DOWNSTREAM)

            # Send stop frame
            stop_frame = TTSStoppedFrame()
            await processor.process_frame(stop_frame, FrameDirection.DOWNSTREAM)

            # Stop frame should be held (pending task)
            assert processor._pending_stop_task is not None

            # Wait for all audio duration + padding to elapse (~106ms + 200ms = 306ms)
            await asyncio.sleep(0.4)

            # Stop frame should now be released
            assert processor._pending_stop_task is None or processor._pending_stop_task.done()
            assert any(isinstance(f, TTSStoppedFrame) for f in pushed_frames)

            await processor.stop()
