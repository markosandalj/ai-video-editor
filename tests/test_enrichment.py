from __future__ import annotations

from pathlib import Path

from ai_video_editor.config.settings import EnrichmentConfig
from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.enrich import (
    EnrichmentResult,
    EnrichmentStatus,
    EnrichmentTag,
    SentenceEnrichment,
    derive_status,
    enrich_transcript,
    load_cached_enrichment,
    reconcile_word_salience,
    save_enrichment,
)
from ai_video_editor.enrich.runner import SentenceEnrichmentLLM
from ai_video_editor.review import build_review_payload
from ai_video_editor.transcription.models import Sentence, Transcript, Word


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sentence(text: str, start: float, end: float) -> Sentence:
    tokens = text.split()
    step = (end - start) / max(len(tokens), 1)
    words = [
        Word(text=token, start=start + i * step, end=start + (i + 1) * step)
        for i, token in enumerate(tokens)
    ]
    return Sentence(text=text, start=start, end=end, words=words)


def _transcript() -> Transcript:
    return Transcript(
        sentences=[
            _sentence("Keep this introduction.", 0.0, 2.0),
            _sentence("Maybe restore this bridge.", 2.5, 4.0),
            _sentence("Keep this calculation.", 4.5, 6.0),
        ],
        source_video="lesson.mp4",
        language="hr",
        model_size="test",
    )


