"""Mock Daily Transport for testing Avatar pipeline without real WebRTC.

This module provides mock implementations of Daily transport components
to test the full pipeline locally without connecting to Daily.co.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    StartFrame,
    EndFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class MockDailyInput(FrameProcessor):
    """Mock Daily input that simulates user audio input.

    Can be fed audio frames to simulate a user speaking.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the mock input."""
        await super().start()
        self._running = True
        logger.info("MockDailyInput started")

    async def stop(self) -> None:
        """Stop the mock input."""
        self._running = False
        if self._task:
            self._task.cancel()
        await super().stop()
        logger.info("MockDailyInput stopped")

    async def inject_audio(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Inject audio data as if user spoke.

        Args:
            audio_data: Raw PCM audio bytes.
            sample_rate: Audio sample rate.
        """
        frame = InputAudioRawFrame(
            audio=audio_data,
            sample_rate=sample_rate,
            num_channels=1,
        )
        await self.push_frame(frame, FrameDirection.DOWNSTREAM)
        logger.debug(f"Injected {len(audio_data)} bytes of audio")

    async def inject_user_speaking(self, speaking: bool) -> None:
        """Inject user speaking state.

        Args:
            speaking: True if user started speaking, False if stopped.
        """
        if speaking:
            await self.push_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            logger.info("Injected: User started speaking")
        else:
            await self.push_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            logger.info("Injected: User stopped speaking")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Pass through frames."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class MockDailyOutput(FrameProcessor):
    """Mock Daily output that captures frames sent to user.

    Captures all audio and video frames for verification.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.audio_frames: list[OutputAudioRawFrame] = []
        self.video_frames: list[OutputImageRawFrame] = []
        self.all_frames: list[Frame] = []
        self._on_audio_callback: Callable[[OutputAudioRawFrame], None] | None = None
        self._on_video_callback: Callable[[OutputImageRawFrame], None] | None = None

    def on_audio(self, callback: Callable[[OutputAudioRawFrame], None]) -> None:
        """Register callback for audio frames."""
        self._on_audio_callback = callback

    def on_video(self, callback: Callable[[OutputImageRawFrame], None]) -> None:
        """Register callback for video frames."""
        self._on_video_callback = callback

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Capture frames."""
        await super().process_frame(frame, direction)

        self.all_frames.append(frame)

        if isinstance(frame, OutputAudioRawFrame):
            self.audio_frames.append(frame)
            if self._on_audio_callback:
                self._on_audio_callback(frame)
            if len(self.audio_frames) % 100 == 0:
                logger.debug(f"Captured {len(self.audio_frames)} audio frames")

        elif isinstance(frame, OutputImageRawFrame):
            self.video_frames.append(frame)
            if self._on_video_callback:
                self._on_video_callback(frame)
            if len(self.video_frames) % 30 == 0:
                logger.debug(f"Captured {len(self.video_frames)} video frames")

        # Don't push frame further - this is the end of the pipeline
        # await self.push_frame(frame, direction)

    def get_stats(self) -> dict[str, Any]:
        """Get capture statistics."""
        total_audio_bytes = sum(len(f.audio) for f in self.audio_frames)
        return {
            "audio_frames": len(self.audio_frames),
            "video_frames": len(self.video_frames),
            "total_frames": len(self.all_frames),
            "audio_bytes": total_audio_bytes,
            "audio_duration_ms": (total_audio_bytes / 2) / 24 if self.audio_frames else 0,
        }

    def clear(self) -> None:
        """Clear captured frames."""
        self.audio_frames.clear()
        self.video_frames.clear()
        self.all_frames.clear()


