"""Section-based cutting with a strong LLM.

The tiered duplicate detector compares sentence *pairs* through a small model,
one mechanism at a time. That fragmentation is the root of two measured failure
modes: it deletes whole sentences when only a few flubbed words should go, and it
can't tell a recap from a retake because it never sees the surrounding passage.

This module inverts the design. It splits the transcript into paragraph-sized
sections, hands each (with context) to one capable model, and asks for the
verbatim spans to delete — whole sentences *or* partial spans. The model works
purely on text; the text→timeline mapping is a separate deterministic step that
uses the word-level timestamps we already have. Everything the model proposes is
validated before it becomes a cut: a span must exist verbatim, short
interjections are protected, and retake deletions are checked against the
keep-later rule and a recap time-gap. Output is the same ``DuplicateFlag`` /
``WordTrim`` objects the rest of the pipeline already consumes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.config.settings import SectionEditorConfig
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason, WordTrim
from ai_video_editor.llm import (
    LangChainModelConfig,
    build_chat_model,
)
from ai_video_editor.transcription.models import Sentence

_PUNCT = ".,;:!?\"'()-–—…"

_TYPE_TO_REASON: dict[str, FlagReason] = {
    "retake": FlagReason.DUPLICATE,
    "false_start": FlagReason.FALSE_START,
    "stutter": FlagReason.STUTTER,
    "filler": FlagReason.FILLER,
    "redundant": FlagReason.FILLER,
}

DeleteType = Literal["retake", "false_start", "stutter", "filler", "redundant"]


def _normalise(text: str) -> str:
    return text.lower().strip(_PUNCT).strip()


class SectionDeletion(BaseModel):
    """One span the model proposes to delete."""
    sentence_index: int = Field(
        ..., description="Global index (the [n] label) of the sentence the span is in"
    )
    verbatim_text: str = Field(
        ...,
        description=(
            "Exact text to delete, copied verbatim from the sentence. May be the "
            "whole sentence or a contiguous part of it."
        ),
    )
    delete_type: DeleteType = Field(
        ..., description="Why it should go: retake, false_start, stutter, filler, redundant"
    )
    reason: str = Field(default="", description="Short justification in Croatian")
    kept_index: int | None = Field(
        default=None,
        description="For retake: the [n] index of the surviving version of this thought",
    )


class SectionEdits(BaseModel):
    """The model's deletions for one section."""
    deletions: list[SectionDeletion] = Field(default_factory=list)


@dataclass
class SectionHealth:
    """Plumbing telemetry for one section-editor run.

    A model whose calls fail or return nothing scores exactly like a very
    conservative editor (zero cuts → recall 0, precision 1). These counters make
    that failure mode visible so a sweep leaderboard can't mistake a broken
    model for a careful one."""
    sections_total: int = 0
    sections_failed: int = 0
    section_retries: int = 0
    deletions_proposed: int = 0
    deletions_rejected_unverifiable: int = 0
    deletions_rejected_guardrail: int = 0
    flags_emitted: int = 0

    @property
    def section_failure_rate(self) -> float:
        return self.sections_failed / self.sections_total if self.sections_total else 0.0

    @property
    def rejection_rate(self) -> float:
        rejected = self.deletions_rejected_unverifiable + self.deletions_rejected_guardrail
        return rejected / self.deletions_proposed if self.deletions_proposed else 0.0

    @property
    def healthy(self) -> bool:
        """No failed sections and the model's spans mostly verified."""
        return self.sections_failed == 0 and (
            self.deletions_proposed == 0
            or self.deletions_rejected_unverifiable / self.deletions_proposed < 0.5
        )


@dataclass
class Section:
    """A window of the transcript: an owned range plus surrounding context.

    Deletions are only accepted for ``owned`` indices; ``ctx_lo``/``ctx_hi`` widen
    the view so a straddling retake pair is visible without being double-cut.
    """
    owned_lo: int
    owned_hi: int  # exclusive
    ctx_lo: int
    ctx_hi: int  # exclusive

    def owns(self, idx: int) -> bool:
        return self.owned_lo <= idx < self.owned_hi


