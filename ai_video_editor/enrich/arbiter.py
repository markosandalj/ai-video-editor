"""Use the independent enrichment score to arbitrate the cut/keep decisions.

The enrichment pass scores every sentence on its own (it never sees the
pipeline's verdict). Measured against human-edited ground truth it is a better
keep/cut classifier than the tiered duplicate pipeline, so here we let it
correct the pipeline's two worst failure modes:

1. Wrong cuts — the duplicate detector cuts one of two sentences a human kept
   (a recap, not a retake). If enrichment is confident the sentence belongs,
   drop the cut flag (un-cut it).
2. Missed cuts — a kept sentence that is really an aside / filler the
   duplicate-anchored logic cannot represent. If enrichment is confident it does
   not belong AND it carries a matching tag, add a cut flag.

The second direction is deliberately tag-gated and conservative: over-keeps that
are genuine asides are the safe target; trimming on low confidence alone would
hurt precision.
"""
from __future__ import annotations

from loguru import logger

from ai_video_editor.config.settings import EnrichmentConfig
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.enrich.models import EnrichmentResult, EnrichmentTag
from ai_video_editor.transcription.models import Transcript

# Only these tags justify an extra cut on top of a low keep_confidence.
# REPETITION_RESIDUE is deliberately excluded: a 18-video threshold sweep showed
# it was the single largest source of wrong extra-cuts (the enrichment tags
# pedagogical restatements the human kept as "repetition"), adding ~40% more
# false positives for almost no accuracy gain. Asides / filler / incomplete
# thoughts are the safe, unambiguous targets.
_EXTRA_CUT_TAGS = {
    EnrichmentTag.OFF_TOPIC_ASIDE,
    EnrichmentTag.FILLER_PHRASE,
    EnrichmentTag.INCOMPLETE_THOUGHT,
}


def apply_enrichment_arbiter(
    flags: list[DuplicateFlag],
    transcript: Transcript,
    enrichment: EnrichmentResult,
    config: EnrichmentConfig,
) -> list[DuplicateFlag]:
    """Return a revised flag list after letting enrichment arbitrate.

    Word-trim (stutter) flags are left untouched — they are sub-sentence and the
    arbiter operates at sentence granularity.
    """
    if not config.arbiter_enabled:
        return flags

    by_idx = enrichment.by_index()
    n = len(transcript.sentences)

    # 1. Un-cut full-sentence flags the enrichment is confident about.
    kept_flags: list[DuplicateFlag] = []
    uncut = 0
    for f in flags:
        if f.word_trims:
            kept_flags.append(f)
            continue
        e = by_idx.get(f.idx)
        if e is not None and e.keep_confidence >= config.arbiter_uncut_confidence:
            uncut += 1
            logger.info(
                "Arbiter un-cut: sentence {} (keep_confidence={:.0f}, was {}) — {}",
                f.idx, e.keep_confidence, f.reason.value, e.rationale[:60],
            )
            continue
        kept_flags.append(f)

    # 2. Add cuts for confidently-unwanted, tagged sentences still kept.
    flagged_full_cut = {f.idx for f in kept_flags if not f.word_trims}
    extra = 0
    for idx in range(n):
        if idx in flagged_full_cut:
            continue
        e = by_idx.get(idx)
        if e is None:
            continue
        if e.keep_confidence >= config.arbiter_extra_cut_confidence:
            continue
        if not (_EXTRA_CUT_TAGS & set(e.tags)):
            continue
        reason = (
            FlagReason.ASIDE
            if EnrichmentTag.OFF_TOPIC_ASIDE in e.tags
            else FlagReason.FILLER
        )
        kept_flags.append(DuplicateFlag(
            idx=idx,
            reason=reason,
            confidence=round(1.0 - e.keep_confidence / 100.0, 3),
            note=f"Arbiter cut: {e.rationale[:80]}",
        ))
        extra += 1
        logger.info(
            "Arbiter extra-cut: sentence {} (keep_confidence={:.0f}, tags={}) — {}",
            idx, e.keep_confidence, [t.value for t in e.tags], e.rationale[:60],
        )

    kept_flags.sort(key=lambda f: f.idx)
    logger.info(
        "Arbiter: {} un-cut, {} extra-cut → {} flags (was {})",
        uncut, extra, len(kept_flags), len(flags),
    )
    return kept_flags
