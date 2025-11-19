"""Debug utilities for Avatar pipeline testing.

This module provides tools to inspect, trace, and debug frame flow
through the Pipecat pipeline.

Usage:
    from debug_utils import FrameTracer, PipelineDebugger, FrameStats
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TextFrame,
    StartInterruptionFrame,
    EndFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


@dataclass
class FrameRecord:
    """Record of a single frame passing through the pipeline."""

    frame_type: str
    timestamp: float
    processor_name: str
    direction: str
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class FrameTracer(FrameProcessor):
    """Traces all frames passing through with timestamps and metadata.

    Useful for understanding exact frame flow and timing.

    Usage:
        tracer = FrameTracer("after_tts")
        # Add to pipeline
        # After test:
        tracer.print_trace()
        tracer.export_json("trace.json")
    """

    def __init__(self, name: str, log_all: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._name = name
        self.log_all = log_all
        self.records: list[FrameRecord] = []
        self._start_time = time.time()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Record frame
        frame_type = type(frame).__name__
        timestamp = time.time() - self._start_time

        metadata = {}
        size_bytes = 0

        if isinstance(frame, OutputAudioRawFrame):
            size_bytes = len(frame.audio)
            metadata = {
                "sample_rate": frame.sample_rate,
                "num_channels": frame.num_channels,
            }
        elif isinstance(frame, OutputImageRawFrame):
            size_bytes = len(frame.image)
            metadata = {"size": frame.size, "format": frame.format}
        elif isinstance(frame, TextFrame):
            metadata = {"text": frame.text[:100]}

        record = FrameRecord(
            frame_type=frame_type,
            timestamp=timestamp,
            processor_name=self._name,
            direction=direction.name,
            size_bytes=size_bytes,
            metadata=metadata,
        )
        self.records.append(record)

        if self.log_all:
            logger.debug(f"[{self._name}] {frame_type} @ {timestamp:.3f}s")

        await self.push_frame(frame, direction)

    def print_trace(self, max_audio: int = 5) -> None:
        """Print human-readable trace.

        Args:
            max_audio: Max audio frames to show (0 for all).
        """
        print(f"\n{'='*60}")
        print(f"  Frame Trace: {self._name}")
        print(f"{'='*60}")

        audio_count = 0
        for record in self.records:
            if record.frame_type == "OutputAudioRawFrame":
                audio_count += 1
                if max_audio > 0 and audio_count > max_audio:
                    if audio_count == max_audio + 1:
                        print(f"  ... (more audio frames)")
                    continue

            line = f"  {record.timestamp:8.3f}s | {record.frame_type:30s}"
            if record.size_bytes:
                line += f" | {record.size_bytes:6d} bytes"
            if record.metadata:
                meta_str = ", ".join(f"{k}={v}" for k, v in record.metadata.items())
                line += f" | {meta_str}"
            print(line)

        print(f"{'='*60}")
        print(f"  Total frames: {len(self.records)}")
        print(f"{'='*60}\n")

    def export_json(self, filepath: str) -> None:
        """Export trace to JSON file."""
        data = {
            "name": self._name,
            "total_frames": len(self.records),
            "records": [
                {
                    "frame_type": r.frame_type,
                    "timestamp": r.timestamp,
                    "processor": r.processor_name,
                    "direction": r.direction,
                    "size_bytes": r.size_bytes,
                    "metadata": r.metadata,
                }
                for r in self.records
            ],
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Trace exported to {filepath}")

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics."""
        by_type: dict[str, int] = defaultdict(int)
        total_bytes = 0

        for record in self.records:
            by_type[record.frame_type] += 1
            total_bytes += record.size_bytes

        duration = self.records[-1].timestamp if self.records else 0

        return {
            "name": self._name,
            "total_frames": len(self.records),
            "by_type": dict(by_type),
            "total_bytes": total_bytes,
            "duration_s": duration,
        }

    def clear(self) -> None:
        """Clear all records."""
        self.records.clear()
        self._start_time = time.time()


