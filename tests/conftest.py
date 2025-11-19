"""Pytest configuration and shared fixtures for Avatar tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.open = True
    ws.send = AsyncMock()
    ws.recv = AsyncMock(return_value='{"type": "ack"}')
    ws.close = AsyncMock()
    ws.wait_closed = AsyncMock()
    return ws


@pytest.fixture
def mock_socket():
    """Create a mock UDP socket."""
    import socket
    sock = MagicMock(spec=socket.socket)
    sock.sendto = MagicMock(return_value=None)
    sock.close = MagicMock()
    sock.setblocking = MagicMock()
    sock.setsockopt = MagicMock()
    return sock


@pytest.fixture
def sample_audio_frame():
    """Create a sample audio frame for testing."""
    from pipecat.frames.frames import OutputAudioRawFrame

    # 20ms of silence at 24kHz mono (480 samples * 2 bytes)
    audio_data = b'\x00' * 960

    return OutputAudioRawFrame(
        audio=audio_data,
        sample_rate=24000,
        num_channels=1,
    )


@pytest.fixture
def sample_tts_frames():
    """Create sample TTS lifecycle frames."""
    from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame

    return {
        "started": TTSStartedFrame(),
        "stopped": TTSStoppedFrame(),
    }


@pytest.fixture
def sample_image_frame():
    """Create a sample image frame for testing."""
    from pipecat.frames.frames import OutputImageRawFrame

    # Small 10x10 RGB image
    width, height = 10, 10
    image_data = b'\xff\x00\x00' * (width * height)  # Red pixels

    return OutputImageRawFrame(
        image=image_data,
        size=(width, height),
        format="RGB",
    )


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    from avatar.config.settings import Settings

    return Settings(
        openai_api_key="test-openai-key",
        elevenlabs_api_key="test-elevenlabs-key",
        elevenlabs_voice_id="test-voice-id",
        daily_room_url="https://test.daily.co/room",
        daily_api_key="test-daily-key",
        unreal_websocket_uri="ws://localhost:8765",
        unreal_audio_udp_host="127.0.0.1",
        unreal_audio_udp_port=8080,
        ndi_source_name="TEST_SOURCE",
        mock_unreal=True,
    )
