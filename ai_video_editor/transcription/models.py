from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, computed_field


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


class Transcript(BaseModel):
    sentences: list[Sentence]
    source_video: str
    language: str
    model_size: str
    created_at: str = ""

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
