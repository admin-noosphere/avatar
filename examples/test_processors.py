#!/usr/bin/env python3
"""Test script for Avatar processors without Daily transport.

This script tests the UnrealEventProcessor and UnrealAudioStreamer
with the mock Unreal server to validate communication.

Usage:
    1. Start mock server: python claude_dev/mock_unreal_server.py
    2. Run this test: python examples/test_processors.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipecat.frames.frames import (
    OutputAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def test_websocket_events():
    """Test WebSocket event sending."""
    logger.info("=" * 60)
    logger.info("  Testing UnrealEventProcessor (WebSocket)")
    logger.info("=" * 60)

    processor = UnrealEventProcessor(
        uri="ws://localhost:8765",
        reconnect_delay=1.0,
    )

    # Mock push_frame to capture forwarded frames
    forwarded_frames = []

    async def mock_push(frame, direction):
        forwarded_frames.append(frame)

    processor.push_frame = mock_push

    try:
        # Start processor
        await processor.start()
        logger.info("Processor started")

        # Wait for connection
        await asyncio.sleep(1.0)

        if not processor.is_connected:
            logger.error("Failed to connect to WebSocket server")
            logger.error("Make sure mock server is running: python claude_dev/mock_unreal_server.py")
            return False

        logger.info("Connected to WebSocket server")

        # Test TTSStartedFrame
        logger.info("Sending TTSStartedFrame...")
        await processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.5)

        # Test contextual animation
        logger.info("Sending contextual animation (happy)...")
        await processor.send_contextual_animation("happy", 0.8)
        await asyncio.sleep(0.5)

        # Test TTSStoppedFrame
        logger.info("Sending TTSStoppedFrame...")
        await processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.5)

        logger.info(f"Frames forwarded: {len(forwarded_frames)}")
        logger.info("WebSocket test PASSED")
        return True

    except Exception as e:
        logger.error(f"WebSocket test FAILED: {e}")
        return False

    finally:
        await processor.stop()
        logger.info("Processor stopped")


async def test_udp_audio():
    """Test UDP audio streaming."""
    logger.info("=" * 60)
    logger.info("  Testing UnrealAudioStreamer (UDP)")
    logger.info("=" * 60)

    processor = UnrealAudioStreamer(
        host="127.0.0.1",
        port=8080,
    )

    # Mock push_frame
    async def mock_push(frame, direction):
        pass

    processor.push_frame = mock_push

    try:
        # Start processor
        await processor.start()
        logger.info("Processor started")

        # Generate test audio (1 second of silence)
        sample_rate = 24000
        duration = 1.0
        num_samples = int(sample_rate * duration)

        # Create test audio (sine wave for audible feedback)
        import math
        audio_data = bytearray()
        for i in range(num_samples):
            # 440 Hz sine wave
            sample = int(32767 * 0.5 * math.sin(2 * math.pi * 440 * i / sample_rate))
            audio_data.extend(sample.to_bytes(2, byteorder='little', signed=True))

        # Send audio in chunks
        chunk_size = 960  # 40ms at 24kHz
        num_chunks = len(audio_data) // (chunk_size * 2)

        logger.info(f"Sending {num_chunks} audio chunks...")

        for i in range(0, len(audio_data), chunk_size * 2):
            chunk = bytes(audio_data[i:i + chunk_size * 2])
            frame = OutputAudioRawFrame(
                audio=chunk,
                sample_rate=sample_rate,
                num_channels=1,
            )
            await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.01)  # Simulate real-time

        # Get stats
        stats = processor.get_stats()
        logger.info(f"Stats: {stats}")

        if stats["packets_sent"] > 0:
            logger.info("UDP test PASSED")
            return True
        else:
            logger.error("No packets sent")
            return False

    except Exception as e:
        logger.error(f"UDP test FAILED: {e}")
        return False

    finally:
        await processor.stop()
        logger.info("Processor stopped")


async def test_combined():
    """Test both processors together simulating a TTS event."""
    logger.info("=" * 60)
    logger.info("  Testing Combined (WebSocket + UDP)")
    logger.info("=" * 60)

    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    # Mock push_frame for both
    async def mock_push(frame, direction):
        pass

    event_processor.push_frame = mock_push
    audio_processor.push_frame = mock_push

    try:
        # Start both
        await event_processor.start()
        await audio_processor.start()
        await asyncio.sleep(1.0)

        if not event_processor.is_connected:
            logger.error("WebSocket not connected")
            return False

        # Simulate TTS flow
        logger.info("Simulating TTS Started...")
        await event_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        # Send some audio
        logger.info("Sending audio chunks...")
        sample_rate = 24000
        chunk_size = 960

        for i in range(25):  # ~500ms of audio
            # Silence for test
            chunk = b'\x00' * (chunk_size * 2)
            frame = OutputAudioRawFrame(
                audio=chunk,
                sample_rate=sample_rate,
                num_channels=1,
            )
            await audio_processor.process_frame(frame, FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.02)

        logger.info("Simulating TTS Stopped...")
        await event_processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)

        await asyncio.sleep(0.5)

        stats = audio_processor.get_stats()
        logger.info(f"Audio stats: {stats}")
        logger.info("Combined test PASSED")
        return True

    except Exception as e:
        logger.error(f"Combined test FAILED: {e}")
        return False

    finally:
        await event_processor.stop()
        await audio_processor.stop()


async def main():
    """Run all tests."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  Avatar Processors Test Suite")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Make sure mock server is running:")
    logger.info("  python claude_dev/mock_unreal_server.py")
    logger.info("")

    results = []

    # Test 1: WebSocket
    result = await test_websocket_events()
    results.append(("WebSocket Events", result))

    await asyncio.sleep(1.0)

    # Test 2: UDP
    result = await test_udp_audio()
    results.append(("UDP Audio", result))

    await asyncio.sleep(1.0)

    # Test 3: Combined
    result = await test_combined()
    results.append(("Combined Flow", result))

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("  Test Results Summary")
    logger.info("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        icon = "✅" if passed else "❌"
        logger.info(f"  {icon} {name}: {status}")
        if not passed:
            all_passed = False

    logger.info("=" * 60)

    if all_passed:
        logger.info("All tests PASSED!")
        return 0
    else:
        logger.error("Some tests FAILED!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