class MockDailyTransport:
    """Mock Daily transport combining input and output.

    Provides a simplified interface similar to real DailyTransport.
    """

    def __init__(self) -> None:
        self._input = MockDailyInput()
        self._output = MockDailyOutput()
        self._event_handlers: dict[str, list[Callable]] = {}

    def input(self) -> MockDailyInput:
        """Get input processor."""
        return self._input

    def output(self) -> MockDailyOutput:
        """Get output processor."""
        return self._output

    def event_handler(self, event_name: str):
        """Decorator to register event handler."""
        def decorator(func: Callable):
            if event_name not in self._event_handlers:
                self._event_handlers[event_name] = []
            self._event_handlers[event_name].append(func)
            return func
        return decorator

    async def emit_event(self, event_name: str, *args, **kwargs) -> None:
        """Emit an event to registered handlers."""
        if event_name in self._event_handlers:
            for handler in self._event_handlers[event_name]:
                await handler(self, *args, **kwargs)

    async def simulate_participant_join(self, user_name: str = "TestUser") -> None:
        """Simulate a participant joining."""
        participant = {
            "info": {"userName": user_name},
            "id": "test-participant-id",
        }
        await self.emit_event("on_first_participant_joined", participant)
        logger.info(f"Simulated participant join: {user_name}")

    async def simulate_participant_leave(self, reason: str = "left") -> None:
        """Simulate a participant leaving."""
        participant = {"id": "test-participant-id"}
        await self.emit_event("on_participant_left", participant, reason)
        logger.info(f"Simulated participant leave: {reason}")

    def get_output_stats(self) -> dict[str, Any]:
        """Get output capture statistics."""
        return self._output.get_stats()


class MockSTTService(FrameProcessor):
    """Mock STT service that returns predefined transcriptions."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._transcriptions: list[str] = []
        self._transcription_index = 0

    def set_transcriptions(self, transcriptions: list[str]) -> None:
        """Set transcriptions to return."""
        self._transcriptions = transcriptions
        self._transcription_index = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Convert audio to text."""
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            # Return next transcription
            if self._transcription_index < len(self._transcriptions):
                from pipecat.frames.frames import TranscriptionFrame
                text = self._transcriptions[self._transcription_index]
                self._transcription_index += 1

                transcription = TranscriptionFrame(
                    text=text,
                    user_id="test-user",
                    timestamp=0,
                )
                await self.push_frame(transcription, direction)
                logger.info(f"MockSTT: '{text}'")
        else:
            await self.push_frame(frame, direction)


class MockLLMService(FrameProcessor):
    """Mock LLM service that returns predefined responses."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses: list[str] = ["Bonjour! Comment puis-je vous aider?"]
        self._response_index = 0

    def set_responses(self, responses: list[str]) -> None:
        """Set responses to return."""
        self._responses = responses
        self._response_index = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Generate response."""
        await super().process_frame(frame, direction)

        from pipecat.frames.frames import TranscriptionFrame, TextFrame

        if isinstance(frame, TranscriptionFrame):
            # Return next response
            if self._response_index < len(self._responses):
                text = self._responses[self._response_index]
                self._response_index += 1
            else:
                text = self._responses[-1]  # Repeat last

            response = TextFrame(text=text)
            await self.push_frame(response, direction)
            logger.info(f"MockLLM: '{text}'")
        else:
            await self.push_frame(frame, direction)


class MockTTSService(FrameProcessor):
    """Mock TTS service that generates fake audio."""

    def __init__(self, sample_rate: int = 24000, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sample_rate = sample_rate

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Generate audio from text."""
        await super().process_frame(frame, direction)

        from pipecat.frames.frames import TextFrame, TTSStartedFrame, TTSStoppedFrame

        if isinstance(frame, TextFrame):
            # Emit TTS started
            await self.push_frame(TTSStartedFrame(), direction)

            # Generate fake audio (100ms per word)
            words = frame.text.split()
            duration_ms = len(words) * 100
            num_samples = int(self.sample_rate * duration_ms / 1000)

            # Generate silence as fake audio
            audio_data = b'\x00' * (num_samples * 2)

            # Send in chunks
            chunk_size = 960  # 20ms at 24kHz
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                audio_frame = OutputAudioRawFrame(
                    audio=chunk,
                    sample_rate=self.sample_rate,
                    num_channels=1,
                )
                await self.push_frame(audio_frame, direction)

            # Emit TTS stopped
            await self.push_frame(TTSStoppedFrame(), direction)
            logger.info(f"MockTTS: Generated {duration_ms}ms audio for '{frame.text[:30]}...'")
        else:
            await self.push_frame(frame, direction)
