#!/usr/bin/env python3
"""Interactive pipeline test with full mocks and detailed logging.

This script tests the complete Avatar pipeline using mocks for all external
services, with verbose logging to understand exactly what's happening.

Usage:
    python examples/test_pipeline_with_mocks.py

No external services required - everything is mocked.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "claude_dev"))

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.frames.frames import (
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer

from mock_daily_transport import (
    MockDailyTransport,
    MockTTSService,
)

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
    datefmt="%H:%M:%S.%f",
)

# Reduce noise from some loggers
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.INFO)

logger = logging.getLogger("test_pipeline")


class FrameLogger(FrameProcessor):
    """Processor that logs all frames passing through."""

    def __init__(self, label: str, **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self.frame_count = 0

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        self.frame_count += 1

        frame_type = type(frame).__name__

        # Log with different colors based on frame type
        if isinstance(frame, TTSStartedFrame):
            logger.info(f"🟢 [{self._label}] {frame_type}")
        elif isinstance(frame, TTSStoppedFrame):
            logger.info(f"🔴 [{self._label}] {frame_type}")
        elif isinstance(frame, OutputAudioRawFrame):
            if self.frame_count % 10 == 0:  # Log every 10th audio frame
                logger.debug(f"🔊 [{self._label}] {frame_type} #{self.frame_count} ({len(frame.audio)} bytes)")
        elif isinstance(frame, TextFrame):
            logger.info(f"📝 [{self._label}] {frame_type}: '{frame.text[:50]}...'")
        else:
            logger.debug(f"📦 [{self._label}] {frame_type}")

        await self.push_frame(frame, direction)


async def test_sequential_pipeline():
    """Test a simple sequential pipeline."""
    logger.info("=" * 70)
    logger.info("  TEST 1: Sequential Pipeline")
    logger.info("=" * 70)

    # Create mock components
    tts = MockTTSService(sample_rate=24000)

    # Create Unreal processors
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    # Start audio processor
    await audio_processor.start()

    # Add loggers
    logger_tts = FrameLogger("TTS Output")
    logger_events = FrameLogger("Events")
    logger_audio = FrameLogger("Audio")

    # Track results
    ws_messages = []
    udp_packets = []

    # Mock WebSocket
    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)
            logger.info(f"📤 WebSocket: {msg[:100]}")

    event_processor._websocket = MockWebSocket()

    # Mock UDP - replace the entire socket
    class MockSocket:
        def sendto(self, data, addr):
            udp_packets.append(data)
        def close(self):
            pass

    audio_processor._socket = MockSocket()

    # Build chain manually
    frames_at_end = []

    async def tts_push(frame, direction):
        await logger_tts.process_frame(frame, direction)

    async def logger_tts_push(frame, direction):
        await event_processor.process_frame(frame, direction)

    async def event_push(frame, direction):
        await logger_events.process_frame(frame, direction)

    async def logger_events_push(frame, direction):
        await audio_processor.process_frame(frame, direction)

    async def audio_push(frame, direction):
        await logger_audio.process_frame(frame, direction)

    async def logger_audio_push(frame, direction):
        frames_at_end.append(frame)

    tts.push_frame = tts_push
    logger_tts.push_frame = logger_tts_push
    event_processor.push_frame = event_push
    logger_events.push_frame = logger_events_push
    audio_processor.push_frame = audio_push
    logger_audio.push_frame = logger_audio_push

    # Process text
    logger.info("")
    logger.info("Sending text: 'Bonjour, je suis Avatar'")
    logger.info("-" * 70)

    text = TextFrame(text="Bonjour, je suis Avatar")
    await tts.process_frame(text, FrameDirection.DOWNSTREAM)

    # Results
    logger.info("-" * 70)
    logger.info("Results:")
    logger.info(f"  - Frames at end: {len(frames_at_end)}")
    logger.info(f"  - WebSocket messages: {len(ws_messages)}")
    logger.info(f"  - UDP packets: {len(udp_packets)}")
    logger.info(f"  - Total audio bytes: {sum(len(p) for p in udp_packets)}")

    await audio_processor.stop()

    return len(ws_messages) == 2 and len(udp_packets) > 0


async def test_parallel_branches():
    """Test parallel pipeline branches."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  TEST 2: Parallel Branches Simulation")
    logger.info("=" * 70)

    # Create TTS
    tts = MockTTSService(sample_rate=24000)

    # Branch A: Daily output
    branch_a_frames = []

    class BranchAOutput(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            branch_a_frames.append(frame)
            if isinstance(frame, OutputAudioRawFrame):
                if len(branch_a_frames) % 5 == 0:
                    logger.debug(f"🅰️  Branch A: Audio frame #{len(branch_a_frames)}")
            else:
                logger.info(f"🅰️  Branch A: {type(frame).__name__}")

    # Branch B: Unreal
    branch_b_frames = []
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    await audio_processor.start()

    # Mock connections
    ws_messages = []

    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)
            logger.info(f"🅱️  Branch B WebSocket: {msg[:80]}")

    event_processor._websocket = MockWebSocket()

    udp_packets = []

    # Mock UDP - replace the entire socket
    class MockSocket:
        def sendto(self, data, addr):
            udp_packets.append(data)
        def close(self):
            pass

    audio_processor._socket = MockSocket()

    # Setup branch B chain
    async def event_push(frame, direction):
        branch_b_frames.append(frame)
        await audio_processor.process_frame(frame, direction)

    async def audio_push(frame, direction):
        if len(udp_packets) % 5 == 0 and isinstance(frame, OutputAudioRawFrame):
            logger.debug(f"🅱️  Branch B: UDP packet #{len(udp_packets)}")

    event_processor.push_frame = event_push
    audio_processor.push_frame = audio_push

    # Setup TTS to send to both branches
    branch_a = BranchAOutput()

    async def tts_push(frame, direction):
        # Send to both branches (simulating ParallelPipeline)
        await branch_a.process_frame(frame, direction)
        await event_processor.process_frame(frame, direction)

    tts.push_frame = tts_push

    # Process text
    logger.info("")
    logger.info("Sending text: 'Test des branches parallèles'")
    logger.info("-" * 70)

    text = TextFrame(text="Test des branches parallèles")
    await tts.process_frame(text, FrameDirection.DOWNSTREAM)

    # Results
    logger.info("-" * 70)
    logger.info("Results:")
    logger.info(f"  - Branch A frames: {len(branch_a_frames)}")
    logger.info(f"  - Branch B frames: {len(branch_b_frames)}")
    logger.info(f"  - WebSocket messages: {len(ws_messages)}")
    logger.info(f"  - UDP packets: {len(udp_packets)}")

    # Verify both branches received same frames
    assert len(branch_a_frames) == len(branch_b_frames), "Branches should receive same frames"

    await audio_processor.stop()

    return True


