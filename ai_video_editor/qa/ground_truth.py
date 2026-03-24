from __future__ import annotations

from pathlib import Path

from loguru import logger
from rapidfuzz import fuzz

from ai_video_editor.qa.models import (
    SentenceMatch,
    TemporalComparisonResult,
    TranscriptComparisonResult,
)
from ai_video_editor.transcription.chunking import chunk_into_sentences
from ai_video_editor.transcription.elevenlabs_stt import transcribe_elevenlabs
from ai_video_editor.transcription.models import Sentence, Transcript

MATCH_THRESHOLD = 65.0


def _transcript_cache_path(video_path: Path) -> Path:
    return video_path.with_name(video_path.stem + ".qa-transcript.json")


def _transcribe_video(video_path: Path) -> list[Sentence]:
    """Transcribe a video file, using a cached transcript when available."""
    cache_path = _transcript_cache_path(video_path)
    if cache_path.exists():
        logger.info("Using cached transcript for {}", video_path.name)
        transcript = Transcript.model_validate_json(cache_path.read_text("utf-8"))
        return transcript.sentences

    words, _ = transcribe_elevenlabs(video_path, language_code="hr")
    sentences = chunk_into_sentences(words)

    transcript = Transcript(
        sentences=sentences,
        source_video=video_path.name,
        language="hr",
        model_size="scribe_v2",
    )
    cache_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Cached transcript for {} → {}", video_path.name, cache_path.name)

    return sentences


def _best_match(
    needle: Sentence,
    haystack: list[Sentence],
    used: set[int],
) -> tuple[int, float] | None:
    """Find the best fuzzy match for *needle* in *haystack*, skipping *used* indices."""
    best_idx = -1
    best_score = 0.0

    for i, candidate in enumerate(haystack):
        if i in used:
            continue
        score = max(
            fuzz.ratio(needle.text, candidate.text),
            fuzz.token_sort_ratio(needle.text, candidate.text),
        )
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx >= 0 and best_score >= MATCH_THRESHOLD:
        return best_idx, best_score
    return None


def compare_transcripts(
    pipeline_sentences: list[Sentence],
    ground_truth_sentences: list[Sentence],
    match_threshold: float = MATCH_THRESHOLD,
) -> TranscriptComparisonResult:
    """
    Compare two lists of sentences via fuzzy matching.

    Returns precision/recall/F1 of the pipeline's output against the
    human-edited ground truth.
    """
    used_gt: set[int] = set()
    matches: list[SentenceMatch] = []
    pipeline_only: list[str] = []

    for ps in pipeline_sentences:
        result = _best_match(ps, ground_truth_sentences, used_gt)
        if result is not None:
            gt_idx, score = result
            gt_s = ground_truth_sentences[gt_idx]
            used_gt.add(gt_idx)
            matches.append(SentenceMatch(
                pipeline_text=ps.text,
                ground_truth_text=gt_s.text,
                similarity=round(score, 2),
                pipeline_start=ps.start,
                pipeline_end=ps.end,
                gt_start=gt_s.start,
                gt_end=gt_s.end,
            ))
        else:
            pipeline_only.append(ps.text)

    gt_only = [
        ground_truth_sentences[i].text
        for i in range(len(ground_truth_sentences))
        if i not in used_gt
    ]

    result = TranscriptComparisonResult(
        pipeline_sentences=len(pipeline_sentences),
        ground_truth_sentences=len(ground_truth_sentences),
        matched=len(matches),
        pipeline_only=pipeline_only,
        ground_truth_only=gt_only,
        matches=matches,
    )

    logger.info(
        "Transcript comparison: P={:.1%} R={:.1%} F1={:.1%} "
        "(matched={}, pipeline_only={}, gt_only={})",
        result.precision, result.recall, result.f1,
        len(matches), len(pipeline_only), len(gt_only),
    )
    return result


def transcribe_for_qa(video_path: Path, *, force: bool = False) -> list[Sentence]:
    """
    Transcribe a video for QA, using a cached `.qa-transcript.json` when
    available.  Pass ``force=True`` to skip the cache (e.g. for the
    pipeline output which changes every run).
    """
    if force:
        logger.info("Transcribing (forced, no cache): {}", video_path.name)
        words, _ = transcribe_elevenlabs(video_path, language_code="hr")
        sentences = chunk_into_sentences(words)
        transcript = Transcript(
            sentences=sentences,
            source_video=video_path.name,
            language="hr",
            model_size="scribe_v2",
        )
        cache_path = _transcript_cache_path(video_path)
        cache_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
        return sentences

    return _transcribe_video(video_path)


def compare_transcripts_from_videos(
    pipeline_video: Path,
    ground_truth_video: Path,
    *,
    pipeline_sentences: list[Sentence] | None = None,
) -> TranscriptComparisonResult:
    """
    Compare transcripts of two videos.

    If *pipeline_sentences* are provided they are used directly (avoids
    a redundant ElevenLabs call when the caller already transcribed the
    pipeline output).
    """
    if pipeline_sentences is None:
        logger.info("Transcribing pipeline output: {}", pipeline_video.name)
        pipeline_sentences = transcribe_for_qa(pipeline_video, force=True)

    logger.info("Transcribing ground truth: {}", ground_truth_video.name)
    gt_sentences = transcribe_for_qa(ground_truth_video)

    return compare_transcripts(pipeline_sentences, gt_sentences)


def compare_temporal(
    pipeline_video: Path,
    ground_truth_video: Path,
    pipeline_sentences: list[Sentence],
    gt_sentences: list[Sentence],
    matches: list[SentenceMatch],
) -> TemporalComparisonResult:
    """
    Compare timing between pipeline and ground truth using matched
    sentence pairs as anchor points.
    """
    import subprocess, json

    def _get_duration(path: Path) -> float:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True,
        )
        return float(json.loads(probe.stdout)["format"]["duration"])

    p_dur = _get_duration(pipeline_video)
    gt_dur = _get_duration(ground_truth_video)

    offsets: list[float] = []
    for m in matches:
        if m.pipeline_start > 0 and m.gt_start > 0:
            offsets.append(abs(m.pipeline_start - m.gt_start))

    mean_off = sum(offsets) / len(offsets) if offsets else 0.0

    dur_ratio = min(p_dur, gt_dur) / max(p_dur, gt_dur) if max(p_dur, gt_dur) > 0 else 1.0

    max_acceptable_offset = 5.0
    timing_score = max(0.0, 1.0 - mean_off / max_acceptable_offset) if offsets else 0.0

    temporal_score = (dur_ratio + timing_score) / 2.0

    result = TemporalComparisonResult(
        pipeline_duration=round(p_dur, 2),
        ground_truth_duration=round(gt_dur, 2),
        duration_delta=round(p_dur - gt_dur, 2),
        anchor_offsets=[round(o, 3) for o in offsets],
        mean_offset=round(mean_off, 3),
        temporal_score=round(temporal_score, 4),
    )

    logger.info(
        "Temporal comparison: pipeline={:.1f}s gt={:.1f}s delta={:.1f}s "
        "mean_offset={:.3f}s score={:.1%}",
        p_dur, gt_dur, p_dur - gt_dur, mean_off, temporal_score,
    )
    return result
