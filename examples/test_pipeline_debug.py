#!/usr/bin/env python3
"""Advanced pipeline test with full debugging and tracing.

This script provides comprehensive debugging for the Avatar pipeline,
showing exact frame flow, timing, and statistics.

Usage:
    python examples/test_pipeline_debug.py

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

from pipecat.frames.frames import (
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    OutputAudioRawFrame,
    StartInterruptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer

from mock_daily_transport import MockTTSService
from debug_utils import (
    FrameTracer,
    FrameStats,
    LatencyMeasurer,
    PipelineDebugger,
    FrameInspector,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline_debug")


async def test_with_full_tracing():
    """Test pipeline with full frame tracing at each stage."""
    logger.info("=" * 70)
    logger.info("  Full Pipeline Trace Test")
    logger.info("=" * 70)

    # Create debugger
    debugger = PipelineDebugger()

    # Create tracers for each stage
    tracer_tts = debugger.create_tracer("tts_output")
    tracer_events = debugger.create_tracer("event_processor")
    tracer_audio = debugger.create_tracer("audio_streamer")

    # Create latency measurer
    latency = debugger.create_latency_measurer(
        "tts_to_first_audio",
        TTSStartedFrame,
        OutputAudioRawFrame,
    )

    # Create processors
    tts = MockTTSService(sample_rate=24000)
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    await audio_processor.start()

    # Mock connections
    ws_messages = []

    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)

    event_processor._websocket = MockWebSocket()

    udp_packets = []

    # Mock UDP - replace the entire socket
    class MockSocket:
        def sendto(self, data, addr):
            udp_packets.append(data)
        def close(self):
            pass

    audio_processor._socket = MockSocket()

    # Chain processors with tracers
    async def tts_push(frame, direction):
        await tracer_tts.process_frame(frame, direction)

    async def tracer_tts_push(frame, direction):
        await latency.process_frame(frame, direction)

    async def latency_push(frame, direction):
        await event_processor.process_frame(frame, direction)

    async def event_push(frame, direction):
        await tracer_events.process_frame(frame, direction)

    async def tracer_events_push(frame, direction):
        await audio_processor.process_frame(frame, direction)

    async def audio_push(frame, direction):
        await tracer_audio.process_frame(frame, direction)

    async def tracer_audio_push(frame, direction):
        pass  # End of chain

    tts.push_frame = tts_push
    tracer_tts.push_frame = tracer_tts_push
    latency.push_frame = latency_push
    event_processor.push_frame = event_push
    tracer_events.push_frame = tracer_events_push
    audio_processor.push_frame = audio_push
    tracer_audio.push_frame = tracer_audio_push

    # Process text
    logger.info("")
    logger.info("Processing: 'Bonjour, je suis Avatar, comment puis-je vous aider?'")
    logger.info("-" * 70)

    text = TextFrame(text="Bonjour, je suis Avatar, comment puis-je vous aider?")
    await tts.process_frame(text, FrameDirection.DOWNSTREAM)

    # Print all traces
    debugger.print_all_traces()

    # Print latency
    latency.print_stats()

    # Summary
    logger.info("-" * 70)
    logger.info("Summary:")
    logger.info(f"  WebSocket messages: {len(ws_messages)}")
    logger.info(f"  UDP packets: {len(udp_packets)}")
    logger.info(f"  Total audio bytes: {sum(len(p) for p in udp_packets):,}")

    await audio_processor.stop()

    return True


async def test_with_statistics():
    """Test pipeline collecting statistics only (lighter weight)."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Statistics Collection Test")
    logger.info("=" * 70)

    # Create debugger
    debugger = PipelineDebugger()

    # Create stats collectors
    stats_tts = debugger.create_stats("tts_output")
    stats_unreal = debugger.create_stats("unreal_branch")

    # Create processors
    tts = MockTTSService(sample_rate=24000)
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    await audio_processor.start()

    # Mock connections
    class MockWebSocket:
        open = True
        async def send(self, msg):
            pass

    event_processor._websocket = MockWebSocket()

    class MockSocket:
        def sendto(self, data, addr):
            pass
        def close(self):
            pass

    audio_processor._socket = MockSocket()

    # Chain with stats
    async def tts_push(frame, direction):
        await stats_tts.process_frame(frame, direction)

    async def stats_tts_push(frame, direction):
        await event_processor.process_frame(frame, direction)

    async def event_push(frame, direction):
        await audio_processor.process_frame(frame, direction)

    async def audio_push(frame, direction):
        await stats_unreal.process_frame(frame, direction)

    async def stats_unreal_push(frame, direction):
        pass

    tts.push_frame = tts_push
    stats_tts.push_frame = stats_tts_push
    event_processor.push_frame = event_push
    audio_processor.push_frame = audio_push
    stats_unreal.push_frame = stats_unreal_push

    # Process multiple messages
    messages = [
        "Premier message test.",
        "Deuxième message plus long pour tester le streaming audio.",
        "Troisième message avec encore plus de mots pour générer plus de frames audio.",
    ]

    logger.info("")
    logger.info(f"Processing {len(messages)} messages...")
    logger.info("-" * 70)

    for i, msg in enumerate(messages, 1):
        logger.info(f"Message {i}: {msg[:40]}...")
        text = TextFrame(text=msg)
        await tts.process_frame(text, FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.1)  # Small delay between messages

    # Print stats
    debugger.print_all_stats()

    await audio_processor.stop()

    return True


