from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, computed_field


class Word(BaseModel):
    text: str
    start: float
    end: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class Sentence(BaseModel):
    words: list[Word]
    text: str
    start: float
    end: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class AudioEvent(BaseModel):
    """A non-speech event the STT engine tagged (e.g. ``(cough)``, ``(laughter)``).

    Kept as a separate stream rather than inlined into sentence text so it never
    pollutes the transcript, the grammar pass, QA, or the diff view — but is still
    available to the edit-decision layer as an acoustic cue."""

    text: str
    start: float
    end: float


class Transcript(BaseModel):
    sentences: list[Sentence]
    source_video: str
    language: str
    model_size: str
    created_at: str = ""
    events: list[AudioEvent] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_duration(self) -> float:
        if not self.sentences:
            return 0.0
        return self.sentences[-1].end - self.sentences[0].start

    @computed_field  # type: ignore[prop-decorator]
    @property
    def word_count(self) -> int:
        return sum(len(s.words) for s in self.sentences)
