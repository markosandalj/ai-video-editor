from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SimilarityScore(BaseModel):
    """Raw similarity scores between a pair of sentences."""
    idx_a: int
    idx_b: int
    lexical_ratio: float | None = None
    lexical_token_sort: float | None = None
    semantic_cosine: float | None = None
    gemini_is_duplicate: bool | None = None
    gemini_confidence: float | None = None


class FlagReason(str, Enum):
    DUPLICATE = "duplicate"
    FALSE_START = "false_start"
    FILLER = "filler"


class DuplicatePair(BaseModel):
    """A confirmed pair of duplicate sentences."""
    idx_keep: int = Field(..., description="Index of the sentence to keep (later take)")
    idx_cut: int = Field(..., description="Index of the sentence to cut (earlier take)")
    score: SimilarityScore
    tier: Literal["lexical", "semantic", "gemini"]


class DuplicateFlag(BaseModel):
    """A sentence flagged for removal."""
    idx: int
    reason: FlagReason
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    related_pair: DuplicatePair | None = None
    note: str = ""
