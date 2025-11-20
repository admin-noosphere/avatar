"""UnrealAudioStreamer - UDP audio streaming to Audio2Face.

This processor receives OutputAudioRawFrame frames and streams the raw PCM
audio data via UDP to NVIDIA Audio2Face for real-time lip-sync animation
on MetaHuman avatars.

Audio must be sent in chunks of 640 bytes (320 samples @ 16-bit) at 75 FPS
(13.33ms per chunk) for proper lip-sync synchronization.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from pipecat.frames.frames import Frame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# Audio2Face chunking constants
CHUNK_SIZE_SAMPLES = 320  # 320 samples per chunk
CHUNK_SIZE_BYTES = CHUNK_SIZE_SAMPLES * 2  # 640 bytes (16-bit samples)
CHUNK_DELAY = 0.01333  # 13.33ms = 75 FPS


class UnrealAudioStreamer(FrameProcessor):
    """Processor that streams audio via UDP to Audio2Face.

    This processor receives audio frames from the pipeline and forwards
    them as raw PCM bytes over UDP to Audio2Face for lip-sync animation.
    The socket is non-blocking to maintain real-time performance.

    Attributes:
        host: UDP target host address.
        port: UDP target port.
    """

    def __init__(
        self,
        host: str = "192.168.1.14",
        port: int = 8080,
        **kwargs: Any,
    ) -> None:
        """Initialize the UnrealAudioStreamer.

        Args:
            host: UDP target host for Audio2Face.
            port: UDP target port for Audio2Face.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self.host = host
        self.port = port
        self._target = (host, port)

        self._socket: socket.socket | None = None
        self._bytes_sent = 0
        self._packets_sent = 0
        self._packets_dropped = 0
        self._buffer = bytearray()  # Buffer for chunking
        self._stream_task: asyncio.Task | None = None
        self._audio_queue: asyncio.Queue | None = None

    async def start(self) -> None:
        """Start the processor and create UDP socket."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)

        # Set socket buffer size for smoother streaming
        try:
            self._socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_SNDBUF, 65536
            )
        except OSError as e:
            logger.warning(f"Could not set socket buffer size: {e}")

        self._bytes_sent = 0
        self._packets_sent = 0
        self._packets_dropped = 0
        self._buffer = bytearray()

        # Create audio queue for rate-controlled streaming
        self._audio_queue = asyncio.Queue()
        self._stream_task = asyncio.create_task(self._stream_audio_loop())

        logger.info(
            f"UnrealAudioStreamer started, streaming to {self.host}:{self.port} "
            f"(chunk_size={CHUNK_SIZE_BYTES} bytes @ {1/CHUNK_DELAY:.0f} FPS)"
        )

    async def stop(self) -> None:
        """Stop the processor and close UDP socket."""
        # Stop streaming task
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None

        # Flush remaining buffer
        if self._buffer and self._socket:
            # Pad to chunk size if needed
            if len(self._buffer) > 0:
                padding = CHUNK_SIZE_BYTES - (len(self._buffer) % CHUNK_SIZE_BYTES)
                if padding < CHUNK_SIZE_BYTES:
                    self._buffer.extend(b'\x00' * padding)
                # Send remaining chunks
                while len(self._buffer) >= CHUNK_SIZE_BYTES:
                    chunk = bytes(self._buffer[:CHUNK_SIZE_BYTES])
                    self._buffer = self._buffer[CHUNK_SIZE_BYTES:]
                    self._send_chunk(chunk)

        if self._socket:
            self._socket.close()
            self._socket = None

        logger.info(
            f"UnrealAudioStreamer stopped. "
            f"Stats: {self._packets_sent} packets sent, "
            f"{self._packets_dropped} dropped, "
            f"{self._bytes_sent / 1024:.1f} KB total"
        )

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        """Process incoming frames and stream audio via UDP.

        Args:
            frame: The frame to process.
            direction: The direction of frame flow (upstream/downstream).
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputAudioRawFrame):
            logger.info(f"Received audio frame: {len(frame.audio)} bytes")
            await self._send_audio(frame.audio)

        # Forward frame downstream (for any subsequent processors)
        await self.push_frame(frame, direction)

    async def _send_audio(self, audio_data: bytes) -> None:
        """Buffer audio and queue chunks for rate-controlled streaming.

        Audio is buffered and sent in 640-byte chunks at 75 FPS for
        proper Audio2Face lip-sync synchronization.

        Args:
            audio_data: Raw PCM audio bytes to buffer.
        """
        if not self._audio_queue:
            logger.warning("Cannot send audio: queue not initialized")
            return

        # Add to buffer
        self._buffer.extend(audio_data)

        # Log first audio received
        if self._packets_sent == 0 and len(self._buffer) >= CHUNK_SIZE_BYTES:
            logger.info(f"First audio received: {len(audio_data)} bytes, buffer now {len(self._buffer)} bytes")

        # Queue complete chunks
        chunks_queued = 0
        while len(self._buffer) >= CHUNK_SIZE_BYTES:
            chunk = bytes(self._buffer[:CHUNK_SIZE_BYTES])
            self._buffer = self._buffer[CHUNK_SIZE_BYTES:]
            await self._audio_queue.put(chunk)
            chunks_queued += 1

        if chunks_queued > 0:
            logger.debug(f"Queued {chunks_queued} chunks, queue size: {self._audio_queue.qsize()}")

    async def _stream_audio_loop(self) -> None:
        """Background task that sends audio chunks at controlled rate (75 FPS)."""
        last_send_time = time.monotonic()

        while True:
            try:
                # Wait for chunk with timeout
                try:
                    chunk = await asyncio.wait_for(
                        self._audio_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                # Rate control: ensure minimum delay between chunks
                now = time.monotonic()
                elapsed = now - last_send_time
                if elapsed < CHUNK_DELAY:
                    await asyncio.sleep(CHUNK_DELAY - elapsed)

                # Send chunk
                self._send_chunk(chunk)
                last_send_time = time.monotonic()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stream loop error: {e}")

    def _send_chunk(self, chunk: bytes) -> None:
        """Send a single chunk via UDP.

        Args:
            chunk: 640-byte audio chunk to send.
        """
        if not self._socket:
            return

        try:
            self._socket.sendto(chunk, self._target)
            self._bytes_sent += len(chunk)
            self._packets_sent += 1

            if self._packets_sent % 1000 == 0:
                logger.debug(
                    f"Audio streaming stats: {self._packets_sent} packets, "
                    f"{self._bytes_sent / 1024:.1f} KB"
                )

        except BlockingIOError:
            self._packets_dropped += 1
            if self._packets_dropped % 100 == 0:
                logger.warning(
                    f"UDP buffer overflow: {self._packets_dropped} packets dropped"
                )

        except OSError as e:
            logger.error(f"UDP send error: {e}")

    def get_stats(self) -> dict[str, int | float]:
        """Get streaming statistics.

        Returns:
            Dictionary with packets_sent, packets_dropped, bytes_sent, and KB_sent.
        """
        return {
            "packets_sent": self._packets_sent,
            "packets_dropped": self._packets_dropped,
            "bytes_sent": self._bytes_sent,
            "KB_sent": self._bytes_sent / 1024,
        }

    @property
    def is_streaming(self) -> bool:
        """Check if the streamer is active.

        Returns:
            True if socket is initialized and ready, False otherwise.
        """
        return self._socket is not None


class ChunkedAudioStreamer(UnrealAudioStreamer):
    """Audio streamer with chunk size control for network optimization.

    This variant allows control over UDP packet sizes to optimize for
    different network conditions. Smaller chunks reduce latency but
    increase overhead; larger chunks are more efficient but add latency.
    """

    def __init__(
        self,
        host: str = "192.168.1.14",
        port: int = 8080,
        chunk_size: int = 4096,
        **kwargs: Any,
    ) -> None:
        """Initialize the ChunkedAudioStreamer.

        Args:
            host: UDP target host for Audio2Face.
            port: UDP target port for Audio2Face.
            chunk_size: Maximum UDP packet size in bytes.
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(host, port, **kwargs)
        self.chunk_size = chunk_size
        self._buffer = bytearray()

    async def _send_audio(self, audio_data: bytes) -> None:
        """Buffer and send audio in fixed-size chunks.

        Args:
            audio_data: Raw PCM audio bytes to buffer and send.
        """
        self._buffer.extend(audio_data)

        # Send complete chunks
        while len(self._buffer) >= self.chunk_size:
            chunk = bytes(self._buffer[: self.chunk_size])
            self._buffer = self._buffer[self.chunk_size :]
            await super()._send_audio(chunk)

    async def stop(self) -> None:
        """Flush remaining buffer before stopping."""
        # Send any remaining buffered audio
        if self._buffer and self._socket:
            await super()._send_audio(bytes(self._buffer))
            self._buffer.clear()

        await super().stop()
