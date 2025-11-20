#!/usr/bin/env python3
"""Simple Avatar pipeline - VAD → LLM → TTS → Unreal.

Uses the proven Pipecat pattern with LLMUserResponseAggregator/LLMAssistantResponseAggregator.
Audio is intercepted and sent to Unreal via UDP with proper chunking.
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import (
    LLMAssistantResponseAggregator,
    LLMUserResponseAggregator,
)
from pipecat.frames.frames import LLMMessagesFrame
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer
from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.null_audio_sink import NullAudioSink

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simple_unreal")


async def main():
    """Run simple Avatar pipeline."""
    load_dotenv()

    # Validate environment
    required = ["OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "DAILY_ROOM_URL"]
    for var in required:
        if not os.getenv(var):
            logger.error(f"{var} is required")
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("  Simple Avatar Pipeline")
    logger.info("  VAD → LLM → TTS → Unreal")
    logger.info("=" * 60)

    # Create transport
    transport = DailyTransport(
        os.getenv("DAILY_ROOM_URL"),
        os.getenv("DAILY_API_KEY", ""),
        "Avatar",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=False,  # No audio to Daily
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,
                    start_secs=0.2,
                    stop_secs=0.8,
                    min_volume=0.5,
                )
            ),
        ),
    )

    # Create services
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
    )

    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
        model="eleven_flash_v2_5",
    )

    # Create Unreal processors
    unreal_audio = UnrealAudioStreamer(
        host="192.168.1.14",
        port=8080,  # UDP audio port
    )

    unreal_events = UnrealEventProcessor(
        uri="ws://192.168.1.14:60765",  # WebSocket control port
    )

    # System prompt
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant IA conversationnel amical. "
                       "Réponds de manière concise et naturelle pour une conversation vocale. "
                       "Commence par dire bonjour.",
        },
    ]

    # Create aggregators (proven pattern)
    tma_in = LLMUserResponseAggregator(messages)
    tma_out = LLMAssistantResponseAggregator(messages)

    # Absorb audio after Unreal (don't send to Daily)
    null_sink = NullAudioSink()

    # Build pipeline - simple and clean
    # No transport.output() - audio goes only to Unreal
    pipeline = Pipeline([
        transport.input(),
        tma_in,
        llm,
        tts,
        unreal_audio,      # Send audio → UDP to Unreal
        unreal_events,     # Send WebSocket events
        tma_out,
    ])

    # Create task
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
    )

    # Event handlers
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        user_name = participant.get("info", {}).get("userName", "Unknown")
        logger.info(f"Participant joined: {user_name}")

        # Start Unreal processors
        await unreal_events.start()
        await unreal_audio.start()

        # Initialize conversation
        await task.queue_frames([LLMMessagesFrame(messages)])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {reason}")

    # Run
    logger.info(f"Daily Room: {os.getenv('DAILY_ROOM_URL')}")
    logger.info(f"UDP Audio → 192.168.1.14:8080")
    logger.info(f"WebSocket → ws://192.168.1.14:60765")
    logger.info("=" * 60)

    runner = PipelineRunner()
    await runner.run(task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
