#!/usr/bin/env python3
"""Run Avatar pipeline with Unreal Engine integration.

This script sends:
- UDP audio to Audio2Face at 192.168.1.14:8080
- WebSocket control messages to localhost:8765

Usage:
    python examples/run_with_unreal.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from avatar.config.settings import Settings
from avatar.pipeline.main_pipeline import AvatarPipeline


def main():
    """Run Avatar with Unreal Engine integration."""
    # Load environment
    load_dotenv()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("with_unreal")

    logger.info("=" * 60)
    logger.info("  Avatar - Unreal Engine Mode")
    logger.info("  (UDP Audio + WebSocket Control)")
    logger.info("=" * 60)

    # Create settings with Unreal enabled, NDI disabled
    settings = Settings(
        enable_unreal=True,
        enable_ndi=False,
        # Unreal endpoints - both on 192.168.1.14
        unreal_websocket_uri="ws://192.168.1.14:9765",
        unreal_audio_udp_host="192.168.1.14",
        unreal_audio_udp_port=8080,
    )

    # Validate required settings
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is required")
        sys.exit(1)
    if not settings.elevenlabs_api_key:
        logger.error("ELEVENLABS_API_KEY is required")
        sys.exit(1)
    if not settings.elevenlabs_voice_id:
        logger.error("ELEVENLABS_VOICE_ID is required")
        sys.exit(1)
    if not settings.daily_room_url:
        logger.error("DAILY_ROOM_URL is required")
        sys.exit(1)

    logger.info(f"UDP Audio → {settings.unreal_audio_udp_host}:{settings.unreal_audio_udp_port}")
    logger.info(f"WebSocket → {settings.unreal_websocket_uri}")

    # Create and run pipeline
    avatar = AvatarPipeline(settings=settings)

    try:
        asyncio.run(avatar.run())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        raise


if __name__ == "__main__":
    main()
