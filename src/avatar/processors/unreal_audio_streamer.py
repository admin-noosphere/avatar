"""UnrealAudioStreamer - UDP audio streaming with sequential utterance queue.

This processor streams audio chunks immediately as they arrive from TTS,
managing multiple utterances in a queue for sequential playback.

Flow:
1. TTSStartedFrame → Create utterance, add to queue. If first → send start events
2. OutputAudioRawFrame → Stream immediately via UDP to receiving utterance
3. TTSStoppedFrame → Mark complete, schedule stop events after duration
4. After duration → Send stop events, start next utterance if any

This ensures low latency while properly sequencing multiple phrases.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

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
    """Tracks an utterance being streamed."""
    utterance_id: int
    sample_rate: int = DEFAULT_SAMPLE_RATE
    num_channels: int = DEFAULT_CHANNELS
    total_bytes: int = 0
    chunk_count: int = 0
    is_complete: bool = False  # True when TTSStoppedFrame received
    started_at: float = field(default_factory=time.monotonic)
    direction: FrameDirection = FrameDirection.DOWNSTREAM

    @property
    def audio_duration_ms(self) -> float:
        """Calculate audio duration in milliseconds from total bytes."""
        if not self.total_bytes:
            return 0.0
        bytes_per_sample = BYTES_PER_SAMPLE * self.num_channels
        samples = self.total_bytes / bytes_per_sample
        return (samples / self.sample_rate) * 1000


class UnrealAudioStreamer(FrameProcessor):
    """Processor that streams TTS audio immediately via UDP with queue management.

    Key behavior:
    - Streams audio chunks immediately as they arrive (low latency)
    - Manages queue of utterances for sequential playback
    - Sends start/stop events at correct times for Audio2Face sync
    """

    def __init__(
        self,
        host: str = "192.168.1.14",
        port: int = 8080,
        websocket_uri: str = "ws://192.168.1.14:8765",
        **kwargs: Any,
    ) -> None:
        """Initialize the UnrealAudioStreamer.

        Args:
            host: UDP target host for Audio2Face.
            port: UDP target port for Audio2Face.
            websocket_uri: WebSocket URI for Unreal Engine events.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self.host = host
        self.port = port
        self.websocket_uri = websocket_uri
        self._target = (host, port)

        self._socket: socket.socket | None = None

        # WebSocket for Unreal events
        self._websocket: websockets.WebSocketClientProtocol | None = None
        self._ws_connection_task: asyncio.Task[None] | None = None
        self._ws_running = False

        # Statistics
        self._total_bytes_sent = 0
        self._total_packets_sent = 0
        self._total_packets_dropped = 0
        self._total_utterances = 0

        # Utterance queue management
        self._utterance_counter: int = 0
        self._utterance_queue: list[Utterance] = []

        # Task to send stop events after audio duration
        self._stop_events_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the processor, create UDP socket, and connect WebSocket."""
        # UDP socket
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
        self._total_utterances = 0
        self._utterance_counter = 0
        self._utterance_queue = []

        # Start WebSocket connection
        self._ws_running = True
        self._ws_connection_task = asyncio.create_task(self._maintain_ws_connection())

        logger.info(f"🎙️ UnrealAudioStreamer started → UDP {self.host}:{self.port}, WS {self.websocket_uri}")

    async def stop(self) -> None:
        """Stop the processor and close connections."""
        # Cancel stop events task
        if self._stop_events_task:
            self._stop_events_task.cancel()
            try:
                await self._stop_events_task
            except asyncio.CancelledError:
                pass
            self._stop_events_task = None

        # Stop WebSocket
        self._ws_running = False
        if self._ws_connection_task:
            self._ws_connection_task.cancel()
            try:
                await self._ws_connection_task
            except asyncio.CancelledError:
                pass
            self._ws_connection_task = None

        if self._websocket:
            await self._websocket.close()
            self._websocket = None

        # Close UDP socket
        if self._socket:
            self._socket.close()
            self._socket = None

        logger.info(
            f"🎙️ UnrealAudioStreamer stopped | "
            f"Utterances: {self._total_utterances} | "
            f"Packets: {self._total_packets_sent} | "
            f"Dropped: {self._total_packets_dropped} | "
            f"Total: {self._total_bytes_sent / 1024:.1f} KB"
        )

    async def _maintain_ws_connection(self) -> None:
        """Maintain persistent WebSocket connection with exponential backoff."""
        reconnect_delay = 1.0
        max_delay = 30.0

        while self._ws_running:
            try:
                async with websockets.connect(
                    self.websocket_uri,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._websocket = ws
                    reconnect_delay = 1.0  # Reset backoff
                    logger.info(f"✅ WebSocket connected to {self.websocket_uri}")

                    # Wait until connection closes
                    await ws.wait_closed()
                    logger.warning("WebSocket connection closed")

            except ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e.code} - {e.reason}")
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except OSError as e:
                logger.error(f"WebSocket connection failed: {e}")
            except asyncio.CancelledError:
                break
            finally:
                self._websocket = None

            if self._ws_running:
                logger.info(f"WebSocket reconnecting in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    async def _send_ws_command(self, data: dict[str, Any]) -> bool:
        """Send a JSON command to Unreal Engine via WebSocket.

        Args:
            data: Dictionary to serialize and send as JSON.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._websocket:
            logger.warning(f"⏳ WebSocket not connected, cannot send: {data.get('type')}")
            return False

        try:
            message = json.dumps(data)
            await self._websocket.send(message)
            logger.info(f"📤 WS → Unreal: {message}")
            return True
        except ConnectionClosed:
            logger.warning("Cannot send: WebSocket connection closed")
            self._websocket = None
            return False
        except WebSocketException as e:
            logger.error(f"Failed to send WebSocket command: {e}")
            return False

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
        # 1. TTSStartedFrame → Create utterance, add to queue
        # ═══════════════════════════════════════════════════════════════
        if isinstance(frame, TTSStartedFrame):
            self._utterance_counter += 1
            utterance = Utterance(
                utterance_id=self._utterance_counter,
                direction=direction,
            )

            # Add to queue
            self._utterance_queue.append(utterance)

            is_first = len(self._utterance_queue) == 1

            logger.info(
                f"📝 Utterance #{utterance.utterance_id} created | "
                f"Queue size: {len(self._utterance_queue)} | "
                f"First: {is_first}"
            )

            # If this is the first utterance, send start events
            if is_first:
                await self._send_ws_command({
                    "type": "start_speaking",
                    "category": "SPEAKING_NEUTRAL",
                    "timestamp": time.time(),
                })
                await self._send_ws_command({
                    "type": "start_audio_stream",
                    "timestamp": time.time(),
                })

            # Forward the frame
            await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 2. OutputAudioRawFrame → Stream immediately via UDP
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, OutputAudioRawFrame):
            audio_data = frame.audio
            audio_len = len(audio_data)

            # Find the utterance still receiving (last incomplete one)
            receiving_utterance = None
            for utt in reversed(self._utterance_queue):
                if not utt.is_complete:
                    receiving_utterance = utt
                    break

            if receiving_utterance:
                # Update sample rate/channels from first chunk
                if receiving_utterance.chunk_count == 0:
                    receiving_utterance.sample_rate = frame.sample_rate or DEFAULT_SAMPLE_RATE
                    receiving_utterance.num_channels = frame.num_channels or DEFAULT_CHANNELS

                # Track total bytes for duration calculation
                receiving_utterance.total_bytes += audio_len
                receiving_utterance.chunk_count += 1

                # Stream immediately via UDP
                packets_sent = 0
                for i in range(0, audio_len, UDP_MAX_PACKET_SIZE):
                    chunk = audio_data[i:i + UDP_MAX_PACKET_SIZE]
                    if self._send_udp_packet(chunk):
                        packets_sent += 1
                        self._total_packets_sent += 1
                        self._total_bytes_sent += len(chunk)
                    else:
                        self._total_packets_dropped += 1

                logger.debug(
                    f"🔊 Utt#{receiving_utterance.utterance_id} chunk #{receiving_utterance.chunk_count}: "
                    f"{audio_len} bytes → {packets_sent} UDP | "
                    f"Total: {receiving_utterance.total_bytes} bytes "
                    f"({receiving_utterance.audio_duration_ms:.0f}ms)"
                )
            else:
                logger.warning(f"⚠️ Audio chunk received but no receiving utterance! ({audio_len} bytes dropped)")

        # ═══════════════════════════════════════════════════════════════
        # 3. TTSStoppedFrame → Mark complete, schedule stop events
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, TTSStoppedFrame):
            # Find the first incomplete utterance
            target = None
            for utt in self._utterance_queue:
                if not utt.is_complete:
                    target = utt
                    break

            if target:
                target.is_complete = True

                # Calculate timing
                elapsed_ms = (time.monotonic() - target.started_at) * 1000
                remaining_ms = target.audio_duration_ms - elapsed_ms

                logger.info(
                    f"✅ Utterance #{target.utterance_id} complete | "
                    f"Chunks: {target.chunk_count} | "
                    f"Size: {target.total_bytes} bytes | "
                    f"Duration: {target.audio_duration_ms:.0f}ms | "
                    f"Remaining: {max(0, remaining_ms):.0f}ms | "
                    f"Queue: {len(self._utterance_queue)}"
                )

                self._total_utterances += 1

                # Check if this is the first in queue (currently playing)
                if self._utterance_queue and self._utterance_queue[0] == target:
                    # Cancel any existing stop task
                    if self._stop_events_task:
                        self._stop_events_task.cancel()

                    # Schedule stop events after remaining duration
                    self._stop_events_task = asyncio.create_task(
                        self._finish_utterance(target, max(0, remaining_ms))
                    )
            else:
                logger.warning("⚠️ TTSStoppedFrame but no incomplete utterance")
                await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 4. Interruption → Cancel everything and stop immediately
        # ═══════════════════════════════════════════════════════════════
        elif isinstance(frame, (InterruptionFrame, CancelFrame)):
            queue_size = len(self._utterance_queue)
            logger.info(f"🛑 INTERRUPTION | Queue size: {queue_size}")

            # Cancel pending stop events
            if self._stop_events_task:
                self._stop_events_task.cancel()
                self._stop_events_task = None

            # Clear queue
            self._utterance_queue = []

            # Send stop events immediately
            await self._send_ws_command({
                "type": "end_audio_stream",
                "timestamp": time.time(),
            })
            await self._send_ws_command({
                "type": "stop_speaking",
                "timestamp": time.time(),
            })
            logger.info("✅ Interruption: stop events sent, queue cleared")

            # Forward interruption downstream
            await self.push_frame(frame, direction)

        # ═══════════════════════════════════════════════════════════════
        # 5. Other frames → Pass through
        # ═══════════════════════════════════════════════════════════════
        else:
            frame_name = type(frame).__name__
            if "Interrupt" in frame_name or "Cancel" in frame_name or "Stop" in frame_name:
                logger.info(f"🔍 Frame passthrough: {frame_name}")
            await self.push_frame(frame, direction)

    async def _finish_utterance(self, utterance: Utterance, delay_ms: float) -> None:
        """Finish an utterance: wait for audio, send stop events, start next.

        Args:
            utterance: The utterance that finished receiving.
            delay_ms: Milliseconds to wait for audio to finish playing.
        """
        try:
            # Wait for audio to finish playing
            if delay_ms > 0:
                logger.debug(f"⏳ Waiting {delay_ms:.0f}ms for utterance #{utterance.utterance_id} to finish...")
                await asyncio.sleep(delay_ms / 1000)

            # Remove from queue
            if self._utterance_queue and self._utterance_queue[0] == utterance:
                self._utterance_queue.pop(0)

            # Check if there's a next utterance
            has_next = len(self._utterance_queue) > 0
            next_id = self._utterance_queue[0].utterance_id if has_next else None

            # Send stop events
            await self._send_ws_command({
                "type": "end_audio_stream",
                "timestamp": time.time(),
            })
            await self._send_ws_command({
                "type": "stop_speaking",
                "timestamp": time.time(),
            })

            logger.info(
                f"⏹️ Utterance #{utterance.utterance_id} done | "
                f"Next: {next_id if has_next else 'None'} | "
                f"Queue: {len(self._utterance_queue)}"
            )

            # Forward TTSStoppedFrame
            await self.push_frame(TTSStoppedFrame(), utterance.direction)

            # If there's a next utterance, send start events for it
            if has_next:
                next_utt = self._utterance_queue[0]

                await self._send_ws_command({
                    "type": "start_speaking",
                    "category": "SPEAKING_NEUTRAL",
                    "timestamp": time.time(),
                })
                await self._send_ws_command({
                    "type": "start_audio_stream",
                    "timestamp": time.time(),
                })

                logger.info(f"▶️ Starting next utterance #{next_utt.utterance_id}")

                # If next utterance is already complete, schedule its finish
                if next_utt.is_complete:
                    elapsed_ms = (time.monotonic() - next_utt.started_at) * 1000
                    remaining_ms = next_utt.audio_duration_ms - elapsed_ms
                    self._stop_events_task = asyncio.create_task(
                        self._finish_utterance(next_utt, max(0, remaining_ms))
                    )

        except asyncio.CancelledError:
            logger.debug(f"⏹️ Finish cancelled for utterance #{utterance.utterance_id}")
            raise

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

    def get_stats(self) -> dict[str, Any]:
        """Get streaming statistics.

        Returns:
            Dictionary with stats.
        """
        return {
            "total_utterances": self._total_utterances,
            "total_packets_sent": self._total_packets_sent,
            "total_packets_dropped": self._total_packets_dropped,
            "total_bytes_sent": self._total_bytes_sent,
            "total_kb_sent": self._total_bytes_sent / 1024,
            "queue_size": len(self._utterance_queue),
            "queue": [
                {
                    "id": u.utterance_id,
                    "bytes": u.total_bytes,
                    "duration_ms": u.audio_duration_ms,
                    "complete": u.is_complete,
                }
                for u in self._utterance_queue
            ],
        }

    @property
    def is_streaming(self) -> bool:
        """Check if the streamer is active.

        Returns:
            True if socket is initialized, False otherwise.
        """
        return self._socket is not None
