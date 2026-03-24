from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field, computed_field

from ai_video_editor.audio.models import KeepRegion
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.transcription.models import Sentence, Transcript


class EditAction(str, Enum):
    KEEP = "keep"
    CUT = "cut"


class EditReason(str, Enum):
    SPEECH = "speech"
    SILENCE = "silence"
    DUPLICATE = "duplicate"
    FALSE_START = "false_start"


class EditDecision(BaseModel):
    """A single edit segment with start/end times and action."""
    start: float
    end: float
    action: EditAction
    reason: EditReason
    confidence: float = 1.0
    note: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return self.end - self.start


class EditDecisionList(BaseModel):
    """Ordered, non-overlapping list of edit decisions for a video."""
    decisions: list[EditDecision] = Field(default_factory=list)
    source_video: str = ""
    total_duration: float = 0.0
    created_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keep_duration(self) -> float:
        return sum(d.duration for d in self.decisions if d.action == EditAction.KEEP)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cut_duration(self) -> float:
        return sum(d.duration for d in self.decisions if d.action == EditAction.CUT)


def _flag_reason_to_edit_reason(reason: FlagReason) -> EditReason:
    return {
        FlagReason.DUPLICATE: EditReason.DUPLICATE,
        FlagReason.FALSE_START: EditReason.FALSE_START,
        FlagReason.FILLER: EditReason.FALSE_START,
    }[reason]


def build_edl(
    transcript: Transcript,
    keep_regions: list[KeepRegion],
    duplicate_flags: list[DuplicateFlag],
) -> EditDecisionList:
    """
    Merge silence-based keep regions and duplicate flags into a single EDL.

    Algorithm:
    1. Start with keep_regions from Phase 1 (silence already removed).
    2. Within each keep region, remove sentence spans flagged as duplicates
       or false starts, splitting the keep region as necessary.
    3. Gaps between final keep segments become cut segments.
    """
    if not transcript.sentences:
        return EditDecisionList(source_video=transcript.source_video)

    total_dur = transcript.sentences[-1].end
    flagged: set[int] = {f.idx for f in duplicate_flags}
    flag_by_idx = {f.idx: f for f in duplicate_flags}

    keep_spans: list[tuple[float, float]] = []

    if not keep_regions:
        keep_regions = [KeepRegion(start=0.0, end=total_dur)]

    for region in keep_regions:
        sentences_in_region = [
            (i, s) for i, s in enumerate(transcript.sentences)
            if s.start >= region.start and s.end <= region.end
        ]

        current_start: float | None = None
        current_end: float | None = None

        for idx, sent in sentences_in_region:
            if idx in flagged:
                if current_start is not None and current_end is not None:
                    keep_spans.append((current_start, current_end))
                    current_start = None
                    current_end = None
                continue

            if current_start is None:
                current_start = sent.start
            current_end = sent.end

        if current_start is not None and current_end is not None:
            keep_spans.append((current_start, current_end))

    keep_spans.sort()
    merged: list[tuple[float, float]] = []
    for start, end in keep_spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    decisions: list[EditDecision] = []
    prev_end = 0.0

    for start, end in merged:
        if start > prev_end + 0.01:
            cut_reason = _classify_gap(prev_end, start, transcript.sentences, flag_by_idx)
            decisions.append(EditDecision(
                start=prev_end,
                end=start,
                action=EditAction.CUT,
                reason=cut_reason,
            ))

        decisions.append(EditDecision(
            start=start,
            end=end,
            action=EditAction.KEEP,
            reason=EditReason.SPEECH,
        ))
        prev_end = end

    if prev_end < total_dur - 0.01:
        decisions.append(EditDecision(
            start=prev_end,
            end=total_dur,
            action=EditAction.CUT,
            reason=EditReason.SILENCE,
        ))

    edl = EditDecisionList(
        decisions=decisions,
        source_video=transcript.source_video,
        total_duration=total_dur,
    )

    logger.info(
        "EDL built: {} decisions, keep={:.1f}s, cut={:.1f}s (total={:.1f}s)",
        len(decisions),
        edl.keep_duration,
        edl.cut_duration,
        total_dur,
    )
    return edl


def _classify_gap(
    gap_start: float,
    gap_end: float,
    sentences: list[Sentence],
    flag_by_idx: dict[int, DuplicateFlag],
) -> EditReason:
    """Determine why a gap exists — silence, duplicate, or false start."""
    for idx, sent in enumerate(sentences):
        if sent.start >= gap_start and sent.end <= gap_end and idx in flag_by_idx:
            flag = flag_by_idx[idx]
            return _flag_reason_to_edit_reason(flag.reason)
    return EditReason.SILENCE
