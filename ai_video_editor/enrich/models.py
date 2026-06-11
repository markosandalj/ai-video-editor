from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


SCHEMA_VERSION = "enrichment.v1"

# Default status thresholds (locked in Phase 5 grilling, 2026-06-10).
DEFAULT_GREEN_THRESHOLD = 80.0
DEFAULT_RESTORE_THRESHOLD = 60.0


class EnrichmentTag(str, Enum):
    """Closed taxonomy of per-chunk labels."""

    VERBATIM_CLEAN = "verbatim_clean"
    MINOR_DISFLUENCY = "minor_disfluency"
    FILLER_PHRASE = "filler_phrase"
    REDUNDANT_EXPLANATION = "redundant_explanation"
    OFF_TOPIC_ASIDE = "off_topic_aside"
    TECHNICAL_TERM_CHECK = "technical_term_check"
    LOW_AUDIO_CONFIDENCE = "low_audio_confidence"
    REPETITION_RESIDUE = "repetition_residue"
    INCOMPLETE_THOUGHT = "incomplete_thought"
    NEEDS_REVIEW = "needs_review"


class EnrichmentStatus(str, Enum):
    """Derived signal shown to the editor."""

    GREEN = "green"  # kept and safe
    YELLOW = "yellow"  # kept, but worth a human look
    RED = "red"  # cut, model agrees
    RESTORE = "restore"  # cut, but model thinks it may belong


def derive_status(
    keep_confidence: float,
    is_cut: bool,
    *,
    green_threshold: float = DEFAULT_GREEN_THRESHOLD,
    restore_threshold: float = DEFAULT_RESTORE_THRESHOLD,
) -> EnrichmentStatus:
    """Deterministically map a keep-confidence score onto a status tier.

    The LLM provides ``keep_confidence``; the status is computed here so the
    thresholds stay tunable and predictable.
    """
    if is_cut:
        return (
            EnrichmentStatus.RESTORE
            if keep_confidence >= restore_threshold
            else EnrichmentStatus.RED
        )
    return (
        EnrichmentStatus.GREEN
        if keep_confidence >= green_threshold
        else EnrichmentStatus.YELLOW
    )


def reconcile_word_salience(
    salience: list[float],
    word_count: int,
    fallback: float,
) -> list[float]:
    """Coerce raw per-word salience into a list aligned to the sentence words.

    Values are clamped to 0-100. Length is fixed to ``word_count`` by padding
    with ``fallback`` (too short / empty) or truncating (too long). Never raises.
    """
    if word_count <= 0:
        return []
    cleaned = [max(0.0, min(100.0, float(value))) for value in salience]
    if len(cleaned) == word_count:
        return cleaned
    if not cleaned:
        return [fallback] * word_count
    if len(cleaned) > word_count:
        return cleaned[:word_count]
    return cleaned + [fallback] * (word_count - len(cleaned))


class SentenceEnrichment(BaseModel):
    """Per-sentence metadata produced by the enrichment pass."""

    sentence_idx: int
    keep_confidence: float = Field(ge=0.0, le=100.0)
    status: EnrichmentStatus
    tags: list[EnrichmentTag] = Field(default_factory=list)
    rationale: str = ""
    word_salience: list[float] = Field(default_factory=list)


class EnrichmentResult(BaseModel):
    """Full enrichment sidecar for one video."""

    schema_version: str = SCHEMA_VERSION
    source_video: str
    sentences: list[SentenceEnrichment] = Field(default_factory=list)
    created_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def by_index(self) -> dict[int, SentenceEnrichment]:
        return {item.sentence_idx: item for item in self.sentences}
