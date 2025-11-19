"""Main Pipeline Assembly for Avatar MetaHuman.

This module assembles the complete Pipecat pipeline using ParallelPipeline
to handle dual audio output: user (Daily) and Unreal Engine (UDP + WebSocket).

Architecture:
    Daily Input → STT → LLM → TTS → ParallelPipeline
                                        ├─→ Branch A: transport.output() (user hears)
                                        └─→ Branch B: Unreal
                                             ├─→ UnrealEventProcessor (WebSocket)
                                             └─→ UnrealAudioStreamer (UDP)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transports.services.daily import DailyParams, DailyTransport

# Services
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

# Our processors
from avatar.processors.unreal_event_processor import UnrealEventProcessor
from avatar.processors.unreal_audio_streamer import UnrealAudioStreamer
from avatar.processors.ndi_output_processor import NDIOutputProcessor
from avatar.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class AvatarPipeline:
    """Main Avatar pipeline with ParallelPipeline for dual audio output.

    This class assembles all components and creates a pipeline that:
    1. Receives audio from Daily
    2. Transcribes with STT
    3. Generates response with LLM
    4. Synthesizes speech with TTS
    5. Outputs to both user (Daily) and Unreal (UDP/WebSocket)
    6. Receives NDI video from Unreal and sends to Daily
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the Avatar pipeline.

        Args:
            settings: Application settings. If None, loads from environment.
        """
        self.settings = settings or get_settings()
        self.transport: DailyTransport | None = None
        self.task: PipelineTask | None = None
        self.runner: PipelineRunner | None = None

        # Processors
        self.unreal_events: UnrealEventProcessor | None = None
        self.unreal_audio: UnrealAudioStreamer | None = None
        self.ndi_processor: NDIOutputProcessor | None = None

    def create_transport(self) -> DailyTransport:
        """Create Daily transport for WebRTC communication.

        Returns:
            Configured DailyTransport instance.
        """
        self.transport = DailyTransport(
            self.settings.daily_room_url,
            self.settings.daily_api_key,
            "Avatar",
            DailyParams(
                audio_out_enabled=True,
                audio_in_enabled=True,
                video_out_enabled=True,  # NDI video output
                camera_out_enabled=True,
                video_out_width=1920,
                video_out_height=1080,
                video_out_framerate=30,
                vad_analyzer=SileroVADAnalyzer(
                    params={"threshold": 0.5, "min_speech_duration_ms": 200}
                ),
                vad_audio_passthrough=True,
            ),
        )
        return self.transport

    def create_stt(self) -> OpenAISTTService:
        """Create Speech-to-Text service.

        Returns:
            Configured STT service.
        """
        return OpenAISTTService(
            api_key=self.settings.openai_api_key,
            model="whisper-1",
        )

    def create_llm(self) -> OpenAILLMService:
        """Create LLM service.

        Returns:
            Configured LLM service.
        """
        return OpenAILLMService(
            api_key=self.settings.openai_api_key,
            model=self.settings.llm_model,
            temperature=self.settings.llm_temperature,
        )

    def create_tts(self) -> ElevenLabsTTSService:
        """Create Text-to-Speech service.

        Returns:
            Configured TTS service.
        """
        return ElevenLabsTTSService(
            api_key=self.settings.elevenlabs_api_key,
            voice_id=self.settings.elevenlabs_voice_id,
            model=self.settings.elevenlabs_model,
            sample_rate=self.settings.audio_sample_rate,
            optimize_streaming_latency=self.settings.elevenlabs_optimize_latency,
        )

    def create_unreal_processors(self) -> tuple[UnrealEventProcessor, UnrealAudioStreamer]:
        """Create Unreal Engine processors.

        Returns:
            Tuple of (UnrealEventProcessor, UnrealAudioStreamer).
        """
        self.unreal_events = UnrealEventProcessor(
            uri=self.settings.unreal_websocket_uri,
        )

        self.unreal_audio = UnrealAudioStreamer(
            host=self.settings.unreal_audio_udp_host,
            port=self.settings.unreal_audio_udp_port,
        )

        return self.unreal_events, self.unreal_audio

    def create_ndi_processor(self) -> NDIOutputProcessor:
        """Create NDI processor for video from Unreal.

        Returns:
            Configured NDIOutputProcessor.
        """
        self.ndi_processor = NDIOutputProcessor(
            source_name=self.settings.ndi_source_name,
            source_ip=self.settings.unreal_audio_udp_host,  # Same IP as Unreal
            use_ndi_audio=True,  # Forward NDI audio to Daily
        )
        return self.ndi_processor

    def create_context(self) -> OpenAILLMContext:
        """Create LLM context with system prompt.

        Returns:
            Configured LLM context.
        """
        messages = [
            {
                "role": "system",
                "content": self.settings.llm_system_prompt,
            }
        ]
        return OpenAILLMContext(messages)

    def build_pipeline(self) -> Pipeline:
        """Build the complete pipeline with ParallelPipeline.

        Returns:
            Configured Pipeline instance.
        """
        # Create all components
        transport = self.create_transport()
        stt = self.create_stt()
        llm = self.create_llm()
        tts = self.create_tts()

        # Create context and aggregators
        context = self.create_context()
        context_aggregator = llm.create_context_aggregator(context)

        # Determine pipeline structure based on feature toggles
        if self.settings.enable_unreal or self.settings.enable_ndi:
            # Full pipeline with ParallelPipeline
            branches = []

            # Branch A: NDI → Daily (if enabled)
            if self.settings.enable_ndi:
                ndi_processor = self.create_ndi_processor()
                branches.append([ndi_processor, transport.output()])
                logger.info("  - Branch A: NDI → Daily transport (video + audio)")
            else:
                # No NDI - just send TTS audio to Daily
                branches.append([transport.output()])
                logger.info("  - Branch A: Direct TTS → Daily transport (audio only)")

            # Branch B: Unreal control (if enabled)
            if self.settings.enable_unreal:
                unreal_events, unreal_audio = self.create_unreal_processors()
                branches.append([unreal_events, unreal_audio])
                logger.info("  - Branch B: Unreal control (WebSocket + UDP)")

            # Build with ParallelPipeline only if we have multiple branches
            if len(branches) > 1:
                pipeline = Pipeline(
                    [
                        transport.input(),
                        stt,
                        context_aggregator.user(),
                        llm,
                        tts,
                        ParallelPipeline(*branches),
                        context_aggregator.assistant(),
                    ]
                )
                logger.info("Pipeline built with ParallelPipeline")
            else:
                # Single branch - no need for ParallelPipeline
                pipeline = Pipeline(
                    [
                        transport.input(),
                        stt,
                        context_aggregator.user(),
                        llm,
                        tts,
                        *branches[0],
                        context_aggregator.assistant(),
                    ]
                )
                logger.info("Pipeline built (single branch)")
        else:
            # Core only - no Unreal, no NDI
            # Simple pipeline: Daily → STT → LLM → TTS → Daily
            pipeline = Pipeline(
                [
                    transport.input(),
                    stt,
                    context_aggregator.user(),
                    llm,
                    tts,
                    transport.output(),
                    context_aggregator.assistant(),
                ]
            )
            logger.info("Pipeline built (core only - no Unreal/NDI)")

        return pipeline

    def create_task(self, pipeline: Pipeline) -> PipelineTask:
        """Create pipeline task with parameters.

        Args:
            pipeline: The pipeline to wrap in a task.

        Returns:
            Configured PipelineTask.
        """
        self.task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
            ),
        )
        return self.task

    async def run(self) -> None:
        """Run the complete Avatar pipeline."""
        logger.info("=" * 60)
        logger.info("  Avatar MetaHuman Pipeline - Starting")
        logger.info("=" * 60)
        logger.info(f"Daily Room: {self.settings.daily_room_url}")
        logger.info(f"TTS Model: {self.settings.elevenlabs_model}")
        logger.info(f"LLM Model: {self.settings.llm_model}")
        logger.info(f"Enable Unreal: {self.settings.enable_unreal}")
        logger.info(f"Enable NDI: {self.settings.enable_ndi}")
        if self.settings.enable_unreal:
            logger.info(f"  Unreal WebSocket: {self.settings.unreal_websocket_uri}")
            logger.info(f"  Unreal UDP: {self.settings.unreal_audio_udp_host}:{self.settings.unreal_audio_udp_port}")
        if self.settings.enable_ndi:
            logger.info(f"  NDI Source: {self.settings.ndi_source_name}")
        logger.info("=" * 60)

        # Build pipeline
        pipeline = self.build_pipeline()
        task = self.create_task(pipeline)

        # Setup event handlers
        self._setup_event_handlers()

        # Run
        self.runner = PipelineRunner()
        await self.runner.run(task)

    def _setup_event_handlers(self) -> None:
        """Setup Daily transport event handlers."""
        if not self.transport:
            return

        @self.transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            user_name = participant.get("info", {}).get("userName", "Unknown")
            logger.info(f"First participant joined: {user_name}")

            # Start NDI reception from Unreal (if enabled)
            if self.settings.enable_ndi and self.ndi_processor:
                logger.info("Starting NDI reception from Unreal...")
                await self.ndi_processor.start_ndi()
                logger.info("NDI started - Video + Audio streaming")

            # Start Unreal audio streamer (if enabled)
            if self.settings.enable_unreal and self.unreal_audio:
                await self.unreal_audio.start()
                logger.info("Unreal audio streamer started")

            # Send welcome message
            from pipecat.frames.frames import TTSSpeakFrame
            if self.task:
                await self.task.queue_frames([
                    TTSSpeakFrame("Bonjour! Je suis Avatar, comment puis-je vous aider?")
                ])

        @self.transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            logger.info(f"Participant left: {reason}")

            # Stop NDI if no more participants
            if self.ndi_processor and self.ndi_processor.is_running:
                await self.ndi_processor.stop_ndi()
                logger.info("NDI stopped")


async def main() -> None:
    """Main entry point for Avatar pipeline."""
    import os
    from dotenv import load_dotenv

    # Load environment
    load_dotenv()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Create and run pipeline
    avatar = AvatarPipeline()

    try:
        await avatar.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