SECTION_PROMPT = """Ti si iskusan video editor za edukacijske lekcije na hrvatskom. Dobivaš ODLOMAK transkripta snimke. Govornik snima u jednom dahu i često pogriješi pa ponovi — tvoj zadatak je označiti dijelove koje treba IZBACITI da montaža bude čista, a da se ne izgubi sadržaj.

ODGOVOR: Vrati isključivo validan JSON prema shemi. Bez Markdowna, bez dodatnog teksta.

ŠTO IZBACITI (delete_type):
- "retake": govornik je istu misao rekao dva puta (lažni pa ispravan pokušaj). Izbaci RANIJU verziju, zadrži KASNIJU. U kept_index navedi indeks verzije koju zadržavaš.
- "false_start": započeta pa prekinuta misao ("Dakle, ovaj-", "Kako bismo, kako bismo..."), nakon koje slijedi potpuna verzija.
- "stutter": ponovljene/zamuckane riječi UNUTAR rečenice ("Firstly, youngsters s- Firstly, youngsters spend..."). Izbaci SAMO zamuckani dio, ne cijelu rečenicu.
- "filler": prazne poštapalice bez sadržaja ("znači", "evo", "ovaj" same za sebe).
- "redundant": rečenica koja ne dodaje NIŠTA novo jer je sadržaj već rečen (npr. suvišno prepričavanje). Budi OPREZAN — ovo je najrizičnije.

KLJUČNA PRAVILA:
- verbatim_text MORA biti točno prepisan iz rečenice (može biti dio rečenice za djelomično izbacivanje).
- Za zamuckivanje/lažni početak izbaci samo pogrešni dio, ne cijelu rečenicu.
- Ako govornik ponovi kratku frazu radi naglaska ili se vraća temi kao PODSJETNIKU (velik vremenski razmak), NE briši — to nije retake.
- Kad nisi siguran, radije NE briši (montažer lakše doda cut nego što vrati izgubljen sadržaj).
- Označavaj SAMO rečenice s indeksima koji su u rasponu za uređivanje: {editable_range}. Rečenice označene (kontekst) su samo za razumijevanje — NE vraćaj brisanja za njih.

Odlomak (indeksi su globalni):
{section_text}"""


def _build_sections(sentences: list[Sentence], cfg: SectionEditorConfig) -> list[Section]:
    """Tile the transcript into disjoint owned ranges, snapping boundaries to pauses."""
    n = len(sentences)
    if n == 0:
        return []

    word_counts = [max(1, len(s.words)) for s in sentences]
    sections: list[Section] = []
    start = 0
    while start < n:
        words = 0
        end = start
        # A soft boundary is allowed once we pass target_words; force one at max_words.
        best_pause_end: int | None = None
        best_pause_gap = -1.0
        while end < n:
            words += word_counts[end]
            end += 1
            if end >= n:
                break
            gap = sentences[end].start - sentences[end - 1].end
            if words >= cfg.target_words and gap > best_pause_gap:
                best_pause_gap = gap
                best_pause_end = end
            if words >= cfg.max_words:
                # Prefer the largest pause seen since target; else cut here.
                end = best_pause_end or end
                break
        owned_hi = end
        ctx_lo = max(0, start - cfg.overlap_sentences)
        ctx_hi = min(n, owned_hi + cfg.overlap_sentences)
        sections.append(Section(start, owned_hi, ctx_lo, ctx_hi))
        start = owned_hi
    return sections


def _render_section(sentences: list[Sentence], section: Section) -> str:
    lines: list[str] = []
    for j in range(section.ctx_lo, section.ctx_hi):
        tag = "" if section.owns(j) else " (kontekst)"
        lines.append(f'[{j}]{tag} "{sentences[j].text}"')
    return "\n".join(lines)


