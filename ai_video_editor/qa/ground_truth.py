from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from loguru import logger
from rapidfuzz import fuzz

from ai_video_editor.qa.models import (
    SentenceMatch,
    TemporalComparisonResult,
    TranscriptComparisonResult,
    WordLevelComparisonResult,
)
from ai_video_editor.transcription.chunking import chunk_into_sentences
from ai_video_editor.transcription.elevenlabs_stt import transcribe_elevenlabs
from ai_video_editor.transcription.models import Sentence, Transcript

MATCH_THRESHOLD = 65.0
_WORD_STRIP = ".,;:!?\"'()-–—…"


def _normalise_word(text: str) -> str:
    return text.lower().strip(_WORD_STRIP)


def _transcript_cache_path(video_path: Path) -> Path:
    return video_path.with_name(video_path.stem + ".qa-transcript.json")


def _transcribe_video(video_path: Path) -> list[Sentence]:
    """Transcribe a video file, using a cached transcript when available."""
    cache_path = _transcript_cache_path(video_path)
    if cache_path.exists():
        logger.info("Using cached transcript for {}", video_path.name)
        transcript = Transcript.model_validate_json(cache_path.read_text("utf-8"))
        return transcript.sentences

    sentences = _transcribe_with_retry(video_path)

    transcript = Transcript(
        sentences=sentences,
        source_video=video_path.name,
        language="hr",
        model_size="scribe_v2",
    )
    cache_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Cached transcript for {} → {}", video_path.name, cache_path.name)

    return sentences


def _pair_similarity(a: Sentence, b: Sentence) -> float:
    return max(fuzz.ratio(a.text, b.text), fuzz.token_sort_ratio(a.text, b.text))


