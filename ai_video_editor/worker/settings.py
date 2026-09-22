from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_video_editor.worker.contracts import ResolvedRenderConfigV1


class WorkerSettings(BaseSettings):
    """Deployment-only worker configuration; none of it enters a job payload."""

    model_config = SettingsConfigDict(extra="ignore")

    api_token: str = Field(alias="AI_VIDEO_EDITOR_API_TOKEN", min_length=16)
    callback_token: str = Field(alias="GRADIVO_VIDEO_CALLBACK_TOKEN", min_length=16)
    callback_base_url: str = Field(alias="GRADIVO_VIDEO_CALLBACK_BASE_URL")
    state_db_path: Path = Field(alias="VIDEO_PROCESSING_STATE_DB_PATH")
    scratch_dir: Path = Field(
        default=Path("/tmp/ai-video-worker/scratch"),
        alias="VIDEO_PROCESSING_SCRATCH_DIR",
    )
    log_dir: Path = Field(
        default=Path("/tmp/ai-video-worker/logs"),
        alias="VIDEO_PROCESSING_LOG_DIR",
    )
    max_number_of_jobs: Literal[1] = Field(default=1, alias="MAX_NUMBER_OF_JOBS")
    analysis_timeout_seconds: float = Field(
        default=4 * 60 * 60,
        gt=0,
        allow_inf_nan=False,
        alias="VIDEO_PROCESSING_ANALYSIS_TIMEOUT_SECONDS",
    )
    render_timeout_seconds: float = Field(
        default=4 * 60 * 60,
        gt=0,
        allow_inf_nan=False,
        alias="VIDEO_PROCESSING_RENDER_TIMEOUT_SECONDS",
    )
    callback_retry_base_seconds: float = Field(default=1.0, gt=0)
    callback_retry_max_seconds: float = Field(default=300.0, gt=0)
    google_drive_client_id: str = Field(default="", alias="GOOGLE_DRIVE_CLIENT_ID")
    google_drive_client_secret: str = Field(
        default="",
        alias="GOOGLE_DRIVE_CLIENT_SECRET",
    )
    google_drive_refresh_token: str = Field(
        default="",
        alias="GOOGLE_DRIVE_REFRESH_TOKEN",
    )
    s3_endpoint_url: str = Field(default="", alias="VIDEO_PROCESSING_S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", alias="VIDEO_PROCESSING_S3_BUCKET")
    s3_access_key_id: str = Field(
        default="",
        alias="VIDEO_PROCESSING_S3_ACCESS_KEY_ID",
    )
    s3_secret_access_key: str = Field(
        default="",
        alias="VIDEO_PROCESSING_S3_SECRET_ACCESS_KEY",
    )
    render_codec: str = Field(default="libx264", alias="VIDEO_PROCESSING_RENDER_CODEC")
    render_crf: int = Field(
        default=28, ge=0, le=51, alias="VIDEO_PROCESSING_RENDER_CRF"
    )
    render_preset: str = Field(
        default="ultrafast", alias="VIDEO_PROCESSING_RENDER_PRESET"
    )
    render_crossfade_ms: int = Field(
        default=30,
        ge=0,
        le=500,
        alias="VIDEO_PROCESSING_RENDER_CROSSFADE_MS",
    )

    @field_validator("state_db_path", "scratch_dir", "log_dir", mode="before")
    @classmethod
    def expand_state_path(cls, value: Path | str) -> Path:
        return Path(value).expanduser().resolve()

    @field_validator("callback_base_url")
    @classmethod
    def validate_callback_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("callback base URL must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def require_independent_tokens(self) -> WorkerSettings:
        if self.api_token == self.callback_token:
            raise ValueError("worker API and Gradivo callback tokens must be different")
        return self

    def resolve_render_config(self) -> ResolvedRenderConfigV1:
        return ResolvedRenderConfigV1(
            schema="resolved_render_config.v1",
            render_profile="student_video.v1",
            codec=self.render_codec,
            crf=self.render_crf,
            preset=self.render_preset,
            crossfade_ms=self.render_crossfade_ms,
            output_suffix="-final",
            audio_codec="aac",
            audio_bitrate="192k",
            movflags="+faststart",
        )
