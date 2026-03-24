"""Unit tests for the QA module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ai_video_editor.qa.ground_truth import compare_transcripts
from ai_video_editor.qa.models import (
    ContinuityResult,
    QAIssue,
    QAReport,
    SentenceMatch,
    Severity,
    SpliceAnalysisResult,
    SpectrogramComparisonResult,
    TemporalComparisonResult,
    TranscriptComparisonResult,
)
from ai_video_editor.qa.regression import (
    PairScore,
    RegressionEntry,
    check_regression,
    discover_pairs,
    record_scores,
)
from ai_video_editor.qa.report import generate_report
from ai_video_editor.transcription.models import Sentence, Word


def _make_sentence(text: str, start: float = 0.0, end: float = 1.0) -> Sentence:
    words = [Word(text=w, start=start, end=end) for w in text.split()]
    return Sentence(words=words, text=text, start=start, end=end)


class TestTranscriptComparison:
    def test_perfect_match(self):
        sentences = [_make_sentence("Hello world."), _make_sentence("How are you?")]
        result = compare_transcripts(sentences, sentences)
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1 == 1.0
        assert result.matched == 2

    def test_no_match(self):
        pipeline = [_make_sentence("Ovo je test.")]
        gt = [_make_sentence("Sasvim drugačija rečenica.")]
        result = compare_transcripts(pipeline, gt)
        assert result.matched == 0
        assert result.precision == 0.0
        assert result.recall == 0.0

    def test_partial_match(self):
        pipeline = [
            _make_sentence("Hello world."),
            _make_sentence("Extra sentence here."),
        ]
        gt = [
            _make_sentence("Hello world."),
            _make_sentence("Goodbye world."),
        ]
        result = compare_transcripts(pipeline, gt)
        assert result.matched == 1
        assert result.pipeline_sentences == 2
        assert result.ground_truth_sentences == 2
        assert result.precision == 0.5
        assert result.recall == 0.5

    def test_fuzzy_match(self):
        pipeline = [_make_sentence("Danas je lijep dan.")]
        gt = [_make_sentence("Danas je lijepi dan.")]
        result = compare_transcripts(pipeline, gt)
        assert result.matched == 1

    def test_empty_inputs(self):
        result = compare_transcripts([], [])
        assert result.f1 == 0.0
        assert result.matched == 0


class TestTranscriptComparisonResult:
    def test_computed_fields(self):
        r = TranscriptComparisonResult(
            pipeline_sentences=10, ground_truth_sentences=8, matched=6
        )
        assert r.precision == pytest.approx(0.6)
        assert r.recall == pytest.approx(0.75)
        assert r.f1 == pytest.approx(2 * 0.6 * 0.75 / (0.6 + 0.75), abs=0.001)

    def test_zero_division(self):
        r = TranscriptComparisonResult()
        assert r.precision == 0.0
        assert r.recall == 0.0
        assert r.f1 == 0.0


class TestTemporalComparisonResult:
    def test_fields(self):
        r = TemporalComparisonResult(
            pipeline_duration=200.0,
            ground_truth_duration=190.0,
            duration_delta=10.0,
            mean_offset=2.0,
            temporal_score=0.85,
        )
        assert r.duration_delta == 10.0
        assert r.temporal_score == 0.85


class TestSpliceAnalysisResult:
    def test_no_harsh_splices(self):
        r = SpliceAnalysisResult(total_splices=5, harsh_splices=0)
        assert r.harsh_splices == 0

    def test_with_details(self):
        r = SpliceAnalysisResult(
            total_splices=3,
            harsh_splices=1,
            max_amplitude_delta=0.45,
            splice_details=[{"time": 5.0, "delta": 0.45, "harsh": True}],
        )
        assert r.harsh_splices == 1


class TestQAReport:
    def test_overall_score_single(self):
        report = QAReport(
            video_name="test",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=8
            ),
        )
        assert report.overall_score == pytest.approx(report.transcript_comparison.f1)

    def test_overall_score_multiple(self):
        report = QAReport(
            video_name="test",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=10
            ),
            splice_analysis=SpliceAnalysisResult(total_splices=5, harsh_splices=0),
        )
        assert report.overall_score == 1.0

    def test_overall_passed(self):
        report = QAReport(
            video_name="test",
            issues=[QAIssue(check="x", severity=Severity.WARNING, message="warn")],
            overall_passed=True,
        )
        assert report.overall_passed is True

    def test_empty_report(self):
        report = QAReport(video_name="empty")
        assert report.overall_score == 0.0


class TestHTMLReport:
    def test_generates_valid_html(self):
        report = QAReport(
            video_name="test-video",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=8, matched=7
            ),
            issues=[
                QAIssue(check="test_check", severity=Severity.WARNING, message="Test warning"),
            ],
        )
        html = generate_report(report)
        assert "<html>" in html
        assert "test-video" in html
        assert "Test warning" in html
        assert "Precision" in html


class TestDiscoverPairs:
    def test_finds_pairs(self, tmp_path):
        (tmp_path / "test-1-raw.mp4").touch()
        (tmp_path / "test-1-edited.mp4").touch()
        (tmp_path / "test-2-raw.mp4").touch()
        (tmp_path / "test-2-edited.mp4").touch()
        (tmp_path / "orphan-raw.mp4").touch()

        pairs = discover_pairs(tmp_path)
        assert len(pairs) == 2
        assert pairs[0][0] == "test-1"
        assert pairs[1][0] == "test-2"

    def test_no_pairs(self, tmp_path):
        (tmp_path / "video.mp4").touch()
        pairs = discover_pairs(tmp_path)
        assert len(pairs) == 0


class TestRegression:
    def test_record_and_check(self, tmp_path):
        history_path = tmp_path / "scores.json"

        report1 = QAReport(
            video_name="v1",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=9
            ),
        )
        entry1 = record_scores([report1], history_path)
        assert entry1.aggregate_score > 0

        warnings1 = check_regression(entry1, history_path)
        assert len(warnings1) == 0

        report2 = QAReport(
            video_name="v1",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=5
            ),
        )
        entry2 = record_scores([report2], history_path)
        warnings2 = check_regression(entry2, history_path)
        assert len(warnings2) > 0
        assert "REGRESSION" in warnings2[0]

    def test_no_regression_on_improvement(self, tmp_path):
        history_path = tmp_path / "scores.json"

        report1 = QAReport(
            video_name="v1",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=5
            ),
        )
        record_scores([report1], history_path)

        report2 = QAReport(
            video_name="v1",
            transcript_comparison=TranscriptComparisonResult(
                pipeline_sentences=10, ground_truth_sentences=10, matched=9
            ),
        )
        entry2 = record_scores([report2], history_path)
        warnings = check_regression(entry2, history_path)
        assert len(warnings) == 0
