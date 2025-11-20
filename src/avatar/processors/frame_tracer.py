"""FrameTracer - Debug processor to trace frame flow in pipeline."""

from __future__ import annotations

import logging
from typing import Any

from pipecat.frames.frames import Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class FrameTracer(FrameProcessor):
    """Debug processor that logs all frames passing through it.

    Insert at different points in pipeline to trace frame flow.
    """

    def __init__(self, name: str = "Tracer", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.name = name
        self._frame_count = 0

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        await super().process_frame(frame, direction)

        self._frame_count += 1
        frame_type = type(frame).__name__

        # Log important frames
        important_frames = [
            'TextFrame', 'TranscriptionFrame', 'TTSStartedFrame', 'TTSStoppedFrame',
            'OutputAudioRawFrame', 'LLMFullResponseStartFrame', 'LLMFullResponseEndFrame',
            'OpenAILLMContextFrame', 'LLMMessagesFrame', 'StartInterruptionFrame'
        ]

        if frame_type in important_frames:
            # Get frame content if available
            content = ""
            if hasattr(frame, 'text'):
                content = f" [{frame.text[:50]}...]" if len(getattr(frame, 'text', '')) > 50 else f" [{frame.text}]"

            logger.info(f"🔍 [{self.name}] #{self._frame_count} {frame_type}{content}")

        # Always forward the frame
        await self.push_frame(frame, direction)
