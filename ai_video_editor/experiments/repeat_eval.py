"""Evaluate explicit source-timeline repeat cases against saved EDLs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.transcription.models import Transcript, Word


class RepeatCase(BaseModel):
    fixture: str
    sentence_index: int = Field(ge=0)
    start_word: int = Field(ge=0)
    end_word: int = Field(gt=0, description="Exclusive word index")
    expected: Literal["cut", "keep"]
    preserve_sentence_remainder: bool = False
    label: str = ""


class RepeatCaseManifest(BaseModel):
    cases: list[RepeatCase] = Field(default_factory=list)


@dataclass
class RepeatCaseResult:
    case: RepeatCase
    cut_words: int
    total_words: int
    passed: bool
    remainder_preserved: bool = True


@dataclass
class RepeatCaseSummary:
    results: list[RepeatCaseResult] = field(default_factory=list)

    @property
    def positive_cases(self) -> int:
        return sum(result.case.expected == "cut" for result in self.results)

    @property
    def positive_passed(self) -> int:
        return sum(
            result.case.expected == "cut" and result.passed
            for result in self.results
        )

    @property
    def control_cases(self) -> int:
        return sum(result.case.expected == "keep" for result in self.results)

    @property
    def control_passed(self) -> int:
        return sum(
            result.case.expected == "keep" and result.passed
            for result in self.results
        )


def _word_is_cut(word: Word, edl: EditDecisionList) -> bool:
    midpoint = (word.start + word.end) / 2.0
    for decision in edl.decisions:
        if decision.start <= midpoint <= decision.end:
            return decision.action == EditAction.CUT
    return True


def evaluate_repeat_cases(
    fixtures_dir: Path,
    edls_dir: Path,
    manifest_path: Path,
    *,
    fixture_names: set[str] | None = None,
) -> RepeatCaseSummary:
    """Score named word spans directly, bypassing ambiguous transcript alignment."""
    manifest = RepeatCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    transcripts: dict[str, Transcript] = {}
    edls: dict[str, EditDecisionList] = {}
    results: list[RepeatCaseResult] = []

    for case in manifest.cases:
        if fixture_names is not None and case.fixture not in fixture_names:
            continue
        transcript = transcripts.setdefault(
            case.fixture,
            Transcript.model_validate_json(
                (fixtures_dir / f"{case.fixture}-raw.transcript.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        edl = edls.setdefault(
            case.fixture,
            EditDecisionList.model_validate_json(
                (edls_dir / f"{case.fixture}.edl.json").read_text(encoding="utf-8")
            ),
        )
        if case.sentence_index >= len(transcript.sentences):
            raise ValueError(
                f"{case.fixture}: sentence index {case.sentence_index} is out of range"
            )
        sentence = transcript.sentences[case.sentence_index]
        if case.end_word > len(sentence.words) or case.start_word >= case.end_word:
            raise ValueError(
                f"{case.fixture}[{case.sentence_index}]: invalid word range "
                f"{case.start_word}:{case.end_word}"
            )

        target_indices = set(range(case.start_word, case.end_word))
        target_cut = sum(
            _word_is_cut(sentence.words[index], edl) for index in target_indices
        )
        target_total = len(target_indices)
        remainder_preserved = all(
            not _word_is_cut(word, edl)
            for index, word in enumerate(sentence.words)
            if index not in target_indices
        )
        expected_span_passed = (
            target_cut == target_total if case.expected == "cut" else target_cut == 0
        )
        passed = expected_span_passed and (
            remainder_preserved if case.preserve_sentence_remainder else True
        )
        results.append(RepeatCaseResult(
            case=case,
            cut_words=target_cut,
            total_words=target_total,
            passed=passed,
            remainder_preserved=remainder_preserved,
        ))

    return RepeatCaseSummary(results=results)


def format_repeat_case_report(summary: RepeatCaseSummary) -> str:
    lines = [
        "## Explicit local-repeat cases",
        "",
        "| fixture | source span | expected | cut words | remainder kept | result |",
        "|---|---|---|---:|---|---|",
    ]
    for result in summary.results:
        case = result.case
        lines.append(
            f"| {case.fixture} | {case.sentence_index}:{case.start_word}-{case.end_word} "
            f"{case.label} | {case.expected} | {result.cut_words}/{result.total_words} | "
            f"{'yes' if result.remainder_preserved else 'no'} | "
            f"{'PASS' if result.passed else 'FAIL'} |"
        )
    lines += [
        "",
        f"Positive repeat cases: {summary.positive_passed}/{summary.positive_cases}",
        f"Intentional-repeat controls: {summary.control_passed}/{summary.control_cases}",
    ]
    return "\n".join(lines)
