from __future__ import annotations

from pathlib import Path

from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.enrich.cache import load_cached_enrichment
from ai_video_editor.enrich.models import EnrichmentResult, SentenceEnrichment
from ai_video_editor.review.models import (
    ReviewPayload,
    ReviewSaveRequest,
    ReviewSaveResponse,
    ReviewSentence,
    ReviewTimelineSegment,
    ReviewVideoMetadata,
    ReviewWord,
)
from ai_video_editor.transcription.cache import cache_path_for
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def review_edl_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}-review.edl.json")


def review_payload_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}.review.json")


def load_review_payload(video_path: Path) -> ReviewPayload:
    transcript_path = cache_path_for(video_path)
    edl_path = video_path.with_suffix(".edl.json")

    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")
    if not edl_path.exists():
        raise FileNotFoundError(f"EDL not found: {edl_path}")

    transcript = Transcript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
    edl = EditDecisionList.model_validate_json(edl_path.read_text(encoding="utf-8"))

    review_edl_path = review_edl_path_for(video_path)
    reviewed = (
        EditDecisionList.model_validate_json(review_edl_path.read_text(encoding="utf-8"))
        if review_edl_path.exists()
        else None
    )
    enrichment = load_cached_enrichment(video_path)
    return build_review_payload(video_path, transcript, edl, reviewed, enrichment)


def build_review_payload(
    video_path: Path,
    transcript: Transcript,
    edl: EditDecisionList,
    reviewed: EditDecisionList | None = None,
    enrichment: EnrichmentResult | None = None,
) -> ReviewPayload:
    segments = [
        ReviewTimelineSegment.from_decision(idx, decision)
        for idx, decision in enumerate(edl.decisions)
    ]

    # When a review sidecar exists, the "current" kept state reflects prior edits.
    current = reviewed.decisions if reviewed is not None else edl.decisions
    enrich_map = enrichment.by_index() if enrichment is not None else {}

    sentences: list[ReviewSentence] = []
    word_idx = 0
    for sidx, sentence in enumerate(transcript.sentences):
        review_sentence, word_idx = _build_review_sentence(
            sidx, word_idx, sentence, edl.decisions, current, enrich_map.get(sidx)
        )
        sentences.append(review_sentence)

    video = ReviewVideoMetadata(
        id=video_path.stem,
        source_name=video_path.name,
        source_path=str(video_path),
        edl_path=str(video_path.with_suffix(".edl.json")),
        review_edl_path=str(review_edl_path_for(video_path)),
        duration=edl.total_duration,
        keep_duration=edl.keep_duration,
        cut_duration=edl.cut_duration,
    )
    return ReviewPayload(video=video, segments=segments, sentences=sentences)


def write_review_payload(video_path: Path, payload: ReviewPayload | None = None) -> Path:
    if payload is None:
        payload = load_review_payload(video_path)
    output = review_payload_path_for(video_path)
    output.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return output


def build_reviewed_edl(
    video_path: Path,
    payload: ReviewPayload,
    request: ReviewSaveRequest,
) -> EditDecisionList:
    cut = set(request.cut_words)
    words = sorted(
        (word for sentence in payload.sentences for word in sentence.words),
        key=lambda word: word.idx,
    )

    keep_spans: list[tuple[float, float]] = []
    run_start: float | None = None
    run_end: float = 0.0
    for word in words:
        if word.idx in cut:
            if run_start is not None:
                keep_spans.append((run_start, run_end))
                run_start = None
            continue
        if run_start is None:
            run_start, run_end = word.start, word.end
        else:
            run_end = max(run_end, word.end)
    if run_start is not None:
        keep_spans.append((run_start, run_end))

    merged = _merge_spans(keep_spans)
    decisions = _spans_to_decisions(merged, payload.video.duration)
    return EditDecisionList(
        decisions=decisions,
        source_video=str(video_path),
        total_duration=payload.video.duration,
    )


def save_reviewed_edl(video_path: Path, request: ReviewSaveRequest) -> ReviewSaveResponse:
    payload = load_review_payload(video_path)
    edl = build_reviewed_edl(video_path, payload, request)
    output = review_edl_path_for(video_path)
    output.write_text(edl.model_dump_json(indent=2), encoding="utf-8")
    return ReviewSaveResponse(
        review_edl_path=str(output),
        keep_duration=edl.keep_duration,
        cut_duration=edl.cut_duration,
        decisions=len(edl.decisions),
    )