def _align_monotonic(
    pipeline_sentences: list[Sentence],
    ground_truth_sentences: list[Sentence],
    match_threshold: float,
) -> list[tuple[int, int, float]]:
    """Order-preserving alignment maximising total matched similarity.

    Greedy global matching can cross-match recurring sentences (the same formula
    said twice in a maths lecture), inflating F1 and — worse — feeding wrong
    anchor pairs to the temporal comparison. This is the sentence-level analogue
    of LCS: matches never cross, so anchors stay monotonic in time.
    """
    n, m = len(pipeline_sentences), len(ground_truth_sentences)
    if n == 0 or m == 0:
        return []

    # dp[i][j] = best total similarity aligning pipeline[i:] with gt[j:].
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(dp[i + 1][j], dp[i][j + 1])
            score = _pair_similarity(pipeline_sentences[i], ground_truth_sentences[j])
            if score >= match_threshold:
                best = max(best, score + dp[i + 1][j + 1])
            dp[i][j] = best

    pairs: list[tuple[int, int, float]] = []
    i = j = 0
    while i < n and j < m:
        score = _pair_similarity(pipeline_sentences[i], ground_truth_sentences[j])
        take = score >= match_threshold and abs(
            (score + dp[i + 1][j + 1]) - dp[i][j]
        ) < 1e-6
        if take:
            pairs.append((i, j, score))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def compare_transcripts(
    pipeline_sentences: list[Sentence],
    ground_truth_sentences: list[Sentence],
    match_threshold: float = MATCH_THRESHOLD,
) -> TranscriptComparisonResult:
    """
    Compare two lists of sentences via order-preserving fuzzy alignment.

    Returns precision/recall/F1 of the pipeline's output against the
    human-edited ground truth.
    """
    aligned = _align_monotonic(pipeline_sentences, ground_truth_sentences, match_threshold)
    matched_pi = {pi for pi, _, _ in aligned}
    matched_gi = {gi for _, gi, _ in aligned}

    matches: list[SentenceMatch] = []
    for pi, gi, score in aligned:
        ps = pipeline_sentences[pi]
        gt_s = ground_truth_sentences[gi]
        matches.append(SentenceMatch(
            pipeline_text=ps.text,
            ground_truth_text=gt_s.text,
            similarity=round(score, 2),
            pipeline_start=ps.start,
            pipeline_end=ps.end,
            gt_start=gt_s.start,
            gt_end=gt_s.end,
        ))

    pipeline_only = [
        ps.text for i, ps in enumerate(pipeline_sentences) if i not in matched_pi
    ]
    gt_only = [
        ground_truth_sentences[i].text
        for i in range(len(ground_truth_sentences))
        if i not in matched_gi
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


def _transcribe_with_retry(video_path: Path, *, max_retries: int = 3) -> list[Sentence]:
    """Call ElevenLabs with retry on transient network errors."""
    import time

    for attempt in range(1, max_retries + 1):
        try:
            words, _, _ = transcribe_elevenlabs(video_path, language_code="hr")
            return chunk_into_sentences(words)
        except Exception as exc:
            if attempt == max_retries:
                raise
            wait = 5 * attempt
            logger.warning(
                "Transcription attempt {}/{} failed ({}), retrying in {}s...",
                attempt, max_retries, type(exc).__name__, wait,
            )
            time.sleep(wait)
    return []  # unreachable


def transcribe_for_qa(video_path: Path, *, force: bool = False) -> list[Sentence]:
    """
    Transcribe a video for QA, using a cached `.qa-transcript.json` when
    available.  Pass ``force=True`` to skip the cache (e.g. for the
    pipeline output which changes every run).
    """
    if force:
        logger.info("Transcribing (forced, no cache): {}", video_path.name)
        sentences = _transcribe_with_retry(video_path)
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


def _lcs_length_table(a: list[str], b: list[str]) -> list[list[int]]:
    """Build the LCS dynamic-programming table (space-optimised rows kept for backtrack)."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp


def _backtrack_lcs(dp: list[list[int]], a: list[str], b: list[str]) -> set[int]:
    """Return indices into *a* that belong to the LCS."""
    indices: list[int] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            indices.append(i - 1)
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return set(indices)


def _backtrack_lcs_b(dp: list[list[int]], a: list[str], b: list[str]) -> set[int]:
    """Return indices into *b* that belong to the LCS."""
    indices: list[int] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            indices.append(j - 1)
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return set(indices)


def compare_transcripts_word_level(
    pipeline_sentences: list[Sentence],
    ground_truth_sentences: list[Sentence],
) -> WordLevelComparisonResult:
    """
    Word-level comparison using Longest Common Subsequence.

    Flattens both transcripts to normalised word lists, computes the LCS,
    and derives precision/recall/F1 based on word coverage.  Immune to
    sentence-boundary differences.
    """
    p_words = [_normalise_word(w.text) for s in pipeline_sentences for w in s.words]
    gt_words = [_normalise_word(w.text) for s in ground_truth_sentences for w in s.words]

    p_words = [w for w in p_words if w]
    gt_words = [w for w in gt_words if w]

    dp = _lcs_length_table(p_words, gt_words)
    lcs_len = dp[len(p_words)][len(gt_words)]

    lcs_p_indices = _backtrack_lcs(dp, p_words, gt_words)
    lcs_gt_indices = _backtrack_lcs_b(dp, p_words, gt_words)

    extra = [p_words[i] for i in range(len(p_words)) if i not in lcs_p_indices]
    missing = [gt_words[i] for i in range(len(gt_words)) if i not in lcs_gt_indices]

    result = WordLevelComparisonResult(
        pipeline_words=len(p_words),
        ground_truth_words=len(gt_words),
        lcs_length=lcs_len,
        extra_words=extra,
        missing_words=missing,
    )

    logger.info(
        "Word-level comparison: P={:.1%} R={:.1%} F1={:.1%} "
        "(LCS={}, pipeline={}, gt={}, extra={}, missing={})",
        result.precision, result.recall, result.f1,
        lcs_len, len(p_words), len(gt_words), len(extra), len(missing),
    )
    return result


def derive_word_coverage(
    raw_sentences: list[Sentence],
    gt_sentences: list[Sentence],
) -> list[float]:
    """Return per-raw-sentence word coverage against the human-edited transcript.

    The human edit is re-transcribed, so sentence boundaries are not stable: a
    raw sentence can be split across two GT sentences, or multiple raw sentences
    can be merged into one GT sentence. This aligns the full word stream instead
    and attributes each matched raw word back to its source sentence.
    """
    raw_words: list[str] = []
    raw_owners: list[int] = []
    totals = [0] * len(raw_sentences)

    for sentence_idx, sentence in enumerate(raw_sentences):
        for word in sentence.words:
            normalised = _normalise_word(word.text)
            if not normalised:
                continue
            totals[sentence_idx] += 1
            raw_words.append(normalised)
            raw_owners.append(sentence_idx)

    gt_words = [
        normalised
        for sentence in gt_sentences
        for word in sentence.words
        if (normalised := _normalise_word(word.text))
    ]

    matched = [0] * len(raw_sentences)
    if raw_words and gt_words:
        matcher = SequenceMatcher(None, raw_words, gt_words, autojunk=False)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                matched[raw_owners[block.a + offset]] += 1

    return [
        matched[i] / totals[i] if totals[i] else 0.0
        for i in range(len(raw_sentences))
    ]


def derive_word_keep_flags(
    raw_sentences: list[Sentence],
    gt_sentences: list[Sentence],
) -> list[list[bool]]:
    """Per raw sentence, per word: True if that word survives into the human edit.

    Like :func:`derive_word_coverage` but keeps the per-word resolution instead of
    collapsing to a ratio — the honest granularity for scoring partial (word-level)
    cuts, where a stutter-trim inside a kept sentence must be judged word by word.
    """
    raw_words: list[str] = []
    owners: list[tuple[int, int]] = []
    flags: list[list[bool]] = []
    for sentence_idx, sentence in enumerate(raw_sentences):
        flags.append([False] * len(sentence.words))
        for word_idx, word in enumerate(sentence.words):
            normalised = _normalise_word(word.text)
            if not normalised:
                # Punctuation-only tokens carry no text signal; treat as kept so
                # they never count as a spurious missed cut.
                flags[sentence_idx][word_idx] = True
                continue
            raw_words.append(normalised)
            owners.append((sentence_idx, word_idx))

    gt_words = [
        normalised
        for sentence in gt_sentences
        for word in sentence.words
        if (normalised := _normalise_word(word.text))
    ]

    if raw_words and gt_words:
        matcher = SequenceMatcher(None, raw_words, gt_words, autojunk=False)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                sentence_idx, word_idx = owners[block.a + offset]
                flags[sentence_idx][word_idx] = True

    return flags


def _filter_outliers_iqr(values: list[float]) -> list[float]:
    """Remove outliers using the IQR method (> Q3 + 1.5*IQR)."""
    if len(values) < 4:
        return values
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[3 * n // 4]
    iqr = q3 - q1
    upper = q3 + 1.5 * iqr
    return [v for v in values if v <= upper]


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
    import json
    import statistics
    import subprocess

    def _get_duration(path: Path) -> float:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True,
        )
        return float(json.loads(probe.stdout)["format"]["duration"])

    p_dur = _get_duration(pipeline_video)
    gt_dur = _get_duration(ground_truth_video)

    # Local-gap drift: how much the spacing between *consecutive* matched anchors
    # diverges between pipeline and ground truth. Absolute start-offsets just
    # accumulate every upstream cut-amount difference, which double-counts the
    # same decision the word/duration metrics already measure and punishes
    # keeping human-kept content twice. Local drift instead measures *where* the
    # two timelines pull apart, not how much total material differs.
    anchors = sorted(
        ((m.pipeline_start, m.gt_start) for m in matches if m.pipeline_start > 0 and m.gt_start > 0),
        key=lambda t: t[1],
    )
    local_drifts: list[float] = []
    for (p0, g0), (p1, g1) in zip(anchors, anchors[1:]):
        local_drifts.append(abs((p1 - p0) - (g1 - g0)))

    filtered = _filter_outliers_iqr(local_drifts)
    n_outliers = len(local_drifts) - len(filtered)
    median_drift = statistics.median(filtered) if filtered else 0.0

    dur_ratio = min(p_dur, gt_dur) / max(p_dur, gt_dur) if max(p_dur, gt_dur) > 0 else 1.0

    max_acceptable_drift = 5.0
    timing_score = max(0.0, 1.0 - median_drift / max_acceptable_drift) if filtered else dur_ratio

    temporal_score = (dur_ratio + timing_score) / 2.0

    result = TemporalComparisonResult(
        pipeline_duration=round(p_dur, 2),
        ground_truth_duration=round(gt_dur, 2),
        duration_delta=round(p_dur - gt_dur, 2),
        anchor_offsets=[round(d, 3) for d in local_drifts],
        mean_offset=round(median_drift, 3),
        temporal_score=round(temporal_score, 4),
    )

    logger.info(
        "Temporal comparison: pipeline={:.1f}s gt={:.1f}s delta={:.1f}s "
        "median_local_drift={:.3f}s score={:.1%} ({} outliers filtered)",
        p_dur, gt_dur, p_dur - gt_dur, median_drift, temporal_score, n_outliers,
    )
    return result
