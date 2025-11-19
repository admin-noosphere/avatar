#!/usr/bin/env python3
"""Mock Unreal Engine server for testing Avatar pipeline.

This script simulates both:
1. WebSocket server (port 8765) - receives control commands
2. UDP server (port 8080) - receives audio data

Usage:
    python claude_dev/mock_unreal_server.py

Options:
    --ws-port PORT      WebSocket port (default: 8765)
    --udp-port PORT     UDP port (default: 8080)
    --log-level LEVEL   Logging level (default: INFO)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
from datetime import datetime
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class MockUnrealServer:
    """Combined WebSocket and UDP mock server for Unreal Engine simulation."""

    def __init__(
        self,
        ws_host: str = "localhost",
        ws_port: int = 8765,
        udp_host: str = "0.0.0.0",
        udp_port: int = 8080,
    ) -> None:
        """Initialize the mock server.

        Args:
            ws_host: WebSocket server host.
            ws_port: WebSocket server port.
            udp_host: UDP server host.
            udp_port: UDP server port.
        """
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.udp_host = udp_host
        self.udp_port = udp_port

        # Statistics
        self.ws_messages_received = 0
        self.udp_packets_received = 0
        self.udp_bytes_received = 0
        self.connected_clients: set[WebSocketServerProtocol] = set()

        # State tracking
        self.is_speaking = False
        self.current_emotion = "neutral"
        self.last_command_time: datetime | None = None

    async def handle_websocket(
        self, websocket: WebSocketServerProtocol
    ) -> None:
        """Handle WebSocket client connection.

        Args:
            websocket: The WebSocket connection.
        """
        self.connected_clients.add(websocket)
        client_addr = websocket.remote_address
        logger.info(f"🔌 WebSocket client connected: {client_addr}")

        # Send initial ready message
        await websocket.send(
            json.dumps({"type": "status", "message": "MetaHuman Ready"})
        )

        try:
            async for message in websocket:
                await self.process_websocket_message(websocket, message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"🔌 Client disconnected: {client_addr} ({e.code})")
        finally:
            self.connected_clients.discard(websocket)

    async def process_websocket_message(
        self, websocket: WebSocketServerProtocol, message: str
    ) -> None:
        """Process incoming WebSocket message.

        Args:
            websocket: The WebSocket connection.
            message: The received message.
        """
        self.ws_messages_received += 1
        self.last_command_time = datetime.now()

        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")

            if msg_type == "start_speaking":
                self.is_speaking = True
                category = data.get("category", "SPEAKING_NEUTRAL")
                logger.info(f"🎤 START SPEAKING - Category: {category}")
                await websocket.send(
                    json.dumps({"type": "ack", "status": "speaking_started"})
                )

            elif msg_type == "stop_speaking":
                self.is_speaking = False
                logger.info("🔇 STOP SPEAKING")
                await websocket.send(
                    json.dumps({"type": "ack", "status": "speaking_stopped"})
                )

            elif msg_type == "contextual_animation":
                emotion = data.get("emotion", "neutral")
                intensity = data.get("intensity", 0.5)
                self.current_emotion = emotion
                logger.info(
                    f"😊 ANIMATION - Emotion: {emotion}, Intensity: {intensity:.2f}"
                )
                await websocket.send(
                    json.dumps({
                        "type": "ack",
                        "status": "animation_triggered",
                        "emotion": emotion,
                    })
                )

            else:
                logger.warning(f"⚠️  Unknown message type: {msg_type}")
                logger.debug(f"    Full message: {data}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON: {e}")
            logger.debug(f"    Raw message: {message}")

    async def run_udp_server(self) -> None:
        """Run UDP server for audio data reception."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.bind((self.udp_host, self.udp_port))

        logger.info(f"📡 UDP server listening on {self.udp_host}:{self.udp_port}")

        loop = asyncio.get_event_loop()
        last_stats_time = datetime.now()

        while True:
            try:
                data, addr = await loop.run_in_executor(
                    None, lambda: sock.recvfrom(65536)
                )

                self.udp_packets_received += 1
                self.udp_bytes_received += len(data)

                # Log stats periodically (every 5 seconds)
                now = datetime.now()
                if (now - last_stats_time).seconds >= 5:
                    self._log_udp_stats()
                    last_stats_time = now

            except BlockingIOError:
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"UDP error: {e}")
                await asyncio.sleep(0.1)

    def _log_udp_stats(self) -> None:
        """Log UDP streaming statistics."""
        kb_received = self.udp_bytes_received / 1024
        logger.info(
            f"📊 UDP Stats: {self.udp_packets_received} packets, "
            f"{kb_received:.1f} KB total"
        )

    async def run_websocket_server(self) -> None:
        """Run WebSocket server for control commands."""
        logger.info(
            f"🌐 WebSocket server listening on ws://{self.ws_host}:{self.ws_port}"
        )

        async with websockets.serve(
            self.handle_websocket,
            self.ws_host,
            self.ws_port,
            ping_interval=20,
            ping_timeout=10,
        ):
            await asyncio.Future()  # Run forever

    async def run(self) -> None:
        """Run both servers concurrently."""
        logger.info("=" * 60)
        logger.info("  Mock Unreal Engine Server")
        logger.info("=" * 60)
        logger.info("")

        await asyncio.gather(
            self.run_websocket_server(),
            self.run_udp_server(),
        )

    def print_status(self) -> None:
        """Print current server status."""
        logger.info("")
        logger.info("Current Status:")
        logger.info(f"  - Connected clients: {len(self.connected_clients)}")
        logger.info(f"  - Is speaking: {self.is_speaking}")
        logger.info(f"  - Current emotion: {self.current_emotion}")
        logger.info(f"  - WS messages: {self.ws_messages_received}")
        logger.info(f"  - UDP packets: {self.udp_packets_received}")
        logger.info(f"  - UDP bytes: {self.udp_bytes_received / 1024:.1f} KB")
        logger.info("")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Mock Unreal Engine server for Avatar pipeline testing"
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=8765,
        help="WebSocket server port (default: 8765)",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=8080,
        help="UDP server port (default: 8080)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    server = MockUnrealServer(
        ws_port=args.ws_port,
        udp_port=args.udp_port,
    )

    try:
        await server.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 Server shutting down...")
        server.print_status()


if __name__ == "__main__":
    asyncio.run(main())
