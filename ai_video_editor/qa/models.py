from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QAIssue(BaseModel):
    check: str
    severity: Severity
    message: str
    details: dict = Field(default_factory=dict)


class SentenceMatch(BaseModel):
    """A matched sentence pair between pipeline and ground truth."""
    pipeline_text: str
    ground_truth_text: str
    similarity: float
    pipeline_start: float = 0.0
    pipeline_end: float = 0.0
    gt_start: float = 0.0
    gt_end: float = 0.0


class TranscriptComparisonResult(BaseModel):
    """Result of comparing pipeline transcript vs human-edited ground truth."""
    pipeline_sentences: int = 0
    ground_truth_sentences: int = 0
    matched: int = 0
    pipeline_only: list[str] = Field(default_factory=list)
    ground_truth_only: list[str] = Field(default_factory=list)
    matches: list[SentenceMatch] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def precision(self) -> float:
        """Of our kept sentences, how many match the human's."""
        return self.matched / self.pipeline_sentences if self.pipeline_sentences else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float:
        """Of the human's kept sentences, how many did we also keep."""
        return self.matched / self.ground_truth_sentences if self.ground_truth_sentences else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


class WordLevelComparisonResult(BaseModel):
    """Result of word-level LCS comparison (immune to sentence boundaries)."""
    pipeline_words: int = 0
    ground_truth_words: int = 0
    lcs_length: int = 0
    extra_words: list[str] = Field(default_factory=list)
    missing_words: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def precision(self) -> float:
        """Of pipeline words, how many are in the LCS."""
        return self.lcs_length / self.pipeline_words if self.pipeline_words else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float:
        """Of ground truth words, how many are in the LCS."""
        return self.lcs_length / self.ground_truth_words if self.ground_truth_words else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


class CutDecisionResult(BaseModel):
    """Sentence-level cut/keep decisions vs the human edit (positive class = CUT).

    Word-overlap metrics normalise by total content, so on a video that needs
    only a couple of cuts, missing every one of them still scores ~95%. These
    counts are normalised by the number of *edit decisions* instead: miss all
    needed cuts and ``cut_recall`` is 0, no matter how much text overlaps.
    """
    true_cuts: int = 0    # pipeline cut, human cut
    overcuts: int = 0     # pipeline cut, human kept
    missed_cuts: int = 0  # pipeline kept, human cut
    true_keeps: int = 0   # pipeline kept, human kept
    take_disagreements: int = 0  # both kept one copy, but not the same take
    wrong_cut_by_reason: dict[str, int] = Field(default_factory=dict)
    right_cut_by_reason: dict[str, int] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needed_cuts(self) -> int:
        """Cuts the human made."""
        return self.true_cuts + self.missed_cuts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def made_cuts(self) -> int:
        """Cuts the pipeline made."""
        return self.true_cuts + self.overcuts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cut_recall(self) -> float:
        """Of the cuts the human made, how many we also made. 1.0 when none were needed."""
        return self.true_cuts / self.needed_cuts if self.needed_cuts else 1.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cut_precision(self) -> float:
        """Of the cuts we made, how many the human also made. 1.0 when we made none."""
        return self.true_cuts / self.made_cuts if self.made_cuts else 1.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cut_f1(self) -> float:
        p, r = self.cut_precision, self.cut_recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def miss_rate(self) -> float:
        """Share of needed cuts we failed to make. 0.0 when none were needed."""
        return self.missed_cuts / self.needed_cuts if self.needed_cuts else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overcut_rate(self) -> float:
        """Share of our cuts that removed content the human kept."""
        return self.overcuts / self.made_cuts if self.made_cuts else 0.0


class TemporalComparisonResult(BaseModel):
    """Result of comparing timing between pipeline and ground truth."""
    pipeline_duration: float = 0.0
    ground_truth_duration: float = 0.0
    duration_delta: float = 0.0
    anchor_offsets: list[float] = Field(default_factory=list)
    mean_offset: float = 0.0
    temporal_score: float = 0.0


class SpliceAnalysisResult(BaseModel):
    """Result of checking audio splice quality."""
    total_splices: int = 0
    harsh_splices: int = 0
    max_amplitude_delta: float = 0.0
    splice_details: list[dict] = Field(default_factory=list)


class SpectrogramComparisonResult(BaseModel):
    """Result of comparing spectrograms."""
    similarity_score: float = 0.0
    passed: bool = True


class ContinuityResult(BaseModel):
    """Result of transcript continuity verification."""
    expected_sentences: int = 0
    found_sentences: int = 0
    missing_sentences: list[str] = Field(default_factory=list)
    alignment_score: float = 0.0


class QAReport(BaseModel):
    """Full QA report for a single video."""
    video_name: str
    created_at: str = ""
    transcript_comparison: TranscriptComparisonResult | None = None
    word_level_comparison: WordLevelComparisonResult | None = None
    cut_decisions: CutDecisionResult | None = None
    temporal_comparison: TemporalComparisonResult | None = None
    splice_analysis: SpliceAnalysisResult | None = None
    spectrogram_comparison: SpectrogramComparisonResult | None = None
    continuity: ContinuityResult | None = None
    issues: list[QAIssue] = Field(default_factory=list)
    overall_passed: bool = True

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_score(self) -> float:
        """Weighted average: cut F1 40%, word F1 30%, temporal 20%, continuity 10%.

        Cut F1 carries the largest weight because it is the only component
        normalised by edit decisions rather than total content — without it, a
        video needing two cuts where both are missed still scores ~95%.
        """
        components: list[tuple[float, float]] = []
        if self.cut_decisions:
            components.append((self.cut_decisions.cut_f1, 0.40))
        if self.word_level_comparison:
            components.append((self.word_level_comparison.f1, 0.30))
        if self.temporal_comparison:
            components.append((self.temporal_comparison.temporal_score, 0.20))
        if self.continuity:
            components.append((self.continuity.alignment_score, 0.10))
        if not components:
            return 0.0
        total_weight = sum(w for _, w in components)
        return sum(s * w for s, w in components) / total_weight
