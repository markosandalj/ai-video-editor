"""Dev-only diff view: raw transcript as a canvas, with each editor's cuts marked.

This powers a throwaway comparison UI (not part of the production app). For one
video it overlays two independent edits on the *same* raw transcript:

* **Pipeline** — derived exactly from our EDL: a raw word is kept iff its
  midpoint lands inside a KEEP decision. No re-transcription, no alignment.
* **Human** — derived by aligning the raw transcript to the human-edited video's
  re-transcription (the QA ground truth). Sentence-level alignment is the
  order-preserving monotonic match QA already uses; within a kept sentence, a
  word-level LCS marks which raw words survived. A raw word/sentence missing from
  the human edit is a human cut.

The frontend renders the raw transcript and strikes through whatever the active
editor removed, so disagreements (we cut what the human kept, or vice versa) are
visible at a glance.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.enrich.cache import load_cached_enrichment
from ai_video_editor.qa.ground_truth import _backtrack_lcs, _lcs_length_table
from ai_video_editor.transcription.cache import cache_path_for
from ai_video_editor.transcription.models import Sentence, Transcript

_STRIP = ".,;:!?\"'()-–—…«»„“”"

# Isolated unmatched runs no longer than this many words (flanked by kept words
# inside the same sentence) are treated as transcription noise rather than human
# cuts. The raw STT and the edited-video STT disagree on spelling/tokenisation
# (e.g. "obadvije" vs "oba dvije"), which would otherwise show as spurious
# strike-throughs inside content the human plainly kept.
_BRIDGE_GAP = 2


def _normalise(text: str) -> str:
    return text.lower().strip(_STRIP)


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------

class DiffWord(BaseModel):
    text: str
    start: float
    end: float
    pipeline_kept: bool
    human_kept: bool


class DiffSentence(BaseModel):
    idx: int
    text: str
    start: float
    end: float
    pipeline_kept: bool
    human_kept: bool
    keep_confidence: float | None = None
    status: str = ""
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""
    words: list[DiffWord] = Field(default_factory=list)


class DiffSummary(BaseModel):
    has_ground_truth: bool
    raw_sentences: int
    raw_words: int
    pipeline_kept_sentences: int
    human_kept_sentences: int
    pipeline_kept_words: int
    human_kept_words: int
    # Sentence-level agreement (positive class = KEEP).
    agree_keep: int
    agree_cut: int
    pipeline_only_cut: int  # we cut, human kept  → over-cut (false positive)
    human_only_cut: int  # human cut, we kept   → missed cut (false negative)


class DiffVideo(BaseModel):
    id: str
    source_name: str
    duration: float
    has_ground_truth: bool


class DiffPayload(BaseModel):
    video: DiffVideo
    summary: DiffSummary
    sentences: list[DiffSentence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def ground_truth_path_for(video_path: Path) -> Path:
    """`<name>-raw.mp4` → `<name>-edited.qa-transcript.json` (human edit re-transcribed)."""
    stem = video_path.stem
    name = stem[:-4] if stem.endswith("-raw") else stem
    return video_path.with_name(f"{name}-edited.qa-transcript.json")


def _pipeline_kept_word(midpoint: float, decisions: list) -> bool:
    for d in decisions:
        if d.start <= midpoint <= d.end:
            return d.action == EditAction.KEEP
    return False


def _human_word_kept_mask(
    raw_sentences: list[Sentence], gt_sentences: list[Sentence]
) -> dict[int, list[bool]]:
    """Per-raw-word human-keep flags via a *global* word-level LCS.

    The human-edited video is re-transcribed independently, so its sentence
    boundaries don't line up with the raw transcript's: two raw sentences can be
    merged into one GT sentence (or split). A 1:1 sentence alignment then falsely
    flags the "extra" raw sentence as cut. Aligning the full raw word stream
    against the full GT word stream sidesteps chunking entirely -- a raw word is
    "kept" iff it participates in the longest common subsequence with the GT
    words, regardless of which sentence either side put it in.

    Two refinements keep the visualisation honest:
    - Punctuation-only / empty-normalised tokens are neutral (always kept) so
      they never add strike noise.
    - A short unmatched run (<= ``_BRIDGE_GAP`` words) *flanked by kept words
      inside the same sentence* is bridged back to kept. A human hard-cut
      removes a contiguous clause, not one or two interior words; such tiny
      runs are transcription/tokenisation artifacts (e.g. raw "obadvije" vs GT
      "oba dvije", or raw "ne mogu" vs GT "nemogu"). Bridging is kept strictly
      *within* a sentence and requires kept flanks, so a fully-removed sentence
      (whose words have no kept neighbour) is never resurrected.
    """
    masks: dict[int, list[bool]] = {
        i: [True] * len(s.words) for i, s in enumerate(raw_sentences)
    }

    raw_flat: list[str] = []
    raw_ref: list[tuple[int, int]] = []  # (sentence_idx, word_pos) per flat entry
    for sidx, sent in enumerate(raw_sentences):
        for wpos, word in enumerate(sent.words):
            norm = _normalise(word.text)
            if norm:
                masks[sidx][wpos] = False  # promoted to kept only if in the LCS
                raw_flat.append(norm)
                raw_ref.append((sidx, wpos))

    gt_flat = [n for s in gt_sentences for w in s.words if (n := _normalise(w.text))]

    if raw_flat and gt_flat:
        dp = _lcs_length_table(raw_flat, gt_flat)
        for pos in _backtrack_lcs(dp, raw_flat, gt_flat):
            sidx, wpos = raw_ref[pos]
            masks[sidx][wpos] = True

    for mask in masks.values():
        n = len(mask)
        i = 0
        while i < n:
            if mask[i]:
                i += 1
                continue
            j = i
            while j < n and not mask[j]:
                j += 1
            # Run [i, j) is unmatched. Bridge it only when it is genuinely
            # interior (kept words on both sides) and short enough to be a
            # transcription artifact rather than a real clause-level cut.
            if 0 < i and j < n and (j - i) <= _BRIDGE_GAP:
                for k in range(i, j):
                    mask[k] = True
            i = j

    return masks


def build_diff_payload(video_path: Path) -> DiffPayload:
    transcript_path = cache_path_for(video_path)
    edl_path = video_path.with_suffix(".edl.json")
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")
    if not edl_path.exists():
        raise FileNotFoundError(f"EDL not found: {edl_path}")

    transcript = Transcript.model_validate_json(transcript_path.read_text("utf-8"))
    edl = EditDecisionList.model_validate_json(edl_path.read_text("utf-8"))
    enrich = load_cached_enrichment(video_path)
    enrich_map = enrich.by_index() if enrich is not None else {}

    gt_path = ground_truth_path_for(video_path)
    gt: Transcript | None = None
    if gt_path.exists():
        gt = Transcript.model_validate_json(gt_path.read_text("utf-8"))

    raw_sentences = transcript.sentences

    # Human keep map from a chunking-immune global word LCS (see helper docstring).
    human_word_kept: dict[int, list[bool]] = (
        _human_word_kept_mask(raw_sentences, gt.sentences) if gt is not None else {}
    )

    sentences: list[DiffSentence] = []
    raw_words = pipeline_kept_words = human_kept_words = 0
    pipeline_kept_sentences = human_kept_sentences = 0
    agree_keep = agree_cut = pipeline_only_cut = human_only_cut = 0

    for sidx, sent in enumerate(raw_sentences):
        e = enrich_map.get(sidx)
        word_human = human_word_kept.get(sidx)

        words: list[DiffWord] = []
        kept_pipeline = kept_human = 0
        for pos, w in enumerate(sent.words):
            mid = (w.start + w.end) / 2
            p_kept = _pipeline_kept_word(mid, edl.decisions)
            if gt is None:
                h_kept = True
            else:
                h_kept = word_human[pos] if word_human and pos < len(word_human) else True
            words.append(
                DiffWord(text=w.text, start=w.start, end=w.end, pipeline_kept=p_kept, human_kept=h_kept)
            )
            raw_words += 1
            if p_kept:
                kept_pipeline += 1
                pipeline_kept_words += 1
            if h_kept:
                kept_human += 1
                if gt is not None:
                    human_kept_words += 1

        total = len(sent.words)
        sent_pipeline_kept = (kept_pipeline / total >= 0.5) if total else False
        sent_human_kept = (kept_human / total >= 0.5) if total else True
        if sent_pipeline_kept:
            pipeline_kept_sentences += 1
        # Without ground truth the human side is unknown, not "all kept": keep
        # the summary counters consistent with human_kept_words (also gated).
        if sent_human_kept and gt is not None:
            human_kept_sentences += 1

        if gt is not None:
            if sent_pipeline_kept and sent_human_kept:
                agree_keep += 1
            elif not sent_pipeline_kept and not sent_human_kept:
                agree_cut += 1
            elif not sent_pipeline_kept and sent_human_kept:
                pipeline_only_cut += 1
            else:
                human_only_cut += 1

        sentences.append(
            DiffSentence(
                idx=sidx,
                text=sent.text,
                start=sent.start,
                end=sent.end,
                pipeline_kept=sent_pipeline_kept,
                human_kept=sent_human_kept if gt is not None else True,
                keep_confidence=e.keep_confidence if e is not None else None,
                status=e.status.value if e is not None else "",
                tags=[t.value for t in e.tags] if e is not None else [],
                rationale=e.rationale if e is not None else "",
                words=words,
            )
        )

    summary = DiffSummary(
        has_ground_truth=gt is not None,
        raw_sentences=len(raw_sentences),
        raw_words=raw_words,
        pipeline_kept_sentences=pipeline_kept_sentences,
        human_kept_sentences=human_kept_sentences,
        pipeline_kept_words=pipeline_kept_words,
        human_kept_words=human_kept_words,
        agree_keep=agree_keep,
        agree_cut=agree_cut,
        pipeline_only_cut=pipeline_only_cut,
        human_only_cut=human_only_cut,
    )
    video = DiffVideo(
        id=video_path.stem,
        source_name=video_path.name,
        duration=edl.total_duration,
        has_ground_truth=gt is not None,
    )
    return DiffPayload(video=video, summary=summary, sentences=sentences)
