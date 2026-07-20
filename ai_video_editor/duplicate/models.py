from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

class FlagReason(str, Enum):
    DUPLICATE = "duplicate"
    FALSE_START = "false_start"
    FILLER = "filler"
    STUTTER = "stutter"
    ASIDE = "aside"


class WordTrim(BaseModel):
    """A sub-sentence time range to cut (word-level precision)."""
    start: float = Field(..., description="Start time of the words to cut")
    end: float = Field(..., description="End time of the words to cut")


class DuplicateFlag(BaseModel):
    """A sentence flagged for removal."""
    idx: int
    reason: FlagReason
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str = ""
    word_trims: list[WordTrim] = Field(
        default_factory=list,
        description="Sub-sentence time ranges to cut instead of the whole sentence. "
        "If non-empty, only these ranges are cut; the rest of the sentence is kept.",
    )