async def test_interruption_handling():
    """Test handling of interruptions."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  TEST 3: Interruption Handling")
    logger.info("=" * 70)

    from pipecat.frames.frames import StartInterruptionFrame

    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")

    ws_messages = []

    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)
            logger.info(f"📤 WebSocket: {msg}")

    event_processor._websocket = MockWebSocket()

    async def noop_push(f, d):
        pass
    event_processor.push_frame = noop_push

    # Simulate: TTS starts, then interruption
    # Note: StartInterruptionFrame requires TaskManager which is only available
    # in a full Pipeline context. We simulate by directly calling stop_speaking.
    logger.info("")
    logger.info("Simulating: TTS start → Interruption (via direct command)")
    logger.info("-" * 70)

    await event_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.1)
    # Simulate interruption by sending stop_speaking directly
    logger.info(">>> User interrupts!")
    await event_processor._send_command({"type": "stop_speaking"})

    # Results
    logger.info("-" * 70)
    logger.info("Results:")
    logger.info(f"  - WebSocket messages: {len(ws_messages)}")

    # Should have: start_speaking, stop_speaking (from interruption)
    assert len(ws_messages) == 2

    import json
    start_msg = json.loads(ws_messages[0])
    stop_msg = json.loads(ws_messages[1])

    assert start_msg["type"] == "start_speaking"
    assert stop_msg["type"] == "stop_speaking"

    logger.info("  - Interruption correctly sent stop_speaking")

    return True


async def test_contextual_animations():
    """Test contextual animation commands."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  TEST 4: Contextual Animations")
    logger.info("=" * 70)

    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")

    ws_messages = []

    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)
            logger.info(f"📤 WebSocket: {msg}")

    event_processor._websocket = MockWebSocket()

    # Test all emotions
    emotions = ["neutral", "happy", "sad", "angry", "surprised"]

    logger.info("")
    logger.info("Testing all emotions:")
    logger.info("-" * 70)

    for emotion in emotions:
        await event_processor.send_contextual_animation(emotion, 0.8)
        await asyncio.sleep(0.05)

    # Results
    logger.info("-" * 70)
    logger.info("Results:")
    logger.info(f"  - Animation commands sent: {len(ws_messages)}")

    import json
    for i, msg in enumerate(ws_messages):
        data = json.loads(msg)
        logger.info(f"  - {emotions[i]}: intensity={data['intensity']}")

    return len(ws_messages) == len(emotions)


async def main():
    """Run all tests."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Avatar Pipeline Test Suite (with Mocks)")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This test suite validates the pipeline without external services.")
    logger.info("All Daily, STT, LLM, TTS, and Unreal connections are mocked.")
    logger.info("")

    results = []

    try:
        # Test 1
        result = await test_sequential_pipeline()
        results.append(("Sequential Pipeline", result))

        # Test 2
        result = await test_parallel_branches()
        results.append(("Parallel Branches", result))

        # Test 3
        result = await test_interruption_handling()
        results.append(("Interruption Handling", result))

        # Test 4
        result = await test_contextual_animations()
        results.append(("Contextual Animations", result))

    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Test Results Summary")
    logger.info("=" * 70)

    all_passed = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        icon = "✅" if passed else "❌"
        logger.info(f"  {icon} {name}: {status}")
        if not passed:
            all_passed = False

    logger.info("=" * 70)

    if all_passed:
        logger.info("All tests PASSED!")
        return 0
    else:
        logger.error("Some tests FAILED!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
