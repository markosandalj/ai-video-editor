from __future__ import annotations

import pytest

from ai_video_editor.audio.models import KeepRegion
from ai_video_editor.config.settings import DuplicateDetectionConfig
from ai_video_editor.duplicate.edl import EditAction, EditDecisionList, EditReason, build_edl
from ai_video_editor.duplicate.lexical import compute_lexical_similarity
from ai_video_editor.duplicate.models import (
    DuplicateFlag,
    DuplicatePair,
    FlagReason,
    SimilarityScore,
)
from ai_video_editor.duplicate.semantic import compute_semantic_similarity
from ai_video_editor.duplicate.stutter import detect_stutters
from ai_video_editor.duplicate.windowed import windowed_pairs
from ai_video_editor.transcription.models import Sentence, Transcript, Word


# ──────────────────────────────────────────────────────────────────────
# Windowed pairs
# ──────────────────────────────────────────────────────────────────────

class TestWindowedPairs:
    def test_basic_window(self):
        pairs = list(windowed_pairs(5, window=2))
        assert (0, 1) in pairs
        assert (0, 2) in pairs
        assert (0, 3) not in pairs

    def test_window_larger_than_list(self):
        pairs = list(windowed_pairs(3, window=10))
        assert pairs == [(0, 1), (0, 2), (1, 2)]

    def test_single_sentence(self):
        assert list(windowed_pairs(1, window=5)) == []

    def test_empty(self):
        assert list(windowed_pairs(0, window=5)) == []

    def test_default_window_5(self):
        pairs = list(windowed_pairs(10, window=5))
        assert (0, 5) in pairs
        assert (0, 6) not in pairs
        assert len(pairs) == 35


# ──────────────────────────────────────────────────────────────────────
# Lexical similarity
# ──────────────────────────────────────────────────────────────────────

class TestLexicalSimilarity:
    def test_exact_match(self, simple_duplicate_pair):
        results = compute_lexical_similarity(simple_duplicate_pair, window=5, threshold=70)
        assert len(results) == 1
        assert results[0].lexical_ratio == 100.0
        assert results[0].lexical_token_sort == 100.0

    def test_no_matches(self, no_duplicates):
        results = compute_lexical_similarity(no_duplicates, window=5, threshold=70)
        assert len(results) == 0

    def test_threshold_filtering(self, simple_duplicate_pair):
        high = compute_lexical_similarity(simple_duplicate_pair, window=5, threshold=100.1)
        assert len(high) == 0

    def test_respects_window(self, croatian_transcript_with_duplicates):
        results_w1 = compute_lexical_similarity(
            croatian_transcript_with_duplicates, window=1, threshold=70
        )
        results_w5 = compute_lexical_similarity(
            croatian_transcript_with_duplicates, window=5, threshold=70
        )
        assert len(results_w5) >= len(results_w1)

    def test_detects_known_duplicate(self, croatian_transcript_with_duplicates):
        results = compute_lexical_similarity(
            croatian_transcript_with_duplicates, window=5, threshold=85
        )
        pair_indices = {(r.idx_a, r.idx_b) for r in results}
        assert (0, 2) in pair_indices

    def test_does_not_flag_distant_recap(self, croatian_transcript_with_duplicates):
        """Sentence [6] is a recap far from [0] — with window=5 it should never be compared."""
        results = compute_lexical_similarity(
            croatian_transcript_with_duplicates, window=5, threshold=50
        )
        pair_indices = {(r.idx_a, r.idx_b) for r in results}
        assert (0, 6) not in pair_indices


# ──────────────────────────────────────────────────────────────────────
# Semantic similarity
# ──────────────────────────────────────────────────────────────────────

class TestSemanticSimilarity:
    def test_exact_match(self, simple_duplicate_pair):
        results = compute_semantic_similarity(simple_duplicate_pair, window=5, threshold=0.5)
        assert len(results) == 1
        assert results[0].semantic_cosine is not None
        assert results[0].semantic_cosine >= 0.99

    def test_no_matches_at_high_threshold(self, no_duplicates):
        results = compute_semantic_similarity(no_duplicates, window=5, threshold=0.99)
        assert len(results) == 0

    def test_paraphrase_detection(self, croatian_transcript_with_duplicates):
        """Sentences [3] and [4] are paraphrases — semantic similarity should catch them."""
        results = compute_semantic_similarity(
            croatian_transcript_with_duplicates, window=5, threshold=0.70
        )
        pair_indices = {(r.idx_a, r.idx_b) for r in results}
        assert (3, 4) in pair_indices

    def test_empty_input(self):
        assert compute_semantic_similarity([], window=5, threshold=0.5) == []