class FrameStats(FrameProcessor):
    """Collects statistics about frame flow without storing all frames.

    Lighter weight than FrameTracer for long-running tests.
    """

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._name = name
        self.counts: dict[str, int] = defaultdict(int)
        self.bytes: dict[str, int] = defaultdict(int)
        self._start_time = time.time()
        self._last_frame_time = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        frame_type = type(frame).__name__
        self.counts[frame_type] += 1
        self._last_frame_time = time.time()

        if isinstance(frame, OutputAudioRawFrame):
            self.bytes["audio"] += len(frame.audio)
        elif isinstance(frame, OutputImageRawFrame):
            self.bytes["video"] += len(frame.image)

        await self.push_frame(frame, direction)

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics."""
        duration = self._last_frame_time - self._start_time if self._last_frame_time else 0
        return {
            "name": self._name,
            "counts": dict(self.counts),
            "bytes": dict(self.bytes),
            "duration_s": duration,
            "total_frames": sum(self.counts.values()),
        }

    def print_stats(self) -> None:
        """Print statistics summary."""
        stats = self.get_stats()
        print(f"\n{'='*50}")
        print(f"  Stats: {self._name}")
        print(f"{'='*50}")
        print(f"  Duration: {stats['duration_s']:.2f}s")
        print(f"  Total frames: {stats['total_frames']}")
        print(f"\n  Frame counts:")
        for frame_type, count in sorted(stats["counts"].items()):
            print(f"    {frame_type}: {count}")
        if stats["bytes"]:
            print(f"\n  Data volume:")
            for data_type, size in stats["bytes"].items():
                print(f"    {data_type}: {size:,} bytes")
        print(f"{'='*50}\n")

    def reset(self) -> None:
        """Reset all statistics."""
        self.counts.clear()
        self.bytes.clear()
        self._start_time = time.time()
        self._last_frame_time = 0.0


class LatencyMeasurer(FrameProcessor):
    """Measures latency between frame pairs (e.g., TTSStarted to first audio).

    Usage:
        measurer = LatencyMeasurer("tts_latency")
        measurer.set_start_frame(TTSStartedFrame)
        measurer.set_end_frame(OutputAudioRawFrame)
    """

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._name = name
        self._start_frame_type: type | None = None
        self._end_frame_type: type | None = None
        self._start_time: float | None = None
        self.latencies: list[float] = []

    def set_start_frame(self, frame_type: type) -> None:
        """Set the frame type that starts measurement."""
        self._start_frame_type = frame_type

    def set_end_frame(self, frame_type: type) -> None:
        """Set the frame type that ends measurement."""
        self._end_frame_type = frame_type

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if self._start_frame_type and isinstance(frame, self._start_frame_type):
            self._start_time = time.time()

        if self._end_frame_type and isinstance(frame, self._end_frame_type):
            if self._start_time:
                latency = time.time() - self._start_time
                self.latencies.append(latency)
                self._start_time = None

        await self.push_frame(frame, direction)

    def get_stats(self) -> dict[str, Any]:
        """Get latency statistics."""
        if not self.latencies:
            return {"name": self._name, "count": 0}

        return {
            "name": self._name,
            "count": len(self.latencies),
            "min_ms": min(self.latencies) * 1000,
            "max_ms": max(self.latencies) * 1000,
            "avg_ms": sum(self.latencies) / len(self.latencies) * 1000,
        }

    def print_stats(self) -> None:
        """Print latency statistics."""
        stats = self.get_stats()
        print(f"\n{'='*40}")
        print(f"  Latency: {self._name}")
        print(f"{'='*40}")
        if stats["count"] == 0:
            print("  No measurements")
        else:
            print(f"  Measurements: {stats['count']}")
            print(f"  Min: {stats['min_ms']:.1f}ms")
            print(f"  Max: {stats['max_ms']:.1f}ms")
            print(f"  Avg: {stats['avg_ms']:.1f}ms")
        print(f"{'='*40}\n")


class FrameFilter(FrameProcessor):
    """Filters frames based on type or custom predicate.

    Useful for isolating specific frame types for testing.
    """

    def __init__(
        self,
        name: str,
        allow_types: list[type] | None = None,
        block_types: list[type] | None = None,
        predicate: Callable[[Frame], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._name = name
        self.allow_types = allow_types
        self.block_types = block_types or []
        self.predicate = predicate
        self.filtered_count = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Check if frame should pass
        should_pass = True

        if self.allow_types:
            should_pass = any(isinstance(frame, t) for t in self.allow_types)

        if should_pass and self.block_types:
            should_pass = not any(isinstance(frame, t) for t in self.block_types)

        if should_pass and self.predicate:
            should_pass = self.predicate(frame)

        if should_pass:
            await self.push_frame(frame, direction)
        else:
            self.filtered_count += 1


class FrameInspector:
    """Utility class for inspecting frame contents.

    Not a processor - use for ad-hoc inspection.
    """

    @staticmethod
    def describe(frame: Frame) -> str:
        """Get human-readable description of a frame."""
        frame_type = type(frame).__name__

        if isinstance(frame, OutputAudioRawFrame):
            duration_ms = len(frame.audio) / 2 / frame.sample_rate * 1000
            return (
                f"{frame_type}: {len(frame.audio)} bytes, "
                f"{frame.sample_rate}Hz, {frame.num_channels}ch, "
                f"{duration_ms:.1f}ms"
            )
        elif isinstance(frame, OutputImageRawFrame):
            return (
                f"{frame_type}: {frame.size[0]}x{frame.size[1]}, "
                f"{frame.format}, {len(frame.image)} bytes"
            )
        elif isinstance(frame, TextFrame):
            text_preview = frame.text[:50] + "..." if len(frame.text) > 50 else frame.text
            return f"{frame_type}: '{text_preview}'"
        elif isinstance(frame, (TTSStartedFrame, TTSStoppedFrame)):
            return frame_type
        elif isinstance(frame, StartInterruptionFrame):
            return f"{frame_type}: User interrupted"
        elif isinstance(frame, EndFrame):
            return f"{frame_type}: Pipeline end"
        else:
            return frame_type

    @staticmethod
    def to_dict(frame: Frame) -> dict[str, Any]:
        """Convert frame to dictionary for serialization."""
        data: dict[str, Any] = {"type": type(frame).__name__}

        if isinstance(frame, OutputAudioRawFrame):
            data.update(
                {
                    "audio_bytes": len(frame.audio),
                    "sample_rate": frame.sample_rate,
                    "num_channels": frame.num_channels,
                }
            )
        elif isinstance(frame, OutputImageRawFrame):
            data.update(
                {
                    "image_bytes": len(frame.image),
                    "width": frame.size[0],
                    "height": frame.size[1],
                    "format": frame.format,
                }
            )
        elif isinstance(frame, TextFrame):
            data["text"] = frame.text

        return data


class PipelineDebugger:
    """High-level debugger for pipeline testing.

    Provides convenient methods for common debugging tasks.
    """

    def __init__(self) -> None:
        self.tracers: dict[str, FrameTracer] = {}
        self.stats: dict[str, FrameStats] = {}
        self.latency_measurers: dict[str, LatencyMeasurer] = {}

    def create_tracer(self, name: str, log_all: bool = False) -> FrameTracer:
        """Create and register a frame tracer."""
        tracer = FrameTracer(name, log_all=log_all)
        self.tracers[name] = tracer
        return tracer

    def create_stats(self, name: str) -> FrameStats:
        """Create and register a frame stats collector."""
        stats = FrameStats(name)
        self.stats[name] = stats
        return stats

    def create_latency_measurer(
        self, name: str, start_frame: type, end_frame: type
    ) -> LatencyMeasurer:
        """Create and register a latency measurer."""
        measurer = LatencyMeasurer(name)
        measurer.set_start_frame(start_frame)
        measurer.set_end_frame(end_frame)
        self.latency_measurers[name] = measurer
        return measurer

    def print_all_traces(self) -> None:
        """Print all registered traces."""
        for tracer in self.tracers.values():
            tracer.print_trace()

    def print_all_stats(self) -> None:
        """Print all registered statistics."""
        for stats in self.stats.values():
            stats.print_stats()
        for measurer in self.latency_measurers.values():
            measurer.print_stats()

    def export_all(self, directory: str) -> None:
        """Export all traces to a directory."""
        import os

        os.makedirs(directory, exist_ok=True)

        for name, tracer in self.tracers.items():
            filepath = os.path.join(directory, f"trace_{name}.json")
            tracer.export_json(filepath)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all debug data."""
        return {
            "tracers": {name: tracer.get_stats() for name, tracer in self.tracers.items()},
            "stats": {name: stats.get_stats() for name, stats in self.stats.items()},
            "latencies": {
                name: measurer.get_stats()
                for name, measurer in self.latency_measurers.items()
            },
        }

    def clear_all(self) -> None:
        """Clear all collected data."""
        for tracer in self.tracers.values():
            tracer.clear()
        for stats in self.stats.values():
            stats.reset()


# Convenience function for quick debugging
def quick_trace(name: str = "debug") -> FrameTracer:
    """Create a quick tracer for debugging.

    Usage:
        tracer = quick_trace("my_test")
        # ... run pipeline ...
        tracer.print_trace()
    """
    return FrameTracer(name, log_all=True)


if __name__ == "__main__":
    # Demo usage
    print("Debug Utilities Demo")
    print("=" * 60)
    print()
    print("Available classes:")
    print("  - FrameTracer: Full trace with timestamps")
    print("  - FrameStats: Lightweight statistics")
    print("  - LatencyMeasurer: Measure frame-to-frame latency")
    print("  - FrameFilter: Filter specific frame types")
    print("  - FrameInspector: Describe/serialize frames")
    print("  - PipelineDebugger: High-level debugging")
    print()
    print("Example:")
    print("  tracer = FrameTracer('after_tts')")
    print("  # Add tracer to pipeline after TTS")
    print("  # Run pipeline")
    print("  tracer.print_trace()")
