from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field, computed_field

from ai_video_editor.duplicate.edl import EditAction, EditDecision


SCHEMA_VERSION = "review.v3"


class CutRange(BaseModel):
    """A free-form span of source video (seconds) removed from the edit."""

    start: float = Field(ge=0.0)
    end: float


class ReviewVideoMetadata(BaseModel):
    id: str
    source_name: str
    source_path: str
    edl_path: str
    review_edl_path: str
    duration: float
    keep_duration: float
    cut_duration: float
    created_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


class ReviewVideoSummary(BaseModel):
    id: str
    source_name: str
    source_path: str
    has_review: bool = False
    duration: float = 0.0


class ReviewTimelineSegment(BaseModel):
    idx: int
    start: float
    end: float
    action: EditAction
    reason: str
    confidence: float = 1.0
    note: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start

    @classmethod
    def from_decision(cls, idx: int, decision: EditDecision) -> "ReviewTimelineSegment":
        return cls(
            idx=idx,
            start=decision.start,
            end=decision.end,
            action=decision.action,
            reason=decision.reason.value,
            confidence=decision.confidence,
            note=decision.note,
        )


class ReviewWord(BaseModel):
    """A single transcript word with the AI decision and a keep-likelihood score."""

    idx: int
    sentence_idx: int
    start: float
    end: float
    text: str
    ai_kept: bool
    kept: bool
    reason: str = ""
    confidence: float = 1.0
    keep_score: float = Field(default=1.0, ge=0.0, le=1.0)
    # Shared acoustic split points. Older payloads omit these and remain valid.
    cut_in: float | None = None
    cut_out: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class ReviewSentence(BaseModel):
    idx: int
    start: float
    end: float
    text: str
    action: EditAction
    original_action: EditAction
    reason: str
    confidence: float = 1.0
    keep_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str = ""
    # Enrichment metadata (phase 5). Defaults keep older payloads valid.
    status: str = ""
    tags: list[str] = Field(default_factory=list)
    keep_confidence: float = Field(default=100.0, ge=0.0, le=100.0)
    rationale: str = ""
    words: list[ReviewWord] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class ReviewPayload(BaseModel):
    schema_version: str = SCHEMA_VERSION
    video: ReviewVideoMetadata
    segments: list[ReviewTimelineSegment]
    sentences: list[ReviewSentence]
    # Canonical current cut state as free-form source-time ranges. Derived from
    # the reviewed sidecar when present, otherwise from the AI EDL. The timeline
    # and transcript both read/write this.
    cut_ranges: list[CutRange] = Field(default_factory=list)


class ReviewSaveRequest(BaseModel):
    """Reviewer decisions to persist.

    The canonical form is ``cut_ranges`` (free-form source-time spans). Legacy
    clients may still send ``cut_words`` (word indices); it is used only when
    ``cut_ranges`` is omitted (``None``). An explicit empty ``cut_ranges`` list
    means "no cuts" (restore everything), which is distinct from omitting it.
    """

    cut_ranges: list[CutRange] | None = None
    cut_words: list[int] = Field(default_factory=list)


class ReviewSaveResponse(BaseModel):
    review_edl_path: str
    keep_duration: float
    cut_duration: float
    decisions: int
