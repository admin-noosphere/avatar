"""NullAudioSink - Absorbs audio frames without blocking.

This processor receives audio frames and discards them, allowing the
pipeline to continue without blocking. Useful when you need a branch
that doesn't output audio but still processes other frames.
"""

from __future__ import annotations

import logging
from typing import Any

from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class NullAudioSink(FrameProcessor):
    """Processor that absorbs audio frames and passes through everything else.

    This prevents blocking in ParallelPipeline branches that don't need audio output.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the NullAudioSink."""
        super().__init__(**kwargs)
        self._audio_frames_absorbed = 0
        self._audio_bytes_absorbed = 0

    async def process_frame(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        """Process frames - absorb audio, pass through everything else.

        Args:
            frame: The frame to process.
            direction: The direction of frame flow.
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputAudioRawFrame):
            # Absorb audio frames - don't forward
            self._audio_frames_absorbed += 1
            self._audio_bytes_absorbed += len(frame.audio)

            if self._audio_frames_absorbed % 100 == 0:
                logger.debug(
                    f"NullAudioSink: Absorbed {self._audio_frames_absorbed} frames, "
                    f"{self._audio_bytes_absorbed / 1024:.1f} KB"
                )
        else:
            # Pass through all other frames
            await self.push_frame(frame, direction)

    def get_stats(self) -> dict[str, int]:
        """Get absorption statistics.

        Returns:
            Dictionary with frames and bytes absorbed.
        """
        return {
            "audio_frames_absorbed": self._audio_frames_absorbed,
            "audio_bytes_absorbed": self._audio_bytes_absorbed,
        }