def _locate_span(
    sentence: Sentence, verbatim_text: str, cfg: SectionEditorConfig
) -> tuple[int, int, float, float] | None:
    """Find the contiguous word run in *sentence* matching *verbatim_text*.

    Returns ``(word_start, word_end_inclusive, match_ratio, sentence_coverage)``
    in original word indices, or None if the text can't be located well enough.
    """
    indexed = [
        (i, norm) for i, w in enumerate(sentence.words) if (norm := _normalise(w.text))
    ]
    if not indexed:
        return None
    sent_norms = [norm for _, norm in indexed]
    target = [t for t in (_normalise(w) for w in verbatim_text.split()) if t]
    if not target:
        return None

    matcher = SequenceMatcher(None, sent_norms, target, autojunk=False)
    matched_positions = [
        block.a + off
        for block in matcher.get_matching_blocks()
        for off in range(block.size)
    ]
    if not matched_positions:
        return None

    lo_pos, hi_pos = min(matched_positions), max(matched_positions)
    match_ratio = len(set(matched_positions)) / len(target)
    if match_ratio < cfg.min_span_match_ratio:
        return None

    word_start = indexed[lo_pos][0]
    word_end = indexed[hi_pos][0]
    sentence_coverage = (hi_pos - lo_pos + 1) / len(indexed)
    return word_start, word_end, match_ratio, sentence_coverage


def _deletion_to_flag(
    deletion: SectionDeletion,
    sentences: list[Sentence],
    cfg: SectionEditorConfig,
    health: SectionHealth | None = None,
) -> DuplicateFlag | None:
    """Map one validated deletion to a flag, applying the guardrails."""
    health = health if health is not None else SectionHealth()
    idx = deletion.sentence_index
    if not (0 <= idx < len(sentences)):
        health.deletions_rejected_unverifiable += 1
        return None

    located = _locate_span(sentences[idx], deletion.verbatim_text, cfg)
    if located is None:
        logger.info(
            "Section editor: rejecting unverifiable span in sentence {} — {!r}",
            idx, deletion.verbatim_text[:60],
        )
        health.deletions_rejected_unverifiable += 1
        return None
    word_start, word_end, _ratio, coverage = located

    reason = _TYPE_TO_REASON.get(deletion.delete_type, FlagReason.FILLER)
    full_sentence = coverage >= cfg.full_sentence_threshold
    confidence = 0.9
    notes: list[str] = [deletion.reason] if deletion.reason else []

    # Guardrail: protect short recurring interjections from whole-sentence retake cuts.
    if (
        full_sentence
        and deletion.delete_type == "retake"
        and len(sentences[idx].words) < cfg.protect_min_words
    ):
        logger.info(
            "Section editor: protecting short interjection sentence {} ({!r})",
            idx, sentences[idx].text[:40],
        )
        health.deletions_rejected_guardrail += 1
        return None

    # Guardrail: reject retake proposals that would require human review. With
    # no annotation queue, lowering confidence would still auto-cut the flag.
    if deletion.delete_type == "retake" and deletion.kept_index is not None:
        kept = deletion.kept_index
        if 0 <= kept < len(sentences):
            if kept < idx:
                logger.info(
                    "Section editor: rejecting sentence {} — model kept earlier take {}",
                    idx,
                    kept,
                )
                health.deletions_rejected_guardrail += 1
                return None
            gap = abs(sentences[kept].start - sentences[idx].start)
            if gap > cfg.retake_max_gap_s:
                logger.info(
                    "Section editor: rejecting sentence {} — twin is {:.0f}s away (recap risk)",
                    idx,
                    gap,
                )
                health.deletions_rejected_guardrail += 1
                return None

    # Guardrail: risky unique-content removals stay kept until a review system exists.
    if deletion.delete_type in cfg.reject_types:
        logger.info(
            "Section editor: rejecting sentence {} — protected deletion type {}",
            idx,
            deletion.delete_type,
        )
        health.deletions_rejected_guardrail += 1
        return None

    word_trims: list[WordTrim] = []
    if not full_sentence:
        word_trims = [
            WordTrim(
                start=sentences[idx].words[word_start].start,
                end=sentences[idx].words[word_end].end,
            )
        ]

    return DuplicateFlag(
        idx=idx,
        reason=reason,
        confidence=confidence,
        note=" | ".join(n for n in notes if n),
        word_trims=word_trims,
    )


