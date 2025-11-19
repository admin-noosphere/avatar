"""UnrealAudioStreamer - UDP audio streaming to Audio2Face.

This processor receives OutputAudioRawFrame frames and streams the raw PCM
audio data via UDP to NVIDIA Audio2Face for real-time lip-sync animation
on MetaHuman avatars.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from pipecat.frames.frames import Frame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


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

        logger.info(
            f"UnrealAudioStreamer started, streaming to {self.host}:{self.port}"
        )

    async def stop(self) -> None:
        """Stop the processor and close UDP socket."""
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
            await self._send_audio(frame.audio)

        # Forward frame downstream (for any subsequent processors)
        await self.push_frame(frame, direction)

    async def _send_audio(self, audio_data: bytes) -> None:
        """Send raw audio bytes via UDP.

        Uses non-blocking socket to prevent pipeline stalls. Packets are
        dropped under extreme load to maintain real-time behavior.

        Args:
            audio_data: Raw PCM audio bytes to send.
        """
        if not self._socket:
            logger.warning("Cannot send audio: socket not initialized")
            return

        try:
            # Non-blocking send
            self._socket.sendto(audio_data, self._target)
            self._bytes_sent += len(audio_data)
            self._packets_sent += 1

            if self._packets_sent % 1000 == 0:
                logger.debug(
                    f"Audio streaming stats: {self._packets_sent} packets, "
                    f"{self._bytes_sent / 1024:.1f} KB"
                )

        except BlockingIOError:
            # Socket buffer full - drop packet to maintain real-time
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
