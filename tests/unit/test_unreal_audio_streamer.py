"""Unit tests for UnrealAudioStreamer."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from avatar.processors.unreal_audio_streamer import (
    ChunkedAudioStreamer,
    UnrealAudioStreamer,
)
from pipecat.frames.frames import OutputAudioRawFrame, TextFrame
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
    async def test_audio_frame_sent_via_udp(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that OutputAudioRawFrame is sent via UDP."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        audio_data = b"\x00\x01\x02\x03" * 100  # 400 bytes
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Verify UDP sendto called
        mock_socket.sendto.assert_called_once_with(
            audio_data, ("127.0.0.1", 8080)
        )

        # Verify stats updated
        assert processor._bytes_sent == 400
        assert processor._packets_sent == 1

        # Verify frame forwarded
        processor.push_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_unrelated_frame_passes_through(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that unrelated frames pass through without UDP calls."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        frame = TextFrame(text="Hello")
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # No UDP send
        mock_socket.sendto.assert_not_called()

        # Frame still forwarded
        processor.push_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocking_io_error_handled(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that BlockingIOError is handled gracefully."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        # Simulate buffer full
        mock_socket.sendto.side_effect = BlockingIOError()

        audio_data = b"\x00" * 100
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

        # Should not raise
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Stats should show dropped packet
        assert processor._packets_dropped == 1
        assert processor._packets_sent == 0

    @pytest.mark.asyncio
    async def test_os_error_handled(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that OSError is handled gracefully."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        mock_socket.sendto.side_effect = OSError("Network unreachable")

        audio_data = b"\x00" * 100
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)

        # Should not raise
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

    @pytest.mark.asyncio
    async def test_send_without_socket_logs_warning(
        self, processor: UnrealAudioStreamer
    ) -> None:
        """Test that sending without socket doesn't raise."""
        processor._socket = None
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
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        # Send some audio
        for i in range(5):
            audio_data = b"\x00" * 1024
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        stats = processor.get_stats()

        assert stats["packets_sent"] == 5
        assert stats["bytes_sent"] == 5120
        assert stats["KB_sent"] == 5.0
        assert stats["packets_dropped"] == 0

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
        chunked_processor._socket = mock_socket
        chunked_processor.push_frame = AsyncMock()

        # Send less than chunk size
        audio_data = b"\x00" * 500
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
        await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Should not send yet (buffered)
        mock_socket.sendto.assert_not_called()
        assert len(chunked_processor._buffer) == 500

    @pytest.mark.asyncio
    async def test_chunk_sent_when_full(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that chunk is sent when buffer reaches chunk size."""
        chunked_processor._socket = mock_socket
        chunked_processor.push_frame = AsyncMock()

        # Send more than chunk size
        audio_data = b"\x00" * 1500
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
        await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Should send one chunk of 1024 bytes
        mock_socket.sendto.assert_called_once()
        sent_data = mock_socket.sendto.call_args[0][0]
        assert len(sent_data) == 1024

        # Remaining should be buffered
        assert len(chunked_processor._buffer) == 476

    @pytest.mark.asyncio
    async def test_multiple_chunks_sent(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that multiple chunks are sent for large audio."""
        chunked_processor._socket = mock_socket
        chunked_processor.push_frame = AsyncMock()

        # Send enough for 3 chunks
        audio_data = b"\x00" * 3500
        frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
        await chunked_processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Should send 3 chunks
        assert mock_socket.sendto.call_count == 3
        assert len(chunked_processor._buffer) == 428  # 3500 - 3*1024

    @pytest.mark.asyncio
    async def test_buffer_flushed_on_stop(
        self, chunked_processor: ChunkedAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test that remaining buffer is flushed on stop."""
        chunked_processor._socket = mock_socket
        chunked_processor.push_frame = AsyncMock()

        # Add data to buffer
        chunked_processor._buffer = bytearray(b"\x00" * 500)

        await chunked_processor.stop()

        # Buffer should be flushed
        mock_socket.sendto.assert_called_once()
        sent_data = mock_socket.sendto.call_args[0][0]
        assert len(sent_data) == 500


class TestIntegrationScenarios:
    """Integration-style tests for realistic scenarios."""

    @pytest.mark.asyncio
    async def test_continuous_audio_streaming(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test continuous streaming of audio packets."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        # Simulate 100 audio frames (like real-time streaming)
        for _ in range(100):
            audio_data = b"\x00" * 1920  # 40ms of 24kHz mono
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        assert mock_socket.sendto.call_count == 100
        assert processor._packets_sent == 100
        assert processor._bytes_sent == 192000

    @pytest.mark.asyncio
    async def test_mixed_packet_drops(
        self, processor: UnrealAudioStreamer, mock_socket: MagicMock
    ) -> None:
        """Test handling of intermittent packet drops."""
        processor._socket = mock_socket
        processor.push_frame = AsyncMock()

        # Simulate some successful sends, some drops
        call_count = 0

        def side_effect(*args):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise BlockingIOError()

        mock_socket.sendto.side_effect = side_effect

        for _ in range(10):
            audio_data = b"\x00" * 100
            frame = OutputAudioRawFrame(audio=audio_data, sample_rate=24000, num_channels=1)
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Should have some sent and some dropped
        assert processor._packets_sent == 7
        assert processor._packets_dropped == 3
