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
        """Weighted average: word F1 50%, temporal 30%, continuity 20%."""
        components: list[tuple[float, float]] = []
        if self.word_level_comparison:
            components.append((self.word_level_comparison.f1, 0.50))
        if self.temporal_comparison:
            components.append((self.temporal_comparison.temporal_score, 0.30))
        if self.continuity:
            components.append((self.continuity.alignment_score, 0.20))
        if not components:
            return 0.0
        total_weight = sum(w for _, w in components)
        return sum(s * w for s, w in components) / total_weight
