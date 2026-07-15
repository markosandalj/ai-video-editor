"""Unit tests for the LLM section editor — the deterministic parts (chunking,
span mapping, guardrails, merge) plus one end-to-end run with a mocked model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_editor.config.settings import SectionEditorConfig, Settings
from ai_video_editor.duplicate.models import FlagReason
from ai_video_editor.duplicate.section_editor import (
    Section,
    SectionDeletion,
    SectionEdits,
    SectionHealth,
    SectionTrace,
    _build_sections,
    _deletion_to_flag,
    _edit_section,
    _find_sandwich_repeat_hints,
    _locate_span,
    _merge_flags,
    detect_section_edits,
)
from ai_video_editor.transcription.models import Sentence, Word


FIXTURES = Path(__file__).parent / "fixtures"


def test_section_editor_is_the_default_cutter() -> None:
    settings = Settings()

    assert settings.section_editor.enabled is True
    assert settings.section_editor.llm.id == "gpt-5.6-sol"
    assert settings.section_editor.llm.class_path == "langchain_openai.ChatOpenAI"
    assert settings.section_editor.llm.model == "openai/gpt-5.6-sol"
    assert settings.section_editor.llm.api_key_env == "OPENROUTER_API_KEY"
    assert settings.section_editor.llm.provider_kwargs["base_url"] == (
        "https://openrouter.ai/api/v1"
    )
    assert settings.section_editor.fallback_llm is not None
    assert settings.section_editor.fallback_llm.model == "gpt-5.6-sol"
    assert settings.section_editor.fallback_llm.api_key_env == "OPENAI_API_KEY"
    assert "base_url" not in settings.section_editor.fallback_llm.provider_kwargs
    assert settings.section_editor.fallback_llm.provider_kwargs["reasoning_effort"] == "low"
    assert not hasattr(settings, "enrichment")


def _sentence(text: str, start: float, end: float) -> Sentence:
    words = text.split()
    n = len(words)
    step = (end - start) / n if n else 0.0
    word_objs = [
        Word(text=w, start=start + i * step, end=start + (i + 1) * step)
        for i, w in enumerate(words)
    ]
    return Sentence(words=word_objs, text=text, start=start, end=end)


class TestBuildSections:
    def test_single_section_when_short(self):
        sents = [_sentence("ovo je kratka recenica broj jedan", 0, 2)]
        cfg = SectionEditorConfig(target_words=1200, max_words=2000)
        sections = _build_sections(sents, cfg)
        assert len(sections) == 1
        assert (sections[0].owned_lo, sections[0].owned_hi) == (0, 1)

    def _tiling_corpus(self):
        # ~10 words each × 120 sentences ≈ 1200 words → several sections at the
        # production minimum sizes, so the guard rails stay under test.
        return [
            _sentence("rijec " * 10 + f"broj {i}", i * 2, i * 2 + 1.0)
            for i in range(120)
        ]

    def test_owned_ranges_tile_disjointly(self):
        sents = self._tiling_corpus()
        cfg = SectionEditorConfig(target_words=200, max_words=400, overlap_sentences=2)
        sections = _build_sections(sents, cfg)
        assert len(sections) > 1
        # Owned ranges cover every index exactly once, in order.
        covered = []
        for s in sections:
            covered.extend(range(s.owned_lo, s.owned_hi))
        assert covered == list(range(120))

    def test_context_widens_but_ownership_does_not(self):
        sents = self._tiling_corpus()
        cfg = SectionEditorConfig(target_words=200, max_words=400, overlap_sentences=2)
        sections = _build_sections(sents, cfg)
        second = sections[1]
        # Context reaches back into the previous section, ownership does not.
        assert second.ctx_lo < second.owned_lo
        assert not second.owns(second.ctx_lo)
        assert second.owns(second.owned_lo)

    def test_empty(self):
        assert _build_sections([], SectionEditorConfig()) == []


class TestSandwichRepeatHints:
    @staticmethod
    def _fixture_sentences(name: str) -> list[Sentence]:
        payload = json.loads((FIXTURES / f"{name}-raw.transcript.json").read_text())
        return [Sentence.model_validate(item) for item in payload["sentences"]]

    @staticmethod
    def _capture_prompt(sentences: list[Sentence], section: Section) -> str:
        prompts: list[str] = []

        class FakeStructured:
            def invoke(self, prompt: str) -> SectionEdits:
                prompts.append(prompt)
                return SectionEdits()

        class FakeLLM:
            def with_structured_output(self, schema):
                return FakeStructured()

        _edit_section(sentences, section, FakeLLM())
        return prompts[0]

    @pytest.mark.parametrize(
        ("fixture", "earlier", "later"),
        [
            ("engleski25ljeto-esej", 40, 43),
            ("engleski25ljeto-listening-1", 148, 150),
        ],
    )
    def test_finds_user_supplied_non_adjacent_chains(
        self, fixture: str, earlier: int, later: int
    ) -> None:
        sentences = self._fixture_sentences(fixture)
        section = Section(earlier, later + 1, earlier, later + 1)

        hints = _find_sandwich_repeat_hints(sentences, section)

        assert (earlier, later) in {
            (hint.earlier_sentence, hint.later_sentence) for hint in hints
        }

    def test_requires_a_visibly_truncated_middle_attempt(self) -> None:
        sentences = [
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 0, 3),
            _sentence("Hm.", 4, 4.5),
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 5, 8),
        ]

        hints = _find_sandwich_repeat_hints(sentences, Section(0, 3, 0, 3))

        assert hints == []

    def test_rejects_endpoint_gap_over_ten_seconds(self) -> None:
        sentences = [
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 0, 3),
            _sentence("Ovo je...", 4, 5),
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 14, 17),
        ]

        hints = _find_sandwich_repeat_hints(sentences, Section(0, 3, 0, 3))

        assert hints == []

    def test_does_not_emit_a_hint_owned_only_by_context(self) -> None:
        sentences = [
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 0, 3),
            _sentence("Ovo je...", 4, 5),
            _sentence("Ovo je prvi potpuni pokušaj iste važne rečenice", 6, 9),
            _sentence("Sada slijedi potpuno nova korisna rečenica", 10, 13),
        ]

        hints = _find_sandwich_repeat_hints(sentences, Section(2, 4, 0, 4))

        assert hints == []

    def test_only_appends_chain_instructions_when_a_hint_exists(self) -> None:
        plain = [
            _sentence("Ovo je prva korisna rečenica bez ponavljanja", 0, 3),
            _sentence("Ovo je druga potpuno različita korisna rečenica", 4, 7),
        ]
        plain_prompt = self._capture_prompt(plain, Section(0, 2, 0, 2))
        assert "MOGUĆI LANCI ISPRAVAKA" not in plain_prompt

        sentences = self._fixture_sentences("engleski25ljeto-esej")
        chain_prompt = self._capture_prompt(sentences, Section(40, 44, 40, 44))
        assert "MOGUĆI LANCI ISPRAVAKA" in chain_prompt
        assert '[40] RANIJE: "Zatim nam slijedi ovaj možda najvažniji dio' in chain_prompt
        assert '[42] IZMEĐU: "a..."' in chain_prompt
        assert '[43] KASNIJE: "Zatim nam slijedi ovaj Zatim nam slijedi' in chain_prompt
        assert "NIKADA ne briši cijelu miješanu rečenicu" in chain_prompt


class TestLocateSpan:
    def test_full_sentence_match(self):
        s = _sentence("Dakle danas ucimo o bazama podataka", 0, 3)
        cfg = SectionEditorConfig()
        ws, we, ratio, cov = _locate_span(s, "Dakle danas ucimo o bazama podataka", cfg)
        assert (ws, we) == (0, 5)
        assert ratio == pytest.approx(1.0)
        assert cov == pytest.approx(1.0)

    def test_partial_span_locates_middle(self):
        s = _sentence("Firstly youngsters s Firstly youngsters spend more time", 0, 4)
        cfg = SectionEditorConfig()
        located = _locate_span(s, "Firstly youngsters s", cfg)
        assert located is not None
        ws, we, ratio, cov = located
        assert ws == 0
        assert we <= 2
        assert cov < 0.9  # partial → should become a word trim

    def test_punctuation_and_case_insensitive(self):
        s = _sentence("Znaci, minus nekoliko i imamo.", 0, 2)
        cfg = SectionEditorConfig()
        located = _locate_span(s, "znaci minus", cfg)
        assert located is not None

    def test_rejects_absent_text(self):
        s = _sentence("Dakle danas ucimo o bazama podataka", 0, 3)
        cfg = SectionEditorConfig(min_span_match_ratio=0.8)
        assert _locate_span(s, "potpuno druga recenica koje nema", cfg) is None

    def test_empty_target(self):
        s = _sentence("Dakle danas", 0, 1)
        assert _locate_span(s, "   ", SectionEditorConfig()) is None


class TestDeletionToFlag:
    def _sents(self):
        return [
            _sentence("Dakle danas cemo raditi na projektu za web aplikaciju", 0, 3),
            _sentence("Znaci ovaj", 3.5, 4.0),
            _sentence("Dakle danas cemo raditi na projektu za web aplikaciju", 4.5, 7.5),
        ]

    def test_full_sentence_retake_becomes_full_flag(self):
        sents = self._sents()
        d = SectionDeletion(
            sentence_index=0,
            verbatim_text="Dakle danas cemo raditi na projektu za web aplikaciju",
            delete_type="retake",
            kept_index=2,
        )
        flag = _deletion_to_flag(d, sents, SectionEditorConfig())
        assert flag is not None
        assert flag.idx == 0
        assert flag.reason == FlagReason.DUPLICATE
        assert flag.word_trims == []
        assert flag.confidence == pytest.approx(0.9)

    def test_partial_span_becomes_word_trim(self):
        sents = [_sentence("Firstly youngsters s Firstly youngsters spend more time online", 0, 5)]
        d = SectionDeletion(
            sentence_index=0, verbatim_text="Firstly youngsters s", delete_type="stutter"
        )
        flag = _deletion_to_flag(d, sents, SectionEditorConfig())
        assert flag is not None
        assert flag.reason == FlagReason.STUTTER
        assert len(flag.word_trims) == 1
        assert flag.word_trims[0].start == pytest.approx(sents[0].words[0].start)

    def test_unverifiable_span_rejected(self):
        sents = self._sents()
        d = SectionDeletion(
            sentence_index=0, verbatim_text="ova recenica ne postoji nigdje", delete_type="filler"
        )
        assert _deletion_to_flag(d, sents, SectionEditorConfig()) is None

    def test_short_interjection_protected(self):
        sents = [
            _sentence("Dobro", 0, 0.4),
            _sentence("Sada rjesavamo prvi zadatak iz gradiva danas", 1, 4),
            _sentence("Dobro", 10, 10.4),
        ]
        d = SectionDeletion(
            sentence_index=0, verbatim_text="Dobro", delete_type="retake", kept_index=2
        )
        assert _deletion_to_flag(d, sents, SectionEditorConfig(protect_min_words=4)) is None

    def test_keep_later_violation_is_rejected(self):
        sents = self._sents()
        # Model wants to keep the EARLIER take (index 0) and cut the LATER (index 2).
        d = SectionDeletion(
            sentence_index=2,
            verbatim_text="Dakle danas cemo raditi na projektu za web aplikaciju",
            delete_type="retake",
            kept_index=0,
        )
        assert _deletion_to_flag(d, sents, SectionEditorConfig()) is None

    def test_long_gap_retake_is_rejected(self):
        sents = [
            _sentence("Danas govorimo o zakonu ocuvanja kolicine gibanja", 0, 4),
            _sentence("Danas govorimo o zakonu ocuvanja kolicine gibanja", 200, 204),
        ]
        d = SectionDeletion(
            sentence_index=0,
            verbatim_text="Danas govorimo o zakonu ocuvanja kolicine gibanja",
            delete_type="retake",
            kept_index=1,
        )
        assert _deletion_to_flag(
            d, sents, SectionEditorConfig(retake_max_gap_s=60)
        ) is None

    def test_redundant_type_is_rejected(self):
        sents = [_sentence("Ova recenica samo ponavlja ono sto smo vec rekli ranije", 0, 4)]
        d = SectionDeletion(
            sentence_index=0,
            verbatim_text="Ova recenica samo ponavlja ono sto smo vec rekli ranije",
            delete_type="redundant",
        )
        assert _deletion_to_flag(d, sents, SectionEditorConfig()) is None

class TestMergeFlags:
    def test_full_sentence_subsumes_trims(self):
        sents = [_sentence("jedan dva tri cetiri pet sest sedam osam", 0, 4)]
        cfg = SectionEditorConfig()
        full = _deletion_to_flag(
            SectionDeletion(sentence_index=0, verbatim_text="jedan dva tri cetiri pet sest sedam osam", delete_type="false_start"),
            sents, cfg,
        )
        partial = _deletion_to_flag(
            SectionDeletion(sentence_index=0, verbatim_text="jedan dva", delete_type="stutter"),
            sents, cfg,
        )
        merged = _merge_flags([partial, full])
        assert len(merged) == 1
        assert merged[0].word_trims == []  # full cut wins

    def test_multiple_partials_unioned(self):
        sents = [_sentence("aa bb cc dd ee ff gg hh ii jj kk ll", 0, 6)]
        cfg = SectionEditorConfig()
        p1 = _deletion_to_flag(
            SectionDeletion(sentence_index=0, verbatim_text="aa bb", delete_type="stutter"), sents, cfg
        )
        p2 = _deletion_to_flag(
            SectionDeletion(sentence_index=0, verbatim_text="kk ll", delete_type="stutter"), sents, cfg
        )
        merged = _merge_flags([p1, p2])
        assert len(merged) == 1
        assert len(merged[0].word_trims) == 2

    def test_partial_trims_with_different_reasons_keep_separate_provenance(self):
        sents = [_sentence("aa bb cc dd ee ff gg hh ii jj kk ll", 0, 6)]
        cfg = SectionEditorConfig()
        stutter = _deletion_to_flag(
            SectionDeletion(
                sentence_index=0,
                verbatim_text="aa bb",
                delete_type="stutter",
            ),
            sents,
            cfg,
        )
        filler = _deletion_to_flag(
            SectionDeletion(
                sentence_index=0,
                verbatim_text="kk ll",
                delete_type="filler",
            ),
            sents,
            cfg,
        )

        merged = _merge_flags([stutter, filler])

        assert [(flag.reason, len(flag.word_trims)) for flag in merged] == [
            (FlagReason.STUTTER, 1),
            (FlagReason.FILLER, 1),
        ]


class TestWordLevelScoring:
    def _edl(self, keeps):
        from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
        decisions = [
            EditDecision(start=s, end=e, action=EditAction.KEEP, reason=EditReason.SPEECH)
            for s, e in keeps
        ]
        return EditDecisionList(decisions=decisions)

    def test_word_keep_flags_partial_sentence(self):
        from ai_video_editor.qa.ground_truth import derive_word_keep_flags

        raw = [_sentence("Firstly youngsters s Firstly youngsters spend more time", 0, 5)]
        gt = [_sentence("Firstly youngsters spend more time", 0, 3)]
        flags = derive_word_keep_flags(raw, gt)
        # The stutter words at the start are not in the human edit; the tail is.
        assert flags[0][-1] is True
        assert flags[0].count(False) >= 1

    def test_word_level_credits_partial_trim(self):
        from ai_video_editor.qa.decision_eval import evaluate_decisions_word_level

        # Sentence 0-5s, 6 words. Human keeps only the last 3 words (after 2.5s).
        raw = [_sentence("aa bb cc dd ee ff", 0, 6)]
        gt = [_sentence("dd ee ff", 0, 3)]
        # Pipeline trims the first half (keeps 3.0-6.0s) — matching the human.
        edl = self._edl([(3.0, 6.0)])
        score = evaluate_decisions_word_level(raw, edl, gt)
        assert score.tp == 3  # aa bb cc correctly cut
        assert score.fp == 0
        assert score.fn == 0
        assert score.cut_f1 == pytest.approx(1.0)

    def test_word_level_penalises_full_cut_of_kept_words(self):
        from ai_video_editor.qa.decision_eval import evaluate_decisions_word_level

        raw = [_sentence("aa bb cc dd ee ff", 0, 6)]
        gt = [_sentence("dd ee ff", 0, 3)]
        # Pipeline cut the WHOLE sentence — 3 correct, 3 overcut.
        edl = self._edl([(100.0, 101.0)])  # keep nothing in range
        score = evaluate_decisions_word_level(raw, edl, gt)
        assert score.tp == 3
        assert score.fp == 3
        assert score.cut_precision == pytest.approx(0.5)

    def test_report_formatter(self):
        from ai_video_editor.experiments.section_pilot import FixturePilotResult, format_pilot_report
        from ai_video_editor.qa.decision_eval import WordDecisionScore

        results = [
            FixturePilotResult(
                "vid-1",
                WordDecisionScore(name="vid-1", tp=5, fp=5, fn=0, tn=90),
                WordDecisionScore(name="vid-1", tp=8, fp=1, fn=1, tn=90),
            )
        ]
        report = format_pilot_report(results, model_id="test-model")
        assert "vid-1" in report
        assert "AGGREGATE" in report
        assert "test-model" in report


class TestDetectSectionEditsEndToEnd:
    def test_trace_records_every_proposal_and_outcome(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se

        sents = [
            _sentence("Prvi pokušaj rečenice koji treba ukloniti sada", 0, 3),
            _sentence("Ispravan pokušaj rečenice koji ostaje u videu", 4, 7),
        ]

        class FakeStructured:
            def invoke(self, prompt):
                return SectionEdits(deletions=[
                    SectionDeletion(
                        sentence_index=0,
                        verbatim_text="Prvi pokušaj rečenice koji treba ukloniti sada",
                        delete_type="retake",
                        kept_index=1,
                    ),
                    SectionDeletion(
                        sentence_index=0,
                        verbatim_text="tekst koji ne postoji",
                        delete_type="filler",
                    ),
                ])

        class FakeLLM:
            def with_structured_output(self, schema):
                return FakeStructured()

        monkeypatch.setattr(se, "build_chat_model", lambda cfg: FakeLLM())
        trace = SectionTrace()

        flags = detect_section_edits(sents, SectionEditorConfig(), trace=trace)

        assert [flag.idx for flag in flags] == [0]
        assert [proposal.disposition for proposal in trace.proposals] == [
            "accepted",
            "rejected_unverifiable",
        ]
        assert trace.proposals[0].flag is not None
        assert trace.proposals[1].flag is None

    def test_primary_failure_falls_back_to_direct_model(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se

        sents = [
            _sentence("Prvi pokušaj rečenice koji treba ukloniti sada", 0, 3),
            _sentence("Ispravan pokušaj rečenice koji ostaje u videu", 4, 7),
        ]

        class PrimaryStructured:
            def invoke(self, prompt):
                raise TypeError("'NoneType' object is not iterable")

        class PrimaryLLM:
            def with_structured_output(self, schema):
                return PrimaryStructured()

        class FallbackStructured:
            def invoke(self, prompt):
                return SectionEdits(deletions=[
                    SectionDeletion(
                        sentence_index=0,
                        verbatim_text="Prvi pokušaj rečenice koji treba ukloniti sada",
                        delete_type="retake",
                        kept_index=1,
                    )
                ])

        class FallbackLLM:
            def with_structured_output(self, schema):
                return FallbackStructured()

        built = []

        def fake_build(cfg):
            built.append(cfg.id)
            return PrimaryLLM() if len(built) == 1 else FallbackLLM()

        monkeypatch.setattr(se, "build_chat_model", fake_build)

        health = SectionHealth()
        flags = detect_section_edits(
            sents,
            SectionEditorConfig(section_max_attempts=1, section_retry_backoff_s=0),
            health=health,
        )

        assert built == ["gpt-5.6-sol", "gpt-5.6-sol-openai-direct"]
        assert health.sections_fallback == 1
        assert health.sections_failed == 0
        assert [flag.idx for flag in flags] == [0]

    def test_builtin_sol_fallback_does_not_pollute_other_model_runs(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se
        from ai_video_editor.llm import LangChainModelConfig

        sents = [
            _sentence("Prva korisna rečenica ostaje u videu", 0, 3),
            _sentence("Druga korisna rečenica ostaje u videu", 4, 7),
        ]

        class BoomLLM:
            def with_structured_output(self, schema):
                raise RuntimeError("candidate failed")

        built = []

        def fake_build(cfg):
            built.append(cfg.model)
            return BoomLLM()

        monkeypatch.setattr(se, "build_chat_model", fake_build)
        candidate = LangChainModelConfig(
            id="candidate",
            model="gemini-candidate",
            api_key_env=None,
        )
        health = SectionHealth()
        flags = detect_section_edits(
            sents,
            SectionEditorConfig(section_max_attempts=1, section_retry_backoff_s=0),
            llm_config=candidate,
            health=health,
        )

        assert flags == []
        assert built == ["gemini-candidate"]
        assert health.sections_fallback == 0
        assert health.sections_failed == 1

    def test_transient_section_failure_is_retried(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se

        sents = [
            _sentence("Prvi pokušaj rečenice koji treba ukloniti sada", 0, 3),
            _sentence("Ispravan pokušaj rečenice koji ostaje u videu", 4, 7),
        ]
        calls = 0

        class FlakyStructured:
            def invoke(self, prompt):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise TypeError("'NoneType' object is not iterable")
                return SectionEdits(deletions=[
                    SectionDeletion(
                        sentence_index=0,
                        verbatim_text="Prvi pokušaj rečenice koji treba ukloniti sada",
                        delete_type="retake",
                        kept_index=1,
                    )
                ])

        class FlakyLLM:
            def with_structured_output(self, schema):
                return FlakyStructured()

        monkeypatch.setattr(se, "build_chat_model", lambda cfg: FlakyLLM())

        health = SectionHealth()
        flags = detect_section_edits(
            sents,
            SectionEditorConfig(section_max_attempts=2, section_retry_backoff_s=0),
            health=health,
        )

        assert calls == 2
        assert health.section_retries == 1
        assert health.sections_failed == 0
        assert [flag.idx for flag in flags] == [0]

    def test_mocked_model_flow(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se

        sents = [
            _sentence("Dakle danas cemo raditi na projektu za web aplikaciju", 0, 3),
            _sentence("Znaci ovaj", 3.5, 4.0),
            _sentence("Dakle danas cemo raditi na projektu za web aplikaciju", 4.5, 7.5),
            _sentence("Prvo trebamo napraviti bazu podataka s korisnicima", 8, 11),
        ]

        class FakeStructured:
            def invoke(self, prompt):
                return SectionEdits(deletions=[
                    SectionDeletion(
                        sentence_index=0,
                        verbatim_text="Dakle danas cemo raditi na projektu za web aplikaciju",
                        delete_type="retake",
                        kept_index=2,
                    ),
                    SectionDeletion(
                        sentence_index=1, verbatim_text="Znaci ovaj", delete_type="filler"
                    ),
                ])

        class FakeLLM:
            def with_structured_output(self, schema):
                return FakeStructured()

        monkeypatch.setattr(se, "build_chat_model", lambda cfg: FakeLLM())

        flags = detect_section_edits(sents, SectionEditorConfig(protect_min_words=4))
        idxs = {f.idx for f in flags}
        assert 0 in idxs  # earlier retake cut
        assert 1 in idxs  # filler cut
        assert 2 not in idxs  # later take kept
        assert 3 not in idxs  # unique content kept

    def test_section_failure_is_skipped(self, monkeypatch):
        import ai_video_editor.duplicate.section_editor as se

        sents = [_sentence(f"rijec rijec rijec rijec sentence broj {i}", i, i + 0.5) for i in range(4)]

        class BoomLLM:
            def with_structured_output(self, schema):
                raise RuntimeError("model exploded")

        monkeypatch.setattr(se, "build_chat_model", lambda cfg: BoomLLM())
        # Must not raise — best-effort per section.
        flags = detect_section_edits(
            sents,
            SectionEditorConfig(section_max_attempts=1, section_retry_backoff_s=0),
        )
        assert flags == []
