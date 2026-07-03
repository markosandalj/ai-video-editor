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

import re

from loguru import logger

from ai_video_editor.config.settings import EnrichmentConfig
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.enrich.models import EnrichmentResult, EnrichmentTag
from ai_video_editor.transcription.models import Sentence, Transcript

# Punctuation/whitespace only (Unicode letters, incl. č/ć/ž/š/đ, are \w).
_PUNCT_ONLY = re.compile(r"^[\W_]*$", re.UNICODE)


def _is_artifact(sentence: Sentence, max_words: int) -> bool:
    """A transcription junk frame: punctuation-only text or a tiny interjection.

    These ('.', '...', a stray one-word 'Ne.'/'Aaaaj.') are kept by the
    duplicate-anchored logic because they aren't duplicates or asides, yet they
    are never part of an edited lesson.
    """
    if _PUNCT_ONLY.match(sentence.text.strip()):
        return True
    return len(sentence.words) <= max_words

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


def _is_audio_evidence_flag(flag: DuplicateFlag) -> bool:
    """True for cut flags backed by acoustic evidence.

    The enrichment pass is text-only, so it can confidently keep a short phrase
    that *reads* like a natural transition ("I dobro.") while missing the cough
    and long pause that tell a human editor it was a flubbed restart.
    """
    return flag.note.startswith("Audio false start:")


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
        if _is_audio_evidence_flag(f):
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
    #    Two independent triggers: (a) a low-confidence aside/filler/incomplete
    #    tag, and (b) a transcription artifact (junk frame) the duplicate logic
    #    can't represent. Both stay tightly confidence-gated to protect precision.
    flagged_full_cut = {f.idx for f in kept_flags if not f.word_trims}
    extra = 0
    artifacts = 0
    for idx in range(n):
        if idx in flagged_full_cut:
            continue
        e = by_idx.get(idx)
        if e is None:
            continue

        tagged_cut = (
            e.keep_confidence < config.arbiter_extra_cut_confidence
            and bool(_EXTRA_CUT_TAGS & set(e.tags))
        )
        is_artifact = (
            e.keep_confidence < config.arbiter_artifact_confidence
            and _is_artifact(transcript.sentences[idx], config.arbiter_artifact_max_words)
        )
        if not (tagged_cut or is_artifact):
            continue

        reason = (
            FlagReason.ASIDE
            if EnrichmentTag.OFF_TOPIC_ASIDE in e.tags
            else FlagReason.FILLER
        )
        note = "Arbiter artifact-cut" if (is_artifact and not tagged_cut) else "Arbiter cut"
        kept_flags.append(DuplicateFlag(
            idx=idx,
            reason=reason,
            confidence=round(1.0 - e.keep_confidence / 100.0, 3),
            note=f"{note}: {e.rationale[:80]}",
        ))
        if tagged_cut:
            extra += 1
        else:
            artifacts += 1
        logger.info(
            "Arbiter {}: sentence {} (keep_confidence={:.0f}, tags={}) — {}",
            "extra-cut" if tagged_cut else "artifact-cut",
            idx, e.keep_confidence, [t.value for t in e.tags],
            transcript.sentences[idx].text[:60],
        )

    kept_flags.sort(key=lambda f: f.idx)
    logger.info(
        "Arbiter: {} un-cut, {} extra-cut, {} artifact-cut → {} flags (was {})",
        uncut, extra, artifacts, len(kept_flags), len(flags),
    )
    return kept_flags