async def test_frame_inspection():
    """Test frame inspection utilities."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Frame Inspection Test")
    logger.info("=" * 70)

    # Create sample frames
    frames = [
        TTSStartedFrame(),
        OutputAudioRawFrame(
            audio=b"\x00" * 1920,
            sample_rate=24000,
            num_channels=1,
        ),
        TextFrame(text="This is a test message for the avatar system."),
        TTSStoppedFrame(),
        StartInterruptionFrame(),
    ]

    logger.info("")
    logger.info("Frame descriptions:")
    logger.info("-" * 70)

    for frame in frames:
        description = FrameInspector.describe(frame)
        logger.info(f"  {description}")

    logger.info("")
    logger.info("Frame dictionaries:")
    logger.info("-" * 70)

    for frame in frames:
        frame_dict = FrameInspector.to_dict(frame)
        logger.info(f"  {frame_dict}")

    return True


async def test_interruption_tracing():
    """Test interruption handling with full tracing."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Interruption Tracing Test")
    logger.info("=" * 70)

    # Create tracer
    tracer = FrameTracer("interruption_test", log_all=True)

    # Create event processor
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")

    ws_messages = []

    class MockWebSocket:
        open = True
        async def send(self, msg):
            ws_messages.append(msg)
            logger.info(f"📤 WebSocket: {msg[:80]}")

    event_processor._websocket = MockWebSocket()

    # Chain
    async def event_push(frame, direction):
        await tracer.process_frame(frame, direction)

    async def tracer_push(frame, direction):
        pass

    event_processor.push_frame = event_push
    tracer.push_frame = tracer_push

    # Simulate: TTS starts, audio plays, then interruption
    logger.info("")
    logger.info("Simulating: TTS start → Audio → Interruption")
    logger.info("-" * 70)

    await event_processor.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

    # Some audio frames
    for _ in range(5):
        audio = OutputAudioRawFrame(
            audio=b"\x00" * 960,
            sample_rate=24000,
            num_channels=1,
        )
        await event_processor.process_frame(audio, FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.02)

    # Interruption!
    logger.info(">>> User interrupts!")
    await event_processor.process_frame(
        StartInterruptionFrame(), FrameDirection.DOWNSTREAM
    )

    # Print trace
    tracer.print_trace()

    # Verify
    logger.info("-" * 70)
    logger.info("Results:")
    logger.info(f"  WebSocket messages: {len(ws_messages)}")

    import json

    for i, msg in enumerate(ws_messages):
        data = json.loads(msg)
        logger.info(f"  Message {i+1}: type={data['type']}")

    return len(ws_messages) == 2  # start_speaking, stop_speaking


async def test_parallel_branch_tracing():
    """Test parallel branch behavior with tracing."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Parallel Branch Tracing Test")
    logger.info("=" * 70)

    # Create debugger
    debugger = PipelineDebugger()

    # Create tracers for each branch
    tracer_a = debugger.create_tracer("branch_a_daily")
    tracer_b = debugger.create_tracer("branch_b_unreal")

    # Create TTS
    tts = MockTTSService(sample_rate=24000)

    # Create branch B processors
    event_processor = UnrealEventProcessor(uri="ws://localhost:8765")
    audio_processor = UnrealAudioStreamer(host="127.0.0.1", port=8080)

    await audio_processor.start()

    # Mock connections
    class MockWebSocket:
        open = True
        async def send(self, msg):
            pass

    event_processor._websocket = MockWebSocket()

    class MockSocket:
        def sendto(self, data, addr):
            pass
        def close(self):
            pass

    audio_processor._socket = MockSocket()

    # Chain branch B
    async def event_push(frame, direction):
        await audio_processor.process_frame(frame, direction)

    async def audio_push(frame, direction):
        await tracer_b.process_frame(frame, direction)

    async def tracer_b_push(frame, direction):
        pass

    event_processor.push_frame = event_push
    audio_processor.push_frame = audio_push
    tracer_b.push_frame = tracer_b_push

    # TTS sends to both branches (simulating ParallelPipeline)
    async def tts_push(frame, direction):
        # Branch A: Direct to tracer (simulating Daily output)
        await tracer_a.process_frame(frame, direction)
        # Branch B: Through Unreal processors
        await event_processor.process_frame(frame, direction)

    async def tracer_a_push(frame, direction):
        pass  # End of branch A

    tts.push_frame = tts_push
    tracer_a.push_frame = tracer_a_push

    # Process text
    logger.info("")
    logger.info("Processing: 'Test des branches parallèles avec tracing'")
    logger.info("-" * 70)

    text = TextFrame(text="Test des branches parallèles avec tracing")
    await tts.process_frame(text, FrameDirection.DOWNSTREAM)

    # Print traces for both branches
    debugger.print_all_traces()

    # Compare
    stats_a = tracer_a.get_stats()
    stats_b = tracer_b.get_stats()

    logger.info("-" * 70)
    logger.info("Branch comparison:")
    logger.info(f"  Branch A (Daily): {stats_a['total_frames']} frames")
    logger.info(f"  Branch B (Unreal): {stats_b['total_frames']} frames")

    await audio_processor.stop()

    return stats_a["total_frames"] == stats_b["total_frames"]


async def main():
    """Run all debug tests."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("  Avatar Pipeline Debug Test Suite")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This test suite provides detailed debugging information")
    logger.info("for the Avatar pipeline using tracers and statistics.")
    logger.info("")

    results = []

    try:
        # Test 1: Full tracing
        result = await test_with_full_tracing()
        results.append(("Full Tracing", result))

        # Test 2: Statistics
        result = await test_with_statistics()
        results.append(("Statistics Collection", result))

        # Test 3: Frame inspection
        result = await test_frame_inspection()
        results.append(("Frame Inspection", result))

        # Test 4: Interruption tracing
        result = await test_interruption_tracing()
        results.append(("Interruption Tracing", result))

        # Test 5: Parallel branch tracing
        result = await test_parallel_branch_tracing()
        results.append(("Parallel Branch Tracing", result))

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
