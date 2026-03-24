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


class Settings(BaseSettings):
    """Root settings object. Nested sections added as phases land. Loaded from Python only (no env / dotenv)."""

    model_config = SettingsConfigDict(extra="allow")

    general: GeneralConfig = Field(default_factory=GeneralConfig)

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
