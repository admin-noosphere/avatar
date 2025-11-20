"""UnrealAudioStreamer - UDP audio streaming with complete buffer playback.

This processor accumulates ALL audio chunks from TTS, then plays the complete
buffer via UDP to ensure coherent audio stream to Audio2Face.

Flow:
1. TTSStartedFrame → Create new utterance buffer
2. OutputAudioRawFrame → Accumulate in buffer (don't send yet)
3. TTSStoppedFrame → Play ENTIRE buffer via UDP, then send stop event

This ensures Unreal receives complete, uninterrupted audio with exact duration.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    InterruptionFrame,
    CancelFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# Audio constants
DEFAULT_SAMPLE_RATE = 24000  # Hz
BYTES_PER_SAMPLE = 2  # 16-bit
DEFAULT_CHANNELS = 1

# UDP packet size limit (safe for most networks)
UDP_MAX_PACKET_SIZE = 8192  # 8KB chunks for reliable UDP transmission


@dataclass
class Utterance:
    """Represents a complete utterance with all its audio data."""
    utterance_id: int
    audio_data: bytearray = field(default_factory=bytearray)
    sample_rate: int = DEFAULT_SAMPLE_RATE
    num_channels: int = DEFAULT_CHANNELS
    chunk_count: int = 0
    is_complete: bool = False  # True when TTSStoppedFrame received
    direction: FrameDirection = FrameDirection.DOWNSTREAM
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float = 0.0

    @property
    def audio_duration_ms(self) -> float:
        """Calculate audio duration in milliseconds from buffer size."""
        if not self.audio_data:
            return 0.0
        bytes_per_sample = BYTES_PER_SAMPLE * self.num_channels
        samples = len(self.audio_data) / bytes_per_sample
        return (samples / self.sample_rate) * 1000

    @property
    def audio_bytes(self) -> int:
        """Total bytes in buffer."""
        return len(self.audio_data)


class UnrealAudioStreamer(FrameProcessor):
    """Processor that buffers complete TTS audio then streams via UDP.

    Key behavior:
    - Accumulates ALL audio chunks until TTSStoppedFrame
    - Only then sends complete audio via UDP
    - Ensures coherent stream with exact duration for Unreal animations
    """

    def __init__(
        self,
        host: str = "192.168.1.14",
        port: int = 8080,
        playback_speed: float = 1.0,  # For simulating real-time playback
        **kwargs: Any,
    ) -> None:
        """Initialize the UnrealAudioStreamer.

        Args:
            host: UDP target host for Audio2Face.
            port: UDP target port for Audio2Face.
            playback_speed: Speed multiplier for UDP sending (1.0 = real-time).
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self.host = host
        self.port = port
        self._target = (host, port)
        self._playback_speed = playback_speed

        self._socket: socket.socket | None = None

        # Statistics
        self._total_bytes_sent = 0
        self._total_packets_sent = 0
        self._total_packets_dropped = 0
        self._total_utterances_completed = 0

        # Utterance management
        self._utterance_counter: int = 0
        self._current_utterance: Utterance | None = None
        self._utterance_queue: list[Utterance] = []

        # Playback task
        self._playback_task: asyncio.Task | None = None
        self._is_playing: bool = False

        # Debug history (last N utterances)
        self._utterance_history: list[dict] = []
        self._max_history = 20

    async def start(self) -> None:
        """Start the processor and create UDP socket."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)

        # Set socket buffer size for smoother streaming
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        except OSError as e:
            logger.warning(f"Could not set socket buffer size: {e}")

        # Reset state
        self._total_bytes_sent = 0
        self._total_packets_sent = 0
        self._total_packets_dropped = 0
        self._total_utterances_completed = 0
        self._utterance_counter = 0
        self._current_utterance = None
        self._utterance_queue = []
        self._is_playing = False

        logger.info(f"🎙️ UnrealAudioStreamer started → {self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the processor and close UDP socket."""
        # Cancel any playback task
        if self._playback_task:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None

        if self._socket:
            self._socket.close()
            self._socket = None

        logger.info(
            f"🎙️ UnrealAudioStreamer stopped | "
            f"Utterances: {self._total_utterances_completed} | "
            f"Packets: {self._total_packets_sent} | "
            f"Dropped: {self._total_packets_dropped} | "
            f"Total: {self._total_bytes_sent / 1024:.1f} KB"
        )

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        """Process incoming frames.

        Args:
            frame: The frame to process.
            direction: The direction of frame flow.
        """
        await super().process_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 1. TTSStartedFrame → Create new utterance buffer
        # ═══════════════════════════════════════════════════════════════
        if isinstance(frame, TTSStartedFrame):
            self._utterance_counter += 1
            utterance = Utterance(
                utterance_id=self._utterance_counter,
                direction=direction,
            )

            # Add to queue
            self._utterance_queue.append(utterance)

            logger.info(
                f"📝 Utterance #{utterance.utterance_id} created | "
                f"Queue size: {len(self._utterance_queue)}"
            )

            # Forward the frame
            await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 2. OutputAudioRawFrame → Accumulate in buffer (DON'T SEND YET)
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, OutputAudioRawFrame):
            audio_data = frame.audio
            audio_len = len(audio_data)
            sample_rate = frame.sample_rate or DEFAULT_SAMPLE_RATE
            num_channels = frame.num_channels or DEFAULT_CHANNELS

            # Find the utterance to add audio to
            # Priority: last incomplete one, or first complete one still in queue (being played)
            target = None

            # First try to find an incomplete utterance
            for utt in reversed(self._utterance_queue):
                if not utt.is_complete:
                    target = utt
                    break

            # If no incomplete, use the first one in queue (being played)
            if not target and self._utterance_queue:
                target = self._utterance_queue[0]

            if target:
                # Update sample rate/channels from first chunk
                if target.chunk_count == 0:
                    target.sample_rate = sample_rate
                    target.num_channels = num_channels

                # Accumulate audio
                target.audio_data.extend(audio_data)
                target.chunk_count += 1

                logger.debug(
                    f"🔊 Utterance #{target.utterance_id} chunk {target.chunk_count}: "
                    f"+{audio_len} bytes | "
                    f"Total: {target.audio_bytes} bytes ({target.audio_duration_ms:.0f}ms)"
                )
            else:
                logger.warning(
                    f"⚠️ Audio chunk received but no active utterance! "
                    f"({audio_len} bytes dropped)"
                )

        # ═══════════════════════════════════════════════════════════════
        # 3. TTSStoppedFrame → Mark complete, start playback if not playing
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, TTSStoppedFrame):
            # Find the utterance to complete (first incomplete one)
            target = None
            for utt in self._utterance_queue:
                if not utt.is_complete:
                    target = utt
                    break

            if target:
                target.is_complete = True
                target.completed_at = time.monotonic()

                buffer_time = (target.completed_at - target.created_at) * 1000

                logger.info(
                    f"✅ Utterance #{target.utterance_id} complete | "
                    f"Chunks: {target.chunk_count} | "
                    f"Size: {target.audio_bytes} bytes | "
                    f"Duration: {target.audio_duration_ms:.0f}ms | "
                    f"Buffer time: {buffer_time:.0f}ms"
                )

                # Save to history for debugging
                self._save_to_history(target)

                # Start playback if not already playing
                if not self._is_playing:
                    self._playback_task = asyncio.create_task(
                        self._play_queue()
                    )
            else:
                logger.warning("⚠️ TTSStoppedFrame but no incomplete utterance found")
                await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 4. Interruption → Cancel everything and stop audio
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, (InterruptionFrame, CancelFrame)):
            # Log what we're canceling
            pending = [u for u in self._utterance_queue if not u.is_complete]
            complete = [u for u in self._utterance_queue if u.is_complete]

            logger.info(
                f"🛑 INTERRUPTION | "
                f"Canceling {len(pending)} pending + {len(complete)} complete utterances | "
                f"Was playing: {self._is_playing}"
            )

            # Cancel playback task (don't await - let it cancel in background)
            if self._playback_task:
                self._playback_task.cancel()
                self._playback_task = None

            # Clear ALL queued utterances
            self._utterance_queue = []
            self._is_playing = False

            # Forward interruption to EventProcessor so it sends stop_speaking
            await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 5. Other frames → Pass through (with debug for system frames)
        # ═══════════════════════════════════════════════════════════════
        else:
            frame_name = type(frame).__name__
            # Log system/control frames for debugging
            if "Interrupt" in frame_name or "Cancel" in frame_name or "Stop" in frame_name:
                logger.info(f"🔍 Frame passthrough: {frame_name}")
            await self.push_frame(frame, direction)

    async def _play_queue(self) -> None:
        """Play all complete utterances in the queue sequentially."""
        self._is_playing = True

        try:
            while True:
                # Find next complete utterance (don't pop yet - keep for late chunks)
                utterance = None
                utterance_index = -1
                for i, utt in enumerate(self._utterance_queue):
                    if utt.is_complete:
                        utterance = utt
                        utterance_index = i
                        break

                if not utterance:
                    # No complete utterance, wait a bit and check again
                    await asyncio.sleep(0.01)

                    # Check if there are any incomplete utterances
                    has_incomplete = any(not u.is_complete for u in self._utterance_queue)
                    if not has_incomplete:
                        # Queue is empty
                        if not self._utterance_queue:
                            break
                        continue
                    continue

                # Play this utterance
                await self._play_utterance(utterance)

                # NOW remove from queue after playback is done
                if utterance_index >= 0 and utterance_index < len(self._utterance_queue):
                    self._utterance_queue.pop(utterance_index)

        except asyncio.CancelledError:
            logger.debug("🛑 Playback cancelled")
            raise
        finally:
            self._is_playing = False

    async def _play_utterance(self, utterance: Utterance) -> None:
        """Play a single utterance via UDP.

        Args:
            utterance: The complete utterance to play.
        """
        if not utterance.audio_data:
            logger.warning(f"⚠️ Utterance #{utterance.utterance_id} has no audio data!")
            # Still forward the stop frame
            await self.push_frame(TTSStoppedFrame(), utterance.direction)
            return

        start_time = time.monotonic()
        audio_data = bytes(utterance.audio_data)
        total_bytes = len(audio_data)

        logger.info(
            f"▶️ Playing utterance #{utterance.utterance_id} | "
            f"{total_bytes} bytes | "
            f"{utterance.audio_duration_ms:.0f}ms | "
            f"{utterance.chunk_count} chunks"
        )

        # Send audio in UDP packets
        packets_sent = 0
        bytes_sent = 0
        packets_dropped = 0

        for i in range(0, total_bytes, UDP_MAX_PACKET_SIZE):
            chunk = audio_data[i:i + UDP_MAX_PACKET_SIZE]

            if self._send_udp_packet(chunk):
                packets_sent += 1
                bytes_sent += len(chunk)
            else:
                packets_dropped += 1

        # Calculate actual send time
        send_time = (time.monotonic() - start_time) * 1000

        # Wait for audio duration to complete (simulate real-time playback)
        # This ensures stop_speaking is sent at the right time
        remaining_ms = utterance.audio_duration_ms - send_time
        if remaining_ms > 0:
            await asyncio.sleep(remaining_ms / 1000)

        # Update stats
        self._total_bytes_sent += bytes_sent
        self._total_packets_sent += packets_sent
        self._total_packets_dropped += packets_dropped
        self._total_utterances_completed += 1

        elapsed = (time.monotonic() - start_time) * 1000

        logger.info(
            f"⏹️ Utterance #{utterance.utterance_id} finished | "
            f"Packets: {packets_sent} sent, {packets_dropped} dropped | "
            f"Bytes: {bytes_sent} | "
            f"Expected: {utterance.audio_duration_ms:.0f}ms | "
            f"Actual: {elapsed:.0f}ms"
        )

        # NOW send the stop frame - audio is complete
        await self.push_frame(TTSStoppedFrame(), utterance.direction)

    def _send_udp_packet(self, data: bytes) -> bool:
        """Send a single UDP packet.

        Args:
            data: Bytes to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._socket:
            return False

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._socket.sendto(data, self._target)
                return True
            except BlockingIOError:
                if attempt < max_retries - 1:
                    time.sleep(0.001)
                    continue
                return False
            except OSError as e:
                logger.error(f"UDP send error: {e}")
                return False

        return False

    def _save_to_history(self, utterance: Utterance) -> None:
        """Save utterance info to debug history.

        Args:
            utterance: The utterance to save.
        """
        info = {
            "id": utterance.utterance_id,
            "chunks": utterance.chunk_count,
            "bytes": utterance.audio_bytes,
            "duration_ms": utterance.audio_duration_ms,
            "sample_rate": utterance.sample_rate,
            "channels": utterance.num_channels,
            "buffer_time_ms": (utterance.completed_at - utterance.created_at) * 1000,
            "timestamp": time.strftime("%H:%M:%S"),
        }

        self._utterance_history.append(info)

        # Keep only last N
        if len(self._utterance_history) > self._max_history:
            self._utterance_history.pop(0)

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive streaming statistics.

        Returns:
            Dictionary with all stats and recent utterance history.
        """
        return {
            "total": {
                "utterances_completed": self._total_utterances_completed,
                "packets_sent": self._total_packets_sent,
                "packets_dropped": self._total_packets_dropped,
                "bytes_sent": self._total_bytes_sent,
                "kb_sent": self._total_bytes_sent / 1024,
            },
            "current": {
                "queue_size": len(self._utterance_queue),
                "is_playing": self._is_playing,
                "pending_utterances": [
                    {
                        "id": u.utterance_id,
                        "bytes": u.audio_bytes,
                        "duration_ms": u.audio_duration_ms,
                        "complete": u.is_complete,
                    }
                    for u in self._utterance_queue
                ],
            },
            "history": self._utterance_history,
        }

    def print_stats(self) -> None:
        """Print formatted statistics to logger."""
        stats = self.get_stats()

        logger.info("=" * 60)
        logger.info("  UnrealAudioStreamer Statistics")
        logger.info("=" * 60)
        logger.info(f"  Utterances completed: {stats['total']['utterances_completed']}")
        logger.info(f"  Packets sent: {stats['total']['packets_sent']}")
        logger.info(f"  Packets dropped: {stats['total']['packets_dropped']}")
        logger.info(f"  Total bytes: {stats['total']['bytes_sent']} ({stats['total']['kb_sent']:.1f} KB)")
        logger.info(f"  Queue size: {stats['current']['queue_size']}")
        logger.info(f"  Is playing: {stats['current']['is_playing']}")

        if stats['history']:
            logger.info("-" * 60)
            logger.info("  Recent Utterances:")
            for h in stats['history'][-5:]:
                logger.info(
                    f"    #{h['id']}: {h['chunks']} chunks, "
                    f"{h['bytes']} bytes, {h['duration_ms']:.0f}ms, "
                    f"buffered in {h['buffer_time_ms']:.0f}ms"
                )
        logger.info("=" * 60)

    @property
    def is_streaming(self) -> bool:
        """Check if the streamer is active.

        Returns:
            True if socket is initialized, False otherwise.
        """
        return self._socket is not None