def _edl() -> EditDecisionList:
    return EditDecisionList(
        source_video="lesson.mp4",
        total_duration=6.0,
        decisions=[
            EditDecision(start=0.0, end=2.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=2.0, end=4.5, action=EditAction.CUT, reason=EditReason.FALSE_START),
            EditDecision(start=4.5, end=6.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )


# Maps sentence idx -> (keep_confidence) for the stub scorer.
_SCORES = {0: 95.0, 1: 70.0, 2: 50.0}


def _stub_scorer(batch):
    items = []
    for ctx in batch:
        score = _SCORES[ctx.idx]
        items.append(
            SentenceEnrichmentLLM(
                sentence_idx=ctx.idx,
                keep_confidence=score,
                tags=["verbatim_clean", "not_a_real_tag"],
                rationale="razlog",
                word_salience=[score] * len(ctx.sentence.words),
            )
        )
    return items


# ---------------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------------

def test_derive_status_all_four_outcomes() -> None:
    assert derive_status(80.0, is_cut=False) is EnrichmentStatus.GREEN
    assert derive_status(79.9, is_cut=False) is EnrichmentStatus.YELLOW
    assert derive_status(60.0, is_cut=True) is EnrichmentStatus.RESTORE
    assert derive_status(59.9, is_cut=True) is EnrichmentStatus.RED


def test_derive_status_respects_custom_thresholds() -> None:
    assert derive_status(85.0, is_cut=False, green_threshold=90.0) is EnrichmentStatus.YELLOW
    assert derive_status(50.0, is_cut=True, restore_threshold=40.0) is EnrichmentStatus.RESTORE


# ---------------------------------------------------------------------------
# reconcile_word_salience
# ---------------------------------------------------------------------------

def test_reconcile_word_salience_variants() -> None:
    assert reconcile_word_salience([10.0, 20.0], 2, 5.0) == [10.0, 20.0]
    assert reconcile_word_salience([10.0], 2, 5.0) == [10.0, 5.0]  # too short -> pad
    assert reconcile_word_salience([10.0, 20.0, 30.0], 2, 5.0) == [10.0, 20.0]  # too long -> trunc
    assert reconcile_word_salience([], 2, 5.0) == [5.0, 5.0]  # empty -> fallback
    assert reconcile_word_salience([-5.0, 200.0], 2, 5.0) == [0.0, 100.0]  # clamp
    assert reconcile_word_salience([1.0], 0, 5.0) == []  # no words


# ---------------------------------------------------------------------------
# Serialization / cache
# ---------------------------------------------------------------------------

def test_enrichment_result_round_trip_and_index() -> None:
    result = EnrichmentResult(
        source_video="lesson.mp4",
        sentences=[
            SentenceEnrichment(
                sentence_idx=0,
                keep_confidence=90.0,
                status=EnrichmentStatus.GREEN,
                tags=[EnrichmentTag.VERBATIM_CLEAN],
                rationale="ok",
                word_salience=[90.0, 90.0],
            )
        ],
    )
    restored = EnrichmentResult.model_validate_json(result.model_dump_json())
    assert restored.sentences == result.sentences
    assert restored.by_index()[0].status is EnrichmentStatus.GREEN


def test_enrichment_cache_round_trip(tmp_path: Path) -> None:
    video = tmp_path / "lesson-raw.mp4"
    result = EnrichmentResult(source_video=str(video), sentences=[])
    path = save_enrichment(video, result)
    assert path == video.with_suffix(".enrichment.json")
    loaded = load_cached_enrichment(video)
    assert loaded is not None and loaded.source_video == str(video)
    assert load_cached_enrichment(tmp_path / "missing.mp4") is None


# ---------------------------------------------------------------------------
# enrich_transcript
# ---------------------------------------------------------------------------

def test_enrich_transcript_maps_status_and_cut_detection() -> None:
    result = enrich_transcript(_transcript(), _edl(), EnrichmentConfig(), scorer=_stub_scorer)
    by_idx = result.by_index()
    # s0 kept & high → green; s1 cut & 70 → restore; s2 kept & 50 → yellow
    assert by_idx[0].status is EnrichmentStatus.GREEN
    assert by_idx[1].status is EnrichmentStatus.RESTORE
    assert by_idx[2].status is EnrichmentStatus.YELLOW
    # Unknown tags are dropped, valid ones kept.
    assert by_idx[0].tags == [EnrichmentTag.VERBATIM_CLEAN]
    # word_salience aligned to word counts.
    assert len(by_idx[0].word_salience) == 3


def test_enrich_transcript_fallback_for_missing_and_raising_scorer() -> None:
    # Scorer that omits sentence 1 entirely.
    def partial_scorer(batch):
        return [it for it in _stub_scorer(batch) if it.sentence_idx != 1]

    result = enrich_transcript(_transcript(), _edl(), EnrichmentConfig(), scorer=partial_scorer)
    s1 = result.by_index()[1]
    assert s1.status is EnrichmentStatus.RED  # cut + neutral fallback
    assert EnrichmentTag.NEEDS_REVIEW in s1.tags

    def boom(batch):
        raise RuntimeError("LLM down")

    fallback = enrich_transcript(_transcript(), _edl(), EnrichmentConfig(), scorer=boom)
    statuses = {s.sentence_idx: s.status for s in fallback.sentences}
    assert statuses[0] is EnrichmentStatus.YELLOW  # kept, failed scoring → yellow not green
    assert statuses[1] is EnrichmentStatus.RED  # cut → red


# ---------------------------------------------------------------------------
# Review payload mapping
# ---------------------------------------------------------------------------

def test_build_review_payload_surfaces_enrichment() -> None:
    enrichment = enrich_transcript(_transcript(), _edl(), EnrichmentConfig(), scorer=_stub_scorer)
    payload = build_review_payload(
        Path("lesson-raw.mp4"), _transcript(), _edl(), None, enrichment
    )

    s0, s1, s2 = payload.sentences
    assert s0.status == "green" and s0.keep_confidence == 95.0
    assert s1.status == "restore"  # cut sentence flagged for possible restore
    assert s2.status == "yellow" and s2.rationale == "razlog"
    # Kept words inherit salience-based keep_score (95/100), not the old 1.0.
    assert s0.words[0].ai_kept and s0.words[0].keep_score == 0.95


def test_build_review_payload_without_enrichment_is_backward_compatible() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())
    s0 = payload.sentences[0]
    assert s0.status == "" and s0.keep_confidence == 100.0
    # Kept words fall back to the old hardcoded score.
    assert s0.words[0].keep_score == 1.0
