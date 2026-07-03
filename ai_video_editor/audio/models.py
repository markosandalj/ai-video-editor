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


class DisruptionRegion(BaseModel):
    """A short, loud non-speech burst inside a pause — a cough, throat-clear,
    mic bump, door, etc. These are the acoustic cues a human editor uses to spot
    flubbed takes that the transcript alone cannot reveal.

    ``source`` is ``"acoustic"`` for energy-detected bursts or ``"stt_event"`` for
    a burst the speech-to-text engine explicitly tagged (e.g. ``(cough)``)."""

    start: float
    end: float
    peak_db: float
    floor_db: float
    source: str = "acoustic"
    label: str = ""

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