def _build_review_sentence(
    idx: int,
    word_idx: int,
    sentence: Sentence,
    ai_decisions: list[EditDecision],
    current_decisions: list[EditDecision],
    enrichment: SentenceEnrichment | None = None,
) -> tuple[ReviewSentence, int]:
    salience = enrichment.word_salience if enrichment is not None else []
    words: list[ReviewWord] = []
    kept_count = 0
    for pos, word in enumerate(sentence.words):
        ai_kept = _is_kept(word, ai_decisions)
        kept = _is_kept(word, current_decisions)
        cut_decision = _decision_at(_midpoint(word), ai_decisions)
        reason = (
            cut_decision.reason.value
            if cut_decision and cut_decision.action == EditAction.CUT
            else ""
        )
        confidence = cut_decision.confidence if cut_decision else 1.0
        if ai_kept:
            # Kept words: prefer the enrichment salience (0-100 → 0-1) over the
            # old hardcoded 1.0; cut words keep the existing reason/confidence path.
            keep_score = (
                round(max(0.0, min(100.0, salience[pos])) / 100.0, 3)
                if pos < len(salience)
                else 1.0
            )
        else:
            keep_score = round(max(0.0, 1.0 - confidence), 3)
        words.append(
            ReviewWord(
                idx=word_idx,
                sentence_idx=idx,
                start=word.start,
                end=word.end,
                text=word.text,
                ai_kept=ai_kept,
                kept=kept,
                reason=reason,
                confidence=confidence,
                keep_score=keep_score,
            )
        )
        if kept:
            kept_count += 1
        word_idx += 1

    coverage = (kept_count / len(words)) if words else _keep_coverage(sentence, current_decisions)
    action = EditAction.KEEP if coverage >= 0.5 else EditAction.CUT
    original = _decision_at((sentence.start + sentence.end) / 2, ai_decisions)
    original_coverage = (
        (sum(1 for w in words if w.ai_kept) / len(words)) if words else 0.0
    )
    original_action = EditAction.KEEP if original_coverage >= 0.5 else EditAction.CUT
    reason = original.reason.value if original else EditReason.SILENCE.value
    confidence = original.confidence if original else 1.0
    note = original.note if original else ""

    review_sentence = ReviewSentence(
        idx=idx,
        start=sentence.start,
        end=sentence.end,
        text=sentence.text,
        action=action,
        original_action=original_action,
        reason=reason,
        confidence=confidence,
        keep_coverage=coverage,
        note=note,
        status=enrichment.status.value if enrichment is not None else "",
        tags=[tag.value for tag in enrichment.tags] if enrichment is not None else [],
        keep_confidence=enrichment.keep_confidence if enrichment is not None else 100.0,
        rationale=enrichment.rationale if enrichment is not None else "",
        words=words,
    )
    return review_sentence, word_idx


def _midpoint(word: Word) -> float:
    return (word.start + word.end) / 2


def _is_kept(word: Word, decisions: list[EditDecision]) -> bool:
    decision = _decision_at(_midpoint(word), decisions)
    return bool(decision and decision.action == EditAction.KEEP)


def _keep_coverage(sentence: Sentence, decisions: list[EditDecision]) -> float:
    duration = max(sentence.end - sentence.start, 0.0)
    if duration <= 0:
        return 0.0

    kept = 0.0
    for decision in decisions:
        if decision.action != EditAction.KEEP:
            continue
        kept += max(0.0, min(sentence.end, decision.end) - max(sentence.start, decision.start))
    return min(1.0, kept / duration)


def _decision_at(timestamp: float, decisions: list[EditDecision]) -> EditDecision | None:
    for decision in decisions:
        if decision.start <= timestamp <= decision.end:
            return decision
    return None


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    valid = sorted((start, end) for start, end in spans if end > start + 0.01)
    merged: list[tuple[float, float]] = []
    for start, end in valid:
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _spans_to_decisions(
    keep_spans: list[tuple[float, float]],
    total_duration: float,
) -> list[EditDecision]:
    decisions: list[EditDecision] = []
    prev_end = 0.0
    for start, end in keep_spans:
        if start > prev_end + 0.01:
            decisions.append(EditDecision(
                start=prev_end,
                end=start,
                action=EditAction.CUT,
                reason=EditReason.SILENCE,
            ))
        decisions.append(EditDecision(
            start=start,
            end=end,
            action=EditAction.KEEP,
            reason=EditReason.SPEECH,
        ))
        prev_end = end

    if prev_end < total_duration - 0.01:
        decisions.append(EditDecision(
            start=prev_end,
            end=total_duration,
            action=EditAction.CUT,
            reason=EditReason.SILENCE,
        ))
    return decisions
