"""UnrealEventProcessor - WebSocket control for Unreal Engine MetaHuman.

This processor listens for TTS events (TTSStartedFrame, TTSStoppedFrame) and
interruption signals, then sends corresponding WebSocket commands to Unreal Engine
to control MetaHuman animation states.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from pipecat.frames.frames import (
    Frame,
    StartInterruptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class UnrealEventProcessor(FrameProcessor):
    """Processor that sends WebSocket events to Unreal Engine for MetaHuman control.

    This processor monitors the pipeline for TTS lifecycle events and user
    interruptions, translating them into WebSocket JSON commands that control
    the MetaHuman's speaking animation state.

    Attributes:
        uri: WebSocket URI for Unreal Engine connection.
        reconnect_delay: Initial delay between reconnection attempts.
        max_reconnect_delay: Maximum delay between reconnection attempts.
    """

    def __init__(
        self,
        uri: str = "ws://localhost:8765",
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        **kwargs: Any,
    ) -> None:
        """Initialize the UnrealEventProcessor.

        Args:
            uri: WebSocket URI for Unreal Engine connection.
            reconnect_delay: Initial delay between reconnection attempts.
            max_reconnect_delay: Maximum delay for exponential backoff.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self.uri = uri
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._websocket: websockets.WebSocketClientProtocol | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._running = False
        self._current_delay = reconnect_delay

        # Queue for commands when WebSocket not connected
        self._command_queue: list[dict[str, Any]] = []

    async def start(self) -> None:
        """Start the processor and initiate WebSocket connection."""
        self._running = True
        self._connection_task = asyncio.create_task(self._maintain_connection())
        logger.info(f"🔌 UnrealEventProcessor started, connecting to {self.uri}")

    async def stop(self) -> None:
        """Stop the processor and close WebSocket connection."""
        self._running = False

        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
            self._connection_task = None

        if self._websocket:
            await self._websocket.close()
            self._websocket = None

        logger.info("UnrealEventProcessor stopped")

    async def _maintain_connection(self) -> None:
        """Maintain persistent WebSocket connection with exponential backoff."""
        while self._running:
            try:
                async with websockets.connect(
                    self.uri,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._websocket = ws
                    self._current_delay = self.reconnect_delay  # Reset backoff
                    logger.info(f"✅ Connected to Unreal Engine at {self.uri}")

                    # Send any queued commands
                    if self._command_queue:
                        logger.info(f"📤 Sending {len(self._command_queue)} queued commands...")
                        for cmd in self._command_queue:
                            await self._send_command(cmd)
                        self._command_queue.clear()

                    # Wait until connection closes
                    await ws.wait_closed()
                    logger.warning("WebSocket connection closed")

            except ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e.code} - {e.reason}")
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except OSError as e:
                logger.error(f"Connection failed: {e}")
            except asyncio.CancelledError:
                break
            finally:
                self._websocket = None

            if self._running:
                logger.info(f"Reconnecting in {self._current_delay:.1f}s...")
                await asyncio.sleep(self._current_delay)
                # Exponential backoff
                self._current_delay = min(
                    self._current_delay * 2, self.max_reconnect_delay
                )

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        """Process incoming frames and send WebSocket events.

        Args:
            frame: The frame to process.
            direction: The direction of frame flow (upstream/downstream).
        """
        await super().process_frame(frame, direction)

        # Log all frames for debugging
        frame_type = type(frame).__name__
        if frame_type in ['TTSStartedFrame', 'TTSStoppedFrame', 'OutputAudioRawFrame']:
            logger.info(f"UnrealEventProcessor received: {frame_type}")

        # Handle TTS Started - Avatar starts speaking
        if isinstance(frame, TTSStartedFrame):
            # Send start_speaking with category and timestamp
            sent = await self._send_command({
                "type": "start_speaking",
                "category": "SPEAKING_NEUTRAL",
                "timestamp": time.time(),
            })
            if sent:
                logger.info("✅ start_speaking sent")
            else:
                logger.info("⏳ start_speaking queued (will send when connected)")

            # Send start_audio_stream
            sent = await self._send_command({
                "type": "start_audio_stream",
                "timestamp": time.time(),
            })
            if sent:
                logger.info("✅ start_audio_stream sent")

        # Handle TTS Stopped - Avatar stops speaking
        elif isinstance(frame, TTSStoppedFrame):
            # Send end_audio_stream
            sent = await self._send_command({
                "type": "end_audio_stream",
                "timestamp": time.time(),
            })
            if sent:
                logger.info("✅ end_audio_stream sent")

            # Send stop_speaking
            sent = await self._send_command({
                "type": "stop_speaking",
                "timestamp": time.time(),
            })
            if sent:
                logger.info("✅ stop_speaking sent")

        # Handle User Interruption (barge-in) - Immediately stop avatar
        elif isinstance(frame, StartInterruptionFrame):
            await self._send_command({
                "type": "end_audio_stream",
                "timestamp": time.time(),
            })
            await self._send_command({
                "type": "stop_speaking",
                "timestamp": time.time(),
            })
            logger.info("Sent stop commands (interruption)")

        # Forward frame downstream
        await self.push_frame(frame, direction)

    async def _send_command(self, data: dict[str, Any], queue_if_disconnected: bool = True) -> bool:
        """Send a JSON command to Unreal Engine via WebSocket.

        Args:
            data: Dictionary to serialize and send as JSON.
            queue_if_disconnected: If True, queue command when not connected.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._websocket:
            if queue_if_disconnected:
                self._command_queue.append(data)
                logger.warning(f"⏳ WebSocket not connected, queued command: {data.get('type')}")
            else:
                logger.warning(f"Cannot send command: WebSocket not connected (trying to send: {data.get('type')})")
            return False

        try:
            message = json.dumps(data)
            await self._websocket.send(message)
            logger.info(f"✅ Sent to Unreal: {message}")
            return True
        except ConnectionClosed:
            logger.warning("Cannot send: connection closed")
            self._websocket = None
            if queue_if_disconnected:
                self._command_queue.append(data)
            return False
        except WebSocketException as e:
            logger.error(f"Failed to send command: {e}")
            return False

    async def send_contextual_animation(
        self,
        emotion: str,
        intensity: float = 0.5,
    ) -> None:
        """Send a contextual animation command to control avatar emotion.

        This method can be called externally (e.g., from LLM function calling)
        to trigger specific emotional animations on the MetaHuman.

        Args:
            emotion: Emotion name (neutral, happy, sad, angry, surprised).
            intensity: Animation intensity from 0.0 to 1.0.
        """
        await self._send_command({
            "type": "contextual_animation",
            "emotion": emotion,
            "intensity": max(0.0, min(1.0, intensity)),
        })
        logger.info(f"Sent contextual animation: {emotion} @ {intensity:.2f}")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected.

        Returns:
            True if connected, False otherwise.
        """
        return self._websocket is not None and self._websocket.open
