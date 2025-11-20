"""Audio Diagnostic Logger for debugging synchronization issues.

This module provides detailed logging of all audio events to help identify
gaps, truncations, and timing issues in the audio pipeline.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AudioEvent:
    """Single audio event for diagnostic logging."""
    timestamp: float
    event_type: str
    utterance_id: int
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class AudioDiagnostic:
    """Diagnostic logger for audio pipeline events.

    Tracks all audio events with precise timing to help identify:
    - Gaps between audio chunks
    - Truncated phrases
    - Timing mismatches
    - Out-of-order events
    """

    def __init__(self, log_file: str | Path = "audio_diagnostic.jsonl"):
        """Initialize the diagnostic logger.

        Args:
            log_file: Path to the JSONL log file.
        """
        self.log_file = Path(log_file)
        self.events: list[AudioEvent] = []
        self.start_time = time.monotonic()
        self._current_utterance: int = 0

        # Per-utterance tracking
        self._utterance_data: dict[int, dict] = {}

        # Clear previous log
        self.log_file.write_text("")
        logger.info(f"📊 AudioDiagnostic initialized, logging to {self.log_file}")

    def _elapsed(self) -> float:
        """Get elapsed time since start in milliseconds."""
        return (time.monotonic() - self.start_time) * 1000

    def _log_event(self, event: AudioEvent) -> None:
        """Log an event to memory and file."""
        self.events.append(event)

        # Append to JSONL file
        with open(self.log_file, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def utterance_started(self, utterance_id: int) -> None:
        """Log utterance start."""
        self._current_utterance = utterance_id
        self._utterance_data[utterance_id] = {
            "start_time": self._elapsed(),
            "audio_bytes": 0,
            "audio_chunks": 0,
            "audio_duration_ms": 0.0,
            "first_audio_time": None,
            "last_audio_time": None,
        }

        event = AudioEvent(
            timestamp=self._elapsed(),
            event_type="UTTERANCE_STARTED",
            utterance_id=utterance_id,
        )
        self._log_event(event)
        logger.info(f"📊 [{self._elapsed():.0f}ms] Utterance #{utterance_id} STARTED")

    def audio_received(self, utterance_id: int, audio_bytes: int, audio_duration_ms: float) -> None:
        """Log audio chunk received."""
        now = self._elapsed()

        if utterance_id in self._utterance_data:
            data = self._utterance_data[utterance_id]
            data["audio_bytes"] += audio_bytes
            data["audio_chunks"] += 1
            data["audio_duration_ms"] += audio_duration_ms

            if data["first_audio_time"] is None:
                data["first_audio_time"] = now
                ttfa = now - data["start_time"]
                logger.info(f"📊 [{now:.0f}ms] Utterance #{utterance_id} FIRST_AUDIO (TTFA: {ttfa:.0f}ms)")

            data["last_audio_time"] = now

        event = AudioEvent(
            timestamp=now,
            event_type="AUDIO_RECEIVED",
            utterance_id=utterance_id,
            data={
                "bytes": audio_bytes,
                "duration_ms": audio_duration_ms,
                "total_bytes": self._utterance_data.get(utterance_id, {}).get("audio_bytes", 0),
                "total_duration_ms": self._utterance_data.get(utterance_id, {}).get("audio_duration_ms", 0),
            }
        )
        self._log_event(event)

    def audio_sent(self, utterance_id: int, audio_bytes: int) -> None:
        """Log audio chunk sent via UDP."""
        event = AudioEvent(
            timestamp=self._elapsed(),
            event_type="AUDIO_SENT",
            utterance_id=utterance_id,
            data={"bytes": audio_bytes}
        )
        self._log_event(event)

    def utterance_stop_received(self, utterance_id: int, remaining_ms: float) -> None:
        """Log TTSStoppedFrame received."""
        now = self._elapsed()

        if utterance_id in self._utterance_data:
            data = self._utterance_data[utterance_id]
            elapsed_since_start = now - data["start_time"]

            event = AudioEvent(
                timestamp=now,
                event_type="STOP_RECEIVED",
                utterance_id=utterance_id,
                data={
                    "elapsed_ms": elapsed_since_start,
                    "audio_duration_ms": data["audio_duration_ms"],
                    "remaining_ms": remaining_ms,
                    "total_bytes": data["audio_bytes"],
                    "total_chunks": data["audio_chunks"],
                }
            )
            self._log_event(event)

            logger.info(
                f"📊 [{now:.0f}ms] Utterance #{utterance_id} STOP_RECEIVED "
                f"(elapsed: {elapsed_since_start:.0f}ms, audio: {data['audio_duration_ms']:.0f}ms, "
                f"remaining: {remaining_ms:.0f}ms, {data['audio_chunks']} chunks, {data['audio_bytes']} bytes)"
            )
        else:
            event = AudioEvent(
                timestamp=now,
                event_type="STOP_RECEIVED",
                utterance_id=utterance_id,
                data={"remaining_ms": remaining_ms, "error": "no_utterance_data"}
            )
            self._log_event(event)
            logger.warning(f"📊 [{now:.0f}ms] STOP_RECEIVED for unknown utterance #{utterance_id}")

    def utterance_completed(self, utterance_id: int) -> None:
        """Log utterance completion (after delay if any)."""
        now = self._elapsed()

        if utterance_id in self._utterance_data:
            data = self._utterance_data[utterance_id]
            total_time = now - data["start_time"]

            event = AudioEvent(
                timestamp=now,
                event_type="UTTERANCE_COMPLETED",
                utterance_id=utterance_id,
                data={
                    "total_time_ms": total_time,
                    "audio_duration_ms": data["audio_duration_ms"],
                    "total_bytes": data["audio_bytes"],
                    "total_chunks": data["audio_chunks"],
                }
            )
            self._log_event(event)

            logger.info(
                f"📊 [{now:.0f}ms] Utterance #{utterance_id} COMPLETED "
                f"(total: {total_time:.0f}ms, audio: {data['audio_duration_ms']:.0f}ms)"
            )
        else:
            event = AudioEvent(
                timestamp=now,
                event_type="UTTERANCE_COMPLETED",
                utterance_id=utterance_id,
                data={"error": "no_utterance_data"}
            )
            self._log_event(event)

    def interruption(self, utterance_id: int) -> None:
        """Log user interruption."""
        event = AudioEvent(
            timestamp=self._elapsed(),
            event_type="INTERRUPTION",
            utterance_id=utterance_id,
        )
        self._log_event(event)
        logger.info(f"📊 [{self._elapsed():.0f}ms] INTERRUPTION during utterance #{utterance_id}")

    def websocket_event(self, event_type: str, command: str) -> None:
        """Log WebSocket event."""
        event = AudioEvent(
            timestamp=self._elapsed(),
            event_type=f"WEBSOCKET_{event_type}",
            utterance_id=self._current_utterance,
            data={"command": command}
        )
        self._log_event(event)

    def error(self, message: str, utterance_id: int | None = None) -> None:
        """Log an error."""
        event = AudioEvent(
            timestamp=self._elapsed(),
            event_type="ERROR",
            utterance_id=utterance_id or self._current_utterance,
            data={"message": message}
        )
        self._log_event(event)
        logger.error(f"📊 [{self._elapsed():.0f}ms] ERROR: {message}")

    def get_summary(self) -> dict:
        """Get summary of all utterances."""
        summary = {
            "total_utterances": len(self._utterance_data),
            "utterances": {}
        }

        for uid, data in self._utterance_data.items():
            summary["utterances"][uid] = {
                "audio_duration_ms": data["audio_duration_ms"],
                "audio_bytes": data["audio_bytes"],
                "audio_chunks": data["audio_chunks"],
            }

        return summary

    def print_summary(self) -> None:
        """Print summary to logger."""
        summary = self.get_summary()
        logger.info(f"📊 DIAGNOSTIC SUMMARY: {json.dumps(summary, indent=2)}")


# Global instance
_diagnostic: AudioDiagnostic | None = None


def get_diagnostic() -> AudioDiagnostic:
    """Get or create the global diagnostic instance."""
    global _diagnostic
    if _diagnostic is None:
        _diagnostic = AudioDiagnostic()
    return _diagnostic


def reset_diagnostic() -> AudioDiagnostic:
    """Reset the global diagnostic instance."""
    global _diagnostic
    _diagnostic = AudioDiagnostic()
    return _diagnostic