# ──────────────────────────────────────────────────────────────────────
# EDL (Edit Decision List)
# ──────────────────────────────────────────────────────────────────────

def _make_transcript(sentences: list[Sentence]) -> Transcript:
    return Transcript(
        sentences=sentences,
        source_video="test.mp4",
        language="hr",
        model_size="test",
    )


class TestEditDecisionList:
    def test_no_flags_keeps_everything(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        keep_regions = [KeepRegion(start=0.0, end=5.0)]
        edl = build_edl(transcript, keep_regions, [])

        keep_decisions = [d for d in edl.decisions if d.action == EditAction.KEEP]
        assert len(keep_decisions) >= 1
        assert edl.keep_duration > 0

    def test_flagged_sentence_excluded(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        keep_regions = [KeepRegion(start=0.0, end=5.0)]

        score = SimilarityScore(idx_a=0, idx_b=1, lexical_ratio=100.0)
        pair = DuplicatePair(idx_keep=1, idx_cut=0, score=score, tier="lexical")
        flags = [DuplicateFlag(idx=0, reason=FlagReason.DUPLICATE, related_pair=pair)]

        edl = build_edl(transcript, keep_regions, flags)
        keep_decisions = [d for d in edl.decisions if d.action == EditAction.KEEP]

        for kd in keep_decisions:
            assert not (kd.start <= 0.0 and kd.end >= 2.0), (
                "Flagged sentence [0] (0.0-2.0) should not be in a keep segment"
            )

    def test_serializable_to_json(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        edl = build_edl(transcript, [], [])
        json_str = edl.model_dump_json()
        restored = EditDecisionList.model_validate_json(json_str)
        assert len(restored.decisions) == len(edl.decisions)

    def test_empty_transcript(self):
        transcript = _make_transcript([])
        edl = build_edl(transcript, [], [])
        assert len(edl.decisions) == 0

    def test_chronological_order(self, croatian_transcript_with_duplicates):
        transcript = _make_transcript(croatian_transcript_with_duplicates)
        keep_regions = [KeepRegion(start=0.0, end=53.0)]
        edl = build_edl(transcript, keep_regions, [])
        starts = [d.start for d in edl.decisions]
        assert starts == sorted(starts)

    def test_non_overlapping(self, croatian_transcript_with_duplicates):
        transcript = _make_transcript(croatian_transcript_with_duplicates)
        keep_regions = [KeepRegion(start=0.0, end=53.0)]
        edl = build_edl(transcript, keep_regions, [])
        for i in range(len(edl.decisions) - 1):
            assert edl.decisions[i].end <= edl.decisions[i + 1].start + 0.01


# ──────────────────────────────────────────────────────────────────────
# Config defaults
# ──────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────
# Stutter detection
# ──────────────────────────────────────────────────────────────────────

class TestStutterDetection:
    def _make_sentence(self, text: str, start: float = 0.0, end: float = 1.0) -> Sentence:
        words = [Word(text=w, start=start, end=end) for w in text.split()]
        return Sentence(words=words, text=text, start=start, end=end)

    def test_detects_trigram_repetition(self):
        s = self._make_sentence("a ovaj tu a ovaj tu broj koji je ovdje")
        result = detect_stutters([s])
        assert 0 in result

    def test_detects_bigram_with_enough_words(self):
        s = self._make_sentence("taj naš broj taj naš broj će mi zapravo")
        result = detect_stutters([s])
        assert 0 in result

    def test_no_stutter_in_clean_sentence(self):
        s = self._make_sentence("Ovo je potpuno normalna rečenica bez ponavljanja.")
        result = detect_stutters([s])
        assert len(result) == 0

    def test_short_sentence_not_flagged(self):
        s = self._make_sentence("Da da.")
        result = detect_stutters([s])
        assert len(result) == 0

    def test_multiple_sentences_only_flags_stutter(self):
        clean = self._make_sentence("Dobro idemo dalje.")
        stutter = self._make_sentence("evo ja evo ja sam nekako uvijek zamišljao")
        sentences = [clean, stutter]
        result = detect_stutters(sentences)
        assert result == [1]


class TestDuplicateDetectionConfig:
    def test_defaults(self):
        cfg = DuplicateDetectionConfig()
        assert cfg.window_size == 5
        assert cfg.lexical_definite == 90.0
        assert cfg.lexical_maybe == 70.0
        assert cfg.semantic_definite == 0.95
        assert cfg.semantic_maybe == 0.75
        assert cfg.gemini_confidence_threshold == 0.8
        assert cfg.definite_min_words == 4
        assert cfg.take_selection == "last"
        assert cfg.llm_keep_review is False
        assert cfg.prefer_completeness is False

    def test_in_settings(self):
        from ai_video_editor.config import Settings
        s = Settings()
        assert s.duplicate_detection.window_size == 5


# ──────────────────────────────────────────────────────────────────────
# Full detection pipeline (Gemini calls mocked)
# ──────────────────────────────────────────────────────────────────────

class TestDetectDuplicatesPipeline:
    @pytest.fixture(autouse=True)
    def _mock_gemini(self, monkeypatch):
        import ai_video_editor.duplicate.pipeline as pl

        self.gemini_pairs: list = []
        self.pick_best_called = False

        def fake_verify(pairs, sentences, **kwargs):
            self.gemini_pairs.extend(pairs)
            return []

        def fake_pick_best(pairs, sentences, **kwargs):
            self.pick_best_called = True
            return {}

        monkeypatch.setattr(pl, "verify_duplicates_with_gemini", fake_verify)
        monkeypatch.setattr(pl, "pick_best_version_with_gemini", fake_pick_best)
        monkeypatch.setattr(pl, "detect_false_starts_with_gemini",
                            lambda *a, **k: _empty_false_start())
        monkeypatch.setattr(pl, "verify_stutters_with_gemini", lambda *a, **k: [])
        monkeypatch.setattr(pl, "verify_fragments_with_gemini", lambda *a, **k: [])

    def test_definite_pair_cuts_earlier_keeps_later(self, simple_duplicate_pair):
        from ai_video_editor.duplicate.pipeline import detect_duplicates

        flags = detect_duplicates(simple_duplicate_pair)
        assert [f.idx for f in flags if f.reason == FlagReason.DUPLICATE] == [0]

    def test_short_definite_pair_demoted_to_gemini(self):
        from ai_video_editor.duplicate.pipeline import detect_duplicates

        sentences = [
            _make_sentence("Dobro.", 0.0, 0.5),
            _make_sentence("Sada rješavamo prvi zadatak iz gradiva.", 1.0, 3.0),
            _make_sentence("Dobro.", 10.0, 10.5),
        ]
        flags = detect_duplicates(sentences)
        # The identical short pair must not be auto-cut by tier 1/2 …
        assert [f.idx for f in flags if f.reason == FlagReason.DUPLICATE] == []
        # … but it must reach Gemini for a context-aware verdict.
        assert any({p.idx_a, p.idx_b} == {0, 2} for p in self.gemini_pairs)

    def test_llm_keep_review_off_by_default(self, simple_duplicate_pair):
        from ai_video_editor.duplicate.pipeline import detect_duplicates

        detect_duplicates(simple_duplicate_pair)
        assert self.pick_best_called is False

    def test_llm_keep_review_opt_in(self, simple_duplicate_pair):
        from ai_video_editor.duplicate.pipeline import detect_duplicates

        # The pick-best pass only runs when Gemini is the arbiter *and* the
        # re-review is opted into.
        cfg = DuplicateDetectionConfig(take_selection="gemini", llm_keep_review=True)
        detect_duplicates(simple_duplicate_pair, cfg)
        assert self.pick_best_called is True

    def test_last_take_selection_overrides_llm_keep_review(self, simple_duplicate_pair):
        from ai_video_editor.duplicate.pipeline import detect_duplicates

        # take_selection='last' is the master switch: even with llm_keep_review
        # opted in, the deterministic keep-later rule wins and Gemini is never
        # asked which side to keep.
        cfg = DuplicateDetectionConfig(take_selection="last", llm_keep_review=True)
        detect_duplicates(simple_duplicate_pair, cfg)
        assert self.pick_best_called is False


def _make_sentence(text: str, start: float, end: float) -> Sentence:
    words = [Word(text=w, start=start, end=end) for w in text.split()]
    return Sentence(words=words, text=text, start=start, end=end)


def _empty_false_start():
    from ai_video_editor.duplicate.gemini_verify import FalseStartVerdict
    return FalseStartVerdict(filler_indices=[], reasoning="")
