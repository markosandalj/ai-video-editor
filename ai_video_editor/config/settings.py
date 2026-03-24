from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


LogLevel = Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]


class GeneralConfig(BaseModel):
    """Global settings. Extended in later phases."""

    model_config = ConfigDict(extra="allow")

    output_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "output",
        description="Directory for processed files and logs.",
    )
    temp_dir: Path = Field(
        default_factory=lambda: Path.cwd() / ".ai_video_editor_tmp",
        description="Scratch space for intermediate files.",
    )
    log_level: LogLevel = "INFO"

    @field_validator("output_dir", "temp_dir", mode="before")
    @classmethod
    def expand_path(cls, v: Path | str) -> Path:
        return Path(v).expanduser().resolve()


class AudioConfig(BaseModel):
    """Audio pre-processing parameters."""

    model_config = ConfigDict(extra="allow")

    noise_reduction_strength: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="prop_decrease for noisereduce (0 = no reduction, 1 = full). 0.3 preserves natural speech quality.",
    )
    silence_threshold_db: float = Field(
        default=-40.0,
        description="dB level below which audio is considered silent.",
    )
    silence_min_duration_s: float = Field(
        default=3.0,
        gt=0.0,
        description="Minimum silence duration (seconds) to trigger a cut.",
    )
    padding_ms: int = Field(
        default=500,
        ge=0,
        description="Milliseconds of padding before/after each speech segment.",
    )


class TranscriptionConfig(BaseModel):
    """Transcription: default pipeline is ElevenLabs Scribe + grammar. WhisperX fields are kept for optional use."""

    model_config = ConfigDict(extra="allow")

    language: str = Field(
        default="hr",
        description="Language code for ElevenLabs and (if used) WhisperX.",
    )

    elevenlabs_model_id: str = Field(
        default="scribe_v2",
        description="ElevenLabs speech-to-text model id (e.g. scribe_v2).",
    )
    elevenlabs_tag_audio_events: bool = Field(
        default=False,
        description="If True, include (laughter) etc. in ElevenLabs output.",
    )
    grammar_max_passes: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max iterative Gemini grammar passes after ElevenLabs.",
    )

    # WhisperX — not used by CLI; kept for experiments or future use
    model_size: str = Field(
        default="small",
        description="Whisper model size (WhisperX only): tiny, base, small, medium, large-v3.",
    )
    device: str = Field(
        default="cpu",
        description="Compute device for WhisperX: cpu or cuda. MPS not supported.",
    )
    batch_size: int = Field(
        default=16,
        gt=0,
        description="Batch size for WhisperX transcription.",
    )
    compute_type: str = Field(
        default="int8",
        description="Quantization type for WhisperX: float16, float32, int8.",
    )


class DuplicateDetectionConfig(BaseModel):
    """Duplicate detection thresholds and behaviour."""

    model_config = ConfigDict(extra="allow")

    window_size: int = Field(
        default=5,
        ge=1,
        description="Lookahead window: each sentence compared against the next N sentences.",
    )

    lexical_definite: float = Field(
        default=85.0,
        ge=0.0,
        le=100.0,
        description="Lexical score (0-100) at or above which a pair is an automatic duplicate.",
    )
    lexical_maybe: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description="Lexical score (0-100) at or above which the pair advances to semantic tier.",
    )

    semantic_definite: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Cosine similarity at or above which a pair is an automatic duplicate.",
    )
    semantic_maybe: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Cosine similarity at or above which the pair advances to Gemini tier.",
    )

    gemini_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum Gemini confidence to accept a duplicate verdict.",
    )


class Settings(BaseSettings):
    """Root settings object. Nested sections added as phases land. Loaded from Python only (no env / dotenv)."""

    model_config = SettingsConfigDict(extra="allow")

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    duplicate_detection: DuplicateDetectionConfig = Field(default_factory=DuplicateDetectionConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def load_settings_from_py_file(path: Path) -> Settings:
    """Load a `Settings` instance from a Python file (must define `settings`)."""
    spec = importlib.util.spec_from_file_location("user_pipeline_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "settings"):
        raise ValueError(
            f"Config file {path} must define a top-level variable named `settings` (Settings instance)."
        )
    user_settings = module.settings
    if not isinstance(user_settings, Settings):
        raise TypeError(
            f"`settings` in {path} must be an instance of ai_video_editor.config.Settings, got {type(user_settings)}"
        )
    return user_settings


def get_settings(*, config_path: Path | None = None) -> Settings:
    if config_path is None:
        return Settings()
    return load_settings_from_py_file(config_path)
