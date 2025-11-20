"""Configuration management using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # API Keys
    # =========================================================================
    openai_api_key: str = Field(default="", description="OpenAI API key")
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key")

    # =========================================================================
    # Unreal Engine Integration
    # =========================================================================
    unreal_websocket_uri: str = Field(
        default="ws://192.168.1.14:60765",
        description="WebSocket URI for Unreal Engine control",
    )
    unreal_audio_udp_host: str = Field(
        default="192.168.1.14",
        description="UDP host for Audio2Face streaming",
    )
    unreal_audio_udp_port: int = Field(
        default=8080,
        description="UDP port for Audio2Face streaming",
    )

    # =========================================================================
    # NDI Configuration
    # =========================================================================
    ndi_source_name: str = Field(
        default="MY_SOURCE",
        description="NDI source name for video/audio input",
    )
    ndi_video_enabled: bool = Field(
        default=True,
        description="Enable NDI video input",
    )
    ndi_video_fps: int = Field(
        default=1,
        description="Video frame rate (decimation for CPU reduction)",
    )
    ndi_video_width: int = Field(
        default=640,
        description="Video frame width",
    )
    ndi_video_height: int = Field(
        default=360,
        description="Video frame height",
    )

    # =========================================================================
    # Audio Settings
    # =========================================================================
    audio_sample_rate: int = Field(
        default=24000,
        description="Audio sample rate (must be 24000 for Audio2Face)",
    )
    audio_channels: int = Field(
        default=1,
        description="Number of audio channels",
    )

    # =========================================================================
    # LLM Configuration
    # =========================================================================
    llm_provider: Literal["openai", "anthropic"] = Field(
        default="openai",
        description="LLM provider to use",
    )
    llm_model: str = Field(
        default="gpt-4o",
        description="LLM model name",
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature for response generation",
    )
    llm_max_tokens: int = Field(
        default=150,
        description="Maximum tokens for LLM response",
    )
    llm_system_prompt: str = Field(
        default=(
            "You are a helpful AI assistant controlling a MetaHuman avatar. "
            "Keep responses concise and natural for voice conversation."
        ),
        description="System prompt for LLM",
    )

    # =========================================================================
    # TTS Configuration (ElevenLabs)
    # =========================================================================
    elevenlabs_voice_id: str = Field(
        default="",
        description="ElevenLabs voice ID",
    )
    elevenlabs_model: str = Field(
        default="eleven_flash_v2_5",
        description="ElevenLabs model (use eleven_flash_v2_5 for low latency)",
    )
    elevenlabs_stability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Voice stability (0-1)",
    )
    elevenlabs_similarity_boost: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Voice similarity boost (0-1)",
    )
    elevenlabs_optimize_latency: int = Field(
        default=4,
        ge=0,
        le=4,
        description="Latency optimization level (0-4, 4=max)",
    )

    # =========================================================================
    # Transport Configuration
    # =========================================================================
    transport_type: Literal["daily", "small-webrtc"] = Field(
        default="daily",
        description="WebRTC transport type",
    )
    daily_room_url: str = Field(
        default="",
        description="Daily.co room URL",
    )
    daily_api_key: str = Field(
        default="",
        description="Daily.co API key",
    )

    # =========================================================================
    # Interruption Handling
    # =========================================================================
    interruption_min_words: int = Field(
        default=3,
        ge=1,
        description="Minimum words required for user to interrupt bot",
    )
    vad_stop_secs: float = Field(
        default=0.5,
        ge=0.1,
        description="Silence duration before considering user stopped speaking",
    )
    allow_interruptions: bool = Field(
        default=False,
        description="Allow user to interrupt the bot (disable if using speakers without AEC)",
    )

    # =========================================================================
    # Logging
    # =========================================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_format: Literal["json", "text"] = Field(
        default="json",
        description="Log output format",
    )
    log_file: str = Field(
        default="logs/avatar.log",
        description="Log file path",
    )

    # =========================================================================
    # Development
    # =========================================================================
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )
    mock_unreal: bool = Field(
        default=False,
        description="Use mock Unreal server for testing",
    )

    # =========================================================================
    # Feature Toggles (for testing core without Unreal)
    # =========================================================================
    enable_unreal: bool = Field(
        default=True,
        description="Enable Unreal Engine integration (WebSocket + UDP audio)",
    )
    enable_ndi: bool = Field(
        default=True,
        description="Enable NDI video/audio from Unreal",
    )

    def validate_audio2face_settings(self) -> None:
        """Validate that audio settings are compatible with Audio2Face."""
        valid_sample_rates = [16000, 22050, 24000, 44100]
        if self.audio_sample_rate not in valid_sample_rates:
            raise ValueError(
                f"audio_sample_rate must be one of {valid_sample_rates}, "
                f"got {self.audio_sample_rate}"
            )

    def validate_elevenlabs_settings(self) -> None:
        """Validate ElevenLabs configuration."""
        if not self.elevenlabs_api_key and not self.mock_unreal:
            raise ValueError("elevenlabs_api_key is required when mock_unreal=False")
        if not self.elevenlabs_voice_id and not self.mock_unreal:
            raise ValueError("elevenlabs_voice_id is required when mock_unreal=False")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Application settings loaded from environment.
    """
    settings = Settings()
    settings.validate_audio2face_settings()
    return settings
