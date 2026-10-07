"""Content-preservation regressions at the proposal and combined-decision seams."""
from __future__ import annotations

import pytest
import json
from pathlib import Path

from ai_video_editor import decisions
from ai_video_editor.audio.models import DisruptionRegion, KeepRegion
from ai_video_editor.config.settings import SectionEditorConfig, Settings
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.duplicate.section_editor import SectionDeletion, SectionEdits, _deletion_to_flag
from ai_video_editor.duplicate.edl import build_edl
from ai_video_editor.duplicate.safeguards import protect_kept_spans
from ai_video_editor.transcription.models import Sentence, Transcript
from tests.test_section_editor import _sentence


def test_audio_pattern_alone_cannot_delete_a_correction(monkeypatch):
    sentences = [
        _sentence("Gustoća je količnik mase otopine sa volumenom otapala.", 130, 142.26),
        _sentence("Sa volumenom otopine.", 146.4, 148.44),
        _sentence("To znači da ako želimo dobiti volumen...", 148.76, 152.92),
    ]
    seen = {}

    def section_editor(_sentences, _cfg, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(decisions, "detect_section_edits", section_editor)
    monkeypatch.setattr(decisions, "detect_asides", lambda *args, **kwargs: [])
    flags = decisions.detect_all_flags(
        Transcript(sentences=sentences, source_video="case-8", language="hr", model_size="saved"),
        [], [DisruptionRegion(start=145, end=145.1, peak_db=-40, floor_db=-80)], Settings(),
    )

    assert flags == []
    assert [candidate.sentence_index for candidate in seen["audio_candidates"]] == [1]


@pytest.mark.parametrize("kept_index,kept_text", [
    (None, None), (1, None), (None, "Ispravan nastavak"),
    (-1, "Ispravan nastavak"), (5, "Ispravan nastavak"),
    (0, "Ovo je cijela ranija rečenica"), (1, "izmišljeni tekst"),
])
@pytest.mark.parametrize("kind", ["retake", "false_start"])
def test_content_deletion_requires_a_verifiable_later_replacement(kept_index, kept_text, kind):
    sentences = [
        _sentence("Ovo je cijela ranija rečenica", 0, 3),
        _sentence("Ispravan nastavak", 4, 6),
    ]
    proposal = SectionDeletion(
        sentence_index=0, verbatim_text=sentences[0].text, delete_type=kind,
        kept_index=kept_index, kept_verbatim_text=kept_text,
    )
    assert _deletion_to_flag(proposal, sentences, SectionEditorConfig()) is None


def test_ninety_percent_proposal_does_not_expand_to_unrequested_words():
    sentence = _sentence("uvod a b c d e f g h i", 0, 10)
    proposal = SectionDeletion(
        sentence_index=0, verbatim_text="a b c d e f g h i", delete_type="stutter",
    )
    flag = _deletion_to_flag(proposal, [sentence], SectionEditorConfig())
    assert flag is not None
    assert [(trim.start, trim.end) for trim in flag.word_trims] == [(1, 10)]


def test_non_contiguous_proposal_cannot_swallow_unique_content():
    sentence = _sentence("jedan dva VAŽAN UVOD tri četiri", 0, 6)
    proposal = SectionDeletion(
        sentence_index=0, verbatim_text="jedan dva tri četiri", delete_type="stutter",
    )
    assert _deletion_to_flag(proposal, [sentence], SectionEditorConfig()) is None


def _excerpt(number):
    data = json.loads((Path(__file__).parent / "data/edit_safety/gradivo-49913-excerpts.json").read_text())
    case = next(case for case in data["cases"] if case["number"] == number)
    return Transcript(
        sentences=[Sentence.model_validate(s) for s in case["sentences"]],
        source_video=f"case-{number}.mp4", language="hr", model_size="saved-projection",
    )


def _model_proposals(monkeypatch, proposals, prompts):
    from ai_video_editor.duplicate import section_editor

    class Structured:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SectionEdits(deletions=proposals)

    class Model:
        def with_structured_output(self, schema):
            assert schema is SectionEdits
            return Structured()

    monkeypatch.setattr(section_editor, "build_chat_model", lambda config: Model())


@pytest.mark.parametrize("conflicting_lane", ["section", "local_correction", "aside"])
def test_case_8_correction_survives_all_cutting_lanes(monkeypatch, conflicting_lane):
    from ai_video_editor.duplicate import section_editor
    transcript = _excerpt(8)
    sentences = transcript.sentences
    proposals = [
        SectionDeletion(sentence_index=0, verbatim_text="sa volumenom otapala.",
                        delete_type="retake", kept_index=1, kept_verbatim_text=sentences[1].text),
        SectionDeletion(sentence_index=2, verbatim_text=sentences[2].text,
                        delete_type="false_start", kept_index=3, kept_verbatim_text=sentences[3].text),
    ]
    conflicting = DuplicateFlag(idx=1, reason=FlagReason.FILLER, note="Conflicting proposal")
    if conflicting_lane == "section":
        proposals.append(SectionDeletion(sentence_index=1, verbatim_text=sentences[1].text,
                                         delete_type="stutter"))
    if conflicting_lane == "local_correction":
        monkeypatch.setattr(section_editor, "detect_local_corrections", lambda ss: [conflicting])
    monkeypatch.setattr(decisions, "detect_asides",
                        lambda *args, **kwargs: [conflicting] if conflicting_lane == "aside" else [])
    prompts = []
    _model_proposals(monkeypatch, proposals, prompts)
    trace = decisions.DecisionTrace()

    flags = decisions.detect_all_flags(
        transcript, [], [DisruptionRegion(start=146.21, end=146.275, peak_db=-41, floor_db=-81.4)],
        Settings(), trace=trace,
    )
    edl = build_edl(transcript, [KeepRegion(start=0, end=sentences[-1].end)], flags)

    assert len(prompts) == 1
    assert "[1] Audio" in prompts[0] and sentences[1].text in prompts[0]
    assert {flag.idx for flag in flags} == {0, 2}
    assert trace.section.protected_spans[0].text == "Sa volumenom otopine."
    rejections = trace.section.rejected_conflicts + trace.rejected_conflicts
    assert len(rejections) == 1 and rejections[0].flag.idx == 1
    for word in sentences[1].words:
        midpoint = (word.start + word.end) / 2
        assert any(d.action == "keep" and d.start <= midpoint < d.end for d in edl.decisions)


def test_case_5_partial_retake_preserves_intro_and_records_proposals(monkeypatch, tmp_path):
    transcript = _excerpt(5)
    sentences = transcript.sentences
    proposals = [
        SectionDeletion(sentence_index=1, verbatim_text="imamo pomnožen broj,", delete_type="false_start",
                        kept_index=3, kept_verbatim_text=sentences[3].text),
        SectionDeletion(sentence_index=2, verbatim_text=sentences[2].text, delete_type="retake",
                        kept_index=3, kept_verbatim_text=sentences[3].text),
        SectionDeletion(sentence_index=1, verbatim_text="izmišljeni tekst", delete_type="stutter"),
    ]
    _model_proposals(monkeypatch, proposals, [])
    monkeypatch.setattr(decisions, "detect_asides", lambda *args, **kwargs: [])
    settings = Settings()
    settings.general.output_dir = tmp_path

    edl = decisions.decide_edits(
        transcript, [KeepRegion(start=0, end=sentences[-1].end)], [], settings,
    )

    for word in sentences[1].words[:-3]:
        midpoint = (word.start + word.end) / 2
        assert any(d.action == "keep" and d.start <= midpoint < d.end for d in edl.decisions)
    for word in [*sentences[1].words[-3:], *sentences[2].words]:
        midpoint = (word.start + word.end) / 2
        assert any(d.action == "cut" and d.start <= midpoint < d.end for d in edl.decisions)
    saved = decisions.DecisionTrace.model_validate_json(next((tmp_path / "decision-traces").glob("*.json")).read_text())
    assert saved.transcript == transcript
    assert [p.deletion for p in saved.section.proposals] == proposals
    assert saved.section.proposals[-1].disposition == "rejected_unverifiable"
    assert saved.section.proposals[-1].detail
    assert saved.section.proposals[0].model_id == settings.section_editor.llm.id
    assert saved.edl_before_snapping == edl


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_retake_chain_is_resolved_without_order_dependence(reverse):
    sentences = [_sentence("Ovo je dovoljno duga rečenica", i * 4, i * 4 + 3) for i in range(3)]
    flags = [_deletion_to_flag(
        SectionDeletion(sentence_index=i, verbatim_text=sentences[i].text, delete_type="retake",
                        kept_index=i + 1, kept_verbatim_text=sentences[i + 1].text),
        sentences, SectionEditorConfig(),
    ) for i in range(2)]
    result = protect_kept_spans(list(reversed(flags)) if reverse else flags, sentences)
    assert [flag.idx for flag in result] == [0]


def test_same_sentence_later_replacement_is_supported():
    sentences = [_sentence("Krivi početak. Sada ispravno nastavljamo.", 0, 5)]
    proposal = SectionDeletion(sentence_index=0, verbatim_text="Krivi početak.", delete_type="false_start",
                               kept_index=0, kept_verbatim_text="Sada ispravno nastavljamo.")
    flag = _deletion_to_flag(proposal, sentences, SectionEditorConfig())
    assert flag is not None
    assert flag.word_trims[0].end == flag.kept_spans[0].start


def test_ambiguous_occurrence_is_rejected():
    sentences = [_sentence("Dobro dobro nastavljamo", 0, 3)]
    assert _deletion_to_flag(
        SectionDeletion(sentence_index=0, verbatim_text="dobro", delete_type="stutter"),
        sentences, SectionEditorConfig(),
    ) is None


def test_audio_candidate_can_be_cut_after_content_review(monkeypatch):
    sentences = [
        _sentence("Prva korisna rečenica.", 0, 5),
        _sentence("Izračunat ćemo masu...", 11, 12),
        _sentence("Prvo ćemo računati masu otopine.", 12.5, 16),
    ]
    prompts = []
    _model_proposals(monkeypatch, [SectionDeletion(
        sentence_index=1, verbatim_text=sentences[1].text, delete_type="false_start",
        kept_index=2, kept_verbatim_text=sentences[2].text,
    )], prompts)
    monkeypatch.setattr(decisions, "detect_asides", lambda *args, **kwargs: [])
    flags = decisions.detect_all_flags(
        Transcript(sentences=sentences, source_video="clip", language="hr", model_size="test"),
        [], [DisruptionRegion(start=8, end=8.1, peak_db=-40, floor_db=-80)], Settings(),
    )
    assert len(prompts) == 1
    assert [(flag.idx, flag.source) for flag in flags] == [(1, "section_editor")]


def test_merge_preserves_all_replacement_dependencies():
    from ai_video_editor.duplicate.section_editor import _merge_flags
    sentences = [
        _sentence("Prvi pokušaj pa drugi pokušaj", 0, 5),
        _sentence("Ispravni prvi pokušaj", 6, 9),
        _sentence("Ispravni drugi pokušaj", 10, 13),
    ]
    flags = [_deletion_to_flag(
        SectionDeletion(sentence_index=0, verbatim_text=text, delete_type="false_start",
                        kept_index=index, kept_verbatim_text=sentences[index].text),
        sentences, SectionEditorConfig(),
    ) for text, index in [("Prvi pokušaj", 1), ("drugi pokušaj", 2)]]
    merged = _merge_flags(flags)
    assert len(merged) == 1
    assert {span.sentence_index for span in merged[0].kept_spans} == {1, 2}
    conflicts = [DuplicateFlag(idx=i, reason=FlagReason.ASIDE) for i in (1, 2)]
    assert protect_kept_spans(merged + conflicts, sentences) == merged
