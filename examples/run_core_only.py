#!/usr/bin/env python3
"""Run Avatar pipeline in core-only mode (no Unreal, no NDI).

This script tests the core Pipecat functionality:
- Daily WebRTC transport
- OpenAI STT
- OpenAI LLM
- ElevenLabs TTS

The TTS audio is sent directly to the Daily room without any
Unreal Engine integration (no WebSocket, no UDP audio, no NDI).

Usage:
    python examples/run_core_only.py

Make sure your .env has the correct API keys and Daily room URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from avatar.config.settings import Settings
from avatar.pipeline.main_pipeline import AvatarPipeline


def main():
    """Run Avatar in core-only mode."""
    # Load environment
    load_dotenv()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("core_only")

    logger.info("=" * 60)
    logger.info("  Avatar - Core Only Mode")
    logger.info("  (No Unreal Engine, No NDI)")
    logger.info("=" * 60)

    # Create settings with Unreal/NDI disabled
    settings = Settings(
        enable_unreal=False,
        enable_ndi=False,
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