def _merge_flags(flags: list[DuplicateFlag]) -> list[DuplicateFlag]:
    """Collapse multiple deletions on the same sentence.

    A whole-sentence cut subsumes any partial trims on that sentence; several
    partial trims on one sentence are unioned into a single flag.
    """
    by_idx: dict[int, list[DuplicateFlag]] = {}
    for f in flags:
        by_idx.setdefault(f.idx, []).append(f)

    merged: list[DuplicateFlag] = []
    for idx, group in by_idx.items():
        full = [f for f in group if not f.word_trims]
        if full:
            merged.append(max(full, key=lambda f: f.confidence))
            continue
        trims: list[WordTrim] = []
        for f in group:
            trims.extend(f.word_trims)
        trims.sort(key=lambda t: t.start)
        base = max(group, key=lambda f: f.confidence)
        merged.append(base.model_copy(update={"word_trims": trims}))
    merged.sort(key=lambda f: f.idx)
    return merged


def _edit_section(
    sentences: list[Sentence],
    section: Section,
    llm,
) -> list[SectionDeletion]:
    prompt = SECTION_PROMPT.format(
        editable_range=f"{section.owned_lo}–{section.owned_hi - 1}",
        section_text=_render_section(sentences, section),
    )
    structured = llm.with_structured_output(SectionEdits)
    result: SectionEdits = structured.invoke(prompt)
    # Only accept deletions the section owns — dedups the overlap context.
    return [d for d in result.deletions if section.owns(d.sentence_index)]


def _edit_section_with_retry(
    sentences: list[Sentence],
    section: Section,
    llm,
    cfg: SectionEditorConfig,
    health: SectionHealth,
) -> list[SectionDeletion]:
    """Retry structured-output failures that occur after a successful HTTP response."""
    for attempt in range(1, cfg.section_max_attempts + 1):
        try:
            return _edit_section(sentences, section, llm)
        except Exception as exc:
            if attempt >= cfg.section_max_attempts:
                raise
            health.section_retries += 1
            delay = cfg.section_retry_backoff_s * attempt
            logger.warning(
                "Section editor: attempt {}/{} failed ({}: {}); retrying in {:.1f}s",
                attempt,
                cfg.section_max_attempts,
                type(exc).__name__,
                str(exc)[:120],
                delay,
            )
            if delay:
                time.sleep(delay)

    raise AssertionError("section retry loop exhausted unexpectedly")


def detect_section_edits(
    sentences: list[Sentence],
    cfg: SectionEditorConfig | None = None,
    *,
    llm_config: LangChainModelConfig | None = None,
    health: SectionHealth | None = None,
) -> list[DuplicateFlag]:
    """Run the section editor and return removal flags (same contract as
    ``detect_duplicates``). Best-effort per section: a failed section is logged
    and skipped rather than aborting the whole video. Pass *health* to collect
    plumbing telemetry (failed sections, rejected spans) — essential when
    comparing models, because a model whose calls fail looks identical to a
    conservative one in the cut metrics."""
    if cfg is None:
        cfg = SectionEditorConfig()
    health = health if health is not None else SectionHealth()
    if len(sentences) < 2:
        return []

    llm = build_chat_model(llm_config or cfg.llm)
    sections = _build_sections(sentences, cfg)
    health.sections_total += len(sections)
    logger.info(
        "Section editor: {} sentences → {} sections (target={}w, max={}w)",
        len(sentences), len(sections), cfg.target_words, cfg.max_words,
    )

    raw_flags: list[DuplicateFlag] = []
    for si, section in enumerate(sections):
        try:
            deletions = _edit_section_with_retry(sentences, section, llm, cfg, health)
        except Exception:
            logger.exception(
                "Section editor: section {}/{} ([{}–{}]) failed — skipping",
                si + 1, len(sections), section.owned_lo, section.owned_hi - 1,
            )
            health.sections_failed += 1
            continue
        health.deletions_proposed += len(deletions)
        for d in deletions:
            flag = _deletion_to_flag(d, sentences, cfg, health)
            if flag is not None:
                raw_flags.append(flag)

    flags = _merge_flags(raw_flags)
    health.flags_emitted += len(flags)
    full = sum(1 for f in flags if not f.word_trims)
    trims = sum(1 for f in flags if f.word_trims)
    logger.info(
        "Section editor: {} flags ({} full-sentence, {} word-trim) — "
        "{}/{} sections failed, {} retries, {} spans rejected",
        len(flags), full, trims,
        health.sections_failed, health.sections_total,
        health.section_retries,
        health.deletions_rejected_unverifiable + health.deletions_rejected_guardrail,
    )
    return flags
