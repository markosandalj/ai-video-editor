from __future__ import annotations

from pydantic import BaseModel, computed_field


class SilenceRegion(BaseModel):
    start: float
    end: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class KeepRegion(BaseModel):
    start: float
    end: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class AudioMeta(BaseModel):
    """Metadata about an extracted audio file."""

    source_video: str
    sample_rate: int
    channels: int
    duration_s: float
    path: str
