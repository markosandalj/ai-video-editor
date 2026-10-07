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
from dataclasses import asdict, dataclass
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.config.settings import SectionEditorConfig
from ai_video_editor.duplicate.false_start_audio import AudioFalseStartCandidate
from ai_video_editor.duplicate.local_corrections import detect_local_corrections
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason, KeptSpan, RejectedCut, WordTrim
from ai_video_editor.duplicate.safeguards import protect_kept_spans
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
    "redundant": FlagReason.FILLER,
}

DeleteType = Literal["retake", "false_start", "stutter", "redundant"]


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
        ..., description="Why it should go: retake, false_start, stutter, redundant"
    )
    reason: str = Field(default="", description="Short justification in Croatian")
    kept_index: int | None = Field(
        default=None,
        description="Required for retake and false_start: [n] index containing the later replacement.",
    )
    kept_verbatim_text: str | None = Field(
        default=None,
        description="Required for retake and false_start: exact contiguous text of the later replacement that must stay. It must replace ALL the content being deleted.",
    )


class SectionEdits(BaseModel):
    """The model's deletions for one section."""
    deletions: list[SectionDeletion] = Field(default_factory=list)


class SectionProposalTrace(BaseModel):
    """One model proposal and the deterministic disposition it received."""

    deletion: SectionDeletion
    disposition: Literal[
        "accepted", "rejected_unverifiable", "rejected_guardrail"
    ]
    flag: DuplicateFlag | None = None
    detail: str = ""
    model_id: str = ""


class SectionTrace(BaseModel):
    """Durable evidence for every proposal made during one video run."""

    proposals: list[SectionProposalTrace] = Field(default_factory=list)
    audio_candidates: list[AudioFalseStartCandidate] = Field(default_factory=list)
    protected_spans: list[KeptSpan] = Field(default_factory=list)
    rejected_conflicts: list[RejectedCut] = Field(default_factory=list)
    local_flags: list[DuplicateFlag] = Field(default_factory=list)
    health: dict[str, int] = Field(default_factory=dict)


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
    sections_fallback: int = 0
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

POSTUPAK ODABIRA ZADRŽANE VERZIJE:
Kad govornik nekoliko puta pokušava izreći istu izjavu, prvo pročitaj sve pokušaje i odredi završnu potpunu verziju. Tek zatim predloži ranije dijelove za brisanje. Ranije dijelove briši samo kada ih ta verzija zamjenjuje bez gubitka jedinstvenih informacija. Završni pokušaj nije automatski bolji samo zato što je posljednji.

ODGOVOR: Vrati isključivo validan JSON prema shemi. Bez Markdowna, bez dodatnog teksta.

ŠTO IZBACITI (delete_type):
- "retake": govornik je istu misao rekao dva puta (lažni pa ispravan pokušaj). Izbaci samo dio RANIJE verzije koji je u cijelosti zamijenjen KASNIJOM.
- "false_start": započeta pa prekinuta misao ("Dakle, ovaj-", "Kako bismo, kako bismo..."), nakon koje slijedi potpuna verzija.
- "stutter": ponovljene/zamuckane riječi UNUTAR rečenice ("Firstly, youngsters s- Firstly, youngsters spend..."). Izbaci SAMO zamuckani dio, ne cijelu rečenicu.
- "redundant": rečenica koja ne dodaje NIŠTA novo jer je sadržaj već rečen (npr. suvišno prepričavanje). Budi OPREZAN — ovo je najrizičnije.

RAZLIKA IZMEĐU PONOVNOG POKUŠAJA I SUVIŠNOG OBJAŠNJAVANJA:
Ako govornik ponovno započinje istu izjavu i kasnije je dovršava ili ispravlja, raniji pokušaj označi kao retake i navedi točnu kasniju zamjenu. Redundant označava višak u objašnjavanju, a ne neuspjeli snimateljski pokušaj. Namjerni sažetak i ponavljanje radi naglaska sačuvaj. Retake predlaži samo uz jasnu kasniju zamjenu bez gubitka sadržaja.

KLJUČNA PRAVILA:
- Sačuvaj prirodan govorni stil. Poštapalice, povezne riječi i oklijevanja nisu sami po sebi razlog za rezanje. Ukloni ih samo ako pripadaju jasno pogrešnom ili prekinutom pokušaju koji je zamijenjen kasnijim ispravnim izgovorom.
- verbatim_text MORA biti točno prepisan iz rečenice (može biti dio rečenice za djelomično izbacivanje).
- Za retake i false_start OBAVEZNO navedi kept_index i kept_verbatim_text: točan kasniji tekst koji zamjenjuje CIJELI predloženi rez. Taj tekst mora ostati u konačnom videu. Ako nema jasne zamjene, ne predlaži takav rez.
- Ako kasniji pokušaj ponavlja samo nastavak, sačuvaj koristan uvod ranijeg pokušaja. Izbaci samo zamijenjeni nastavak; zajednička tema nije dokaz da je cijela ranija rečenica suvišna.
- Kratak ispravak pojma, broja ili formule nosi sadržaj lekcije. Sačuvaj ispravnu verziju i ukloni samo pogrešni dio koji ona zamjenjuje. Ispravak nije filler čak ni nakon duge pauze ili šuma.
- Audio kandidati su samo trag za provjeru. Pauza, šum i mali broj riječi NISU dovoljan razlog za brisanje. Provjeri značenje u kontekstu; bez potvrde iz sadržaja zadrži kandidat.
- Ne briši tekst koji si drugom prijedlogu naveo kao kept_verbatim_text. Navedi završnu zadržanu verziju umjesto lanca međusobno izbrisanih zamjena.
- Za zamuckivanje/lažni početak izbaci samo pogrešni dio, ne cijelu rečenicu.
- Ako govornik ponovi kratku frazu radi naglaska ili se vraća temi kao PODSJETNIKU (velik vremenski razmak), NE briši — to nije retake.
- Kad nisi siguran, radije NE briši (montažer lakše doda cut nego što vrati izgubljen sadržaj).
- Označavaj SAMO rečenice s indeksima koji su u rasponu za uređivanje: {editable_range}. Rečenice označene (kontekst) su samo za razumijevanje — NE vraćaj brisanja za njih.

Odlomak (indeksi su globalni):
{section_text}

Audio kandidati za provjeru (nisu naredbe za brisanje):
{audio_candidates}

PROVJERA PREOSTALOG TEKSTA PRIJE ODGOVORA:
Prije konačnog odgovora provjeri tekst koji ostaje nakon svih predloženih rezova. Ako ostaju dva snimateljska pokušaja iste izjave, provjeri može li se raniji ukloniti uz postojeća pravila. Provjeri i da su ostali koristan uvod, ispravni pojmovi i svi dijelovi navedeni kao zadržana zamjena. Vrati samo konačni JSON.
"""


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
    sentence: Sentence, verbatim_text: str
) -> tuple[int, int, float, float] | None:
    """Find the contiguous word run in *sentence* matching *verbatim_text*.

    Returns ``(word_start, word_end_inclusive, match_ratio, sentence_coverage)``
    in original word indices, or None if the text can't be located well enough.
    """
    # A grammar correction may put several lexical tokens in one timed Word.
    # Match lexical tokens while retaining original, indivisible time spans.
    indexed = [
        (i, norm) for i, w in enumerate(sentence.words)
        for token in w.text.split() if (norm := _normalise(token))
    ]
    if not indexed:
        return None
    sent_norms = [norm for _, norm in indexed]
    target = [t for t in (_normalise(w) for w in verbatim_text.split()) if t]
    if not target:
        return None

    matches = [
        start for start in range(len(sent_norms) - len(target) + 1)
        if sent_norms[start:start + len(target)] == target
        and (start == 0 or indexed[start - 1][0] != indexed[start][0])
        and (start + len(target) == len(indexed)
             or indexed[start + len(target) - 1][0] != indexed[start + len(target)][0])
    ]
    # Never bridge unmatched words or guess which occurrence the model meant.
    if len(matches) != 1:
        return None
    lo_pos = matches[0]
    hi_pos = lo_pos + len(target) - 1
    word_start = indexed[lo_pos][0]
    word_end = indexed[hi_pos][0]
    sentence_coverage = (hi_pos - lo_pos + 1) / len(indexed)
    return word_start, word_end, 1.0, sentence_coverage


def _deletion_to_flag(
    deletion: SectionDeletion,
    sentences: list[Sentence],
    cfg: SectionEditorConfig,
    health: SectionHealth | None = None,
    *,
    rejection_reasons: list[str] | None = None,
) -> DuplicateFlag | None:
    """Map one validated deletion to a flag, applying the guardrails."""
    health = health if health is not None else SectionHealth()

    def reject(message: str, *, unverifiable: bool = False) -> None:
        if unverifiable:
            health.deletions_rejected_unverifiable += 1
        else:
            health.deletions_rejected_guardrail += 1
        if rejection_reasons is not None:
            rejection_reasons.append(message)
        logger.info("Section editor: rejecting [{}] — {}", deletion.sentence_index, message)

    idx = deletion.sentence_index
    if not (0 <= idx < len(sentences)):
        return reject("Sentence index is outside the transcript", unverifiable=True)

    located = _locate_span(sentences[idx], deletion.verbatim_text)
    if located is None:
        return reject("Deletion text is absent, non-contiguous or ambiguous", unverifiable=True)
    word_start, word_end, _ratio, _coverage = located

    reason = _TYPE_TO_REASON[deletion.delete_type]
    full_sentence = word_start == 0 and word_end == len(sentences[idx].words) - 1
    confidence = 0.9
    notes: list[str] = [deletion.reason] if deletion.reason else []

    # Guardrail: protect short recurring interjections from whole-sentence retake cuts.
    if (
        full_sentence
        and deletion.delete_type == "retake"
        and len(sentences[idx].words) < cfg.protect_min_words
    ):
        return reject("Short whole-sentence retake is protected")

    # Guardrail: reject retake proposals that would require human review. With
    # no annotation queue, lowering confidence would still auto-cut the flag.
    kept_spans: list[KeptSpan] = []
    if deletion.delete_type in {"retake", "false_start"}:
        kept = deletion.kept_index
        if kept is None or not (0 <= kept < len(sentences)) or not deletion.kept_verbatim_text:
            return reject("Missing or invalid retained replacement")
        kept_location = _locate_span(sentences[kept], deletion.kept_verbatim_text)
        if kept_location is None:
            return reject("Replacement text is absent, non-contiguous or ambiguous", unverifiable=True)
        kept_start, kept_end, _, _ = kept_location
        replacement = KeptSpan(
            sentence_index=kept,
            start=sentences[kept].words[kept_start].start,
            end=sentences[kept].words[kept_end].end,
            text=" ".join(w.text for w in sentences[kept].words[kept_start:kept_end + 1]),
        )
        cut_end = sentences[idx].words[word_end].end
        if kept < idx or replacement.start < cut_end or replacement.end <= replacement.start:
            return reject("Replacement must follow and not overlap the deletion")
        if replacement.start - cut_end > cfg.retake_max_gap_s:
            return reject("Replacement is too far away (recap risk)")
        kept_spans.append(replacement)
    elif deletion.kept_index is not None or deletion.kept_verbatim_text is not None:
        return reject("Replacement supplied for a deletion type that does not use one")

    # Guardrail: risky unique-content removals stay kept until a review system exists.
    if deletion.delete_type in cfg.reject_types:
        return reject(f"Protected deletion type: {deletion.delete_type}")

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
        source="section_editor",
        kept_spans=kept_spans,
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
            base = max(full, key=lambda f: f.confidence)
            merged.append(base.model_copy(update={
                "kept_spans": [span for flag in group for span in flag.kept_spans],
            }))
            continue
        by_reason: dict[FlagReason, list[DuplicateFlag]] = {}
        for flag in group:
            by_reason.setdefault(flag.reason, []).append(flag)
        for reason_group in by_reason.values():
            trims = sorted(
                (trim for flag in reason_group for trim in flag.word_trims),
                key=lambda trim: trim.start,
            )
            base = max(reason_group, key=lambda flag: flag.confidence)
            merged.append(base.model_copy(update={
                "word_trims": trims,
                "kept_spans": [span for flag in reason_group for span in flag.kept_spans],
            }))
    merged.sort(key=lambda flag: (
        flag.idx,
        flag.word_trims[0].start if flag.word_trims else float("-inf"),
    ))
    return merged


def _edit_section(
    sentences: list[Sentence],
    section: Section,
    llm,
    *,
    audio_candidates: list[AudioFalseStartCandidate] | None = None,
) -> list[SectionDeletion]:
    prompt = SECTION_PROMPT.format(
        editable_range=f"{section.owned_lo}–{section.owned_hi - 1}",
        section_text=_render_section(sentences, section),
        audio_candidates="\n".join(
            f"[{candidate.sentence_index}] {candidate.evidence}"
            for candidate in audio_candidates or []
            if section.ctx_lo <= candidate.sentence_index < section.ctx_hi
        ) or "Nema audio kandidata.",
    )
    structured = llm.with_structured_output(SectionEdits)
    result: SectionEdits = structured.invoke(prompt)
    return result.deletions


def _edit_section_with_retry(
    sentences: list[Sentence],
    section: Section,
    llm,
    cfg: SectionEditorConfig,
    health: SectionHealth,
    *,
    audio_candidates: list[AudioFalseStartCandidate] | None = None,
) -> list[SectionDeletion]:
    """Retry structured-output failures that occur after a successful HTTP response."""
    for attempt in range(1, cfg.section_max_attempts + 1):
        try:
            return _edit_section(sentences, section, llm, audio_candidates=audio_candidates)
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
    trace: SectionTrace | None = None,
    audio_candidates: list[AudioFalseStartCandidate] | None = None,
) -> list[DuplicateFlag]:
    """Run the section editor and return removal flags.

    Best-effort per section: a failed section is logged
    and skipped rather than aborting the whole video. Pass *health* to collect
    plumbing telemetry (failed sections, rejected spans) — essential when
    comparing models, because a model whose calls fail looks identical to a
    conservative one in the cut metrics."""
    if cfg is None:
        cfg = SectionEditorConfig()
    health = health if health is not None else SectionHealth()
    trace = trace if trace is not None else SectionTrace()
    trace.audio_candidates = list(audio_candidates or [])
    if len(sentences) < 2:
        return []

    primary_config = llm_config or cfg.llm
    llm = build_chat_model(primary_config)
    fallback_config = cfg.fallback_llm
    if (
        fallback_config is not None
        and fallback_config.id == "gpt-5.6-sol-openai-direct"
        and primary_config.model != "openai/gpt-5.6-sol"
    ):
        # The built-in fallback belongs specifically to the default OpenRouter
        # Sol route. Model experiments must never silently mix in Sol results.
        fallback_config = None
    fallback_llm = None
    sections = _build_sections(sentences, cfg)
    health.sections_total += len(sections)
    logger.info(
        "Section editor: {} sentences → {} sections (target={}w, max={}w)",
        len(sentences), len(sections), cfg.target_words, cfg.max_words,
    )

    raw_flags: list[DuplicateFlag] = []
    for si, section in enumerate(sections):
        model_id = primary_config.id or primary_config.model
        try:
            deletions = _edit_section_with_retry(
                sentences, section, llm, cfg, health, audio_candidates=audio_candidates,
            )
        except Exception as primary_exc:
            if fallback_config is None:
                logger.exception(
                    "Section editor: section {}/{} ([{}–{}]) failed — skipping",
                    si + 1, len(sections), section.owned_lo, section.owned_hi - 1,
                )
                health.sections_failed += 1
                continue

            health.sections_fallback += 1
            logger.warning(
                "Section editor: primary {} failed for section {}/{} ({}: {}); "
                "falling back to {}",
                primary_config.id or primary_config.model,
                si + 1,
                len(sections),
                type(primary_exc).__name__,
                str(primary_exc)[:120],
                fallback_config.id or fallback_config.model,
            )
            try:
                if fallback_llm is None:
                    fallback_llm = build_chat_model(fallback_config)
                deletions = _edit_section_with_retry(
                    sentences, section, fallback_llm, cfg, health,
                    audio_candidates=audio_candidates,
                )
                model_id = fallback_config.id or fallback_config.model
            except Exception:
                logger.exception(
                    "Section editor: primary and fallback failed for section {}/{} "
                    "([{}–{}]) — skipping",
                    si + 1, len(sections), section.owned_lo, section.owned_hi - 1,
                )
                health.sections_failed += 1
                continue
        health.deletions_proposed += len(deletions)
        for d in deletions:
            unverifiable_before = health.deletions_rejected_unverifiable
            rejection_reasons = []
            if not section.owns(d.sentence_index) or (
                d.kept_index is not None and not section.ctx_lo <= d.kept_index < section.ctx_hi
            ):
                flag = None
                health.deletions_rejected_guardrail += 1
                rejection_reasons.append("Deletion is not owned or replacement is outside the supplied context")
            else:
                flag = _deletion_to_flag(
                    d, sentences, cfg, health, rejection_reasons=rejection_reasons,
                )
            if trace is not None:
                if flag is not None:
                    disposition = "accepted"
                elif health.deletions_rejected_unverifiable > unverifiable_before:
                    disposition = "rejected_unverifiable"
                else:
                    disposition = "rejected_guardrail"
                trace.proposals.append(SectionProposalTrace(
                    deletion=d,
                    disposition=disposition,
                    flag=flag,
                    detail="; ".join(rejection_reasons),
                    model_id=model_id,
                ))
            if flag is not None:
                raw_flags.append(flag)

    trace.local_flags = [
        flag.model_copy(update={"source": "local_correction"})
        for flag in detect_local_corrections(sentences)
    ]
    raw_flags.extend(trace.local_flags)
    trace.protected_spans = [span for flag in raw_flags for span in flag.kept_spans]
    flags = _merge_flags(protect_kept_spans(
        raw_flags, sentences, protected=trace.protected_spans, rejected=trace.rejected_conflicts,
    ))
    health.flags_emitted += len(flags)
    trace.health = asdict(health)
    full = sum(1 for f in flags if not f.word_trims)
    trims = sum(1 for f in flags if f.word_trims)
    logger.info(
        "Section editor: {} flags ({} full-sentence, {} word-trim) — "
        "{}/{} sections failed, {} retries, {} fallbacks, {} spans rejected",
        len(flags), full, trims,
        health.sections_failed, health.sections_total,
        health.section_retries,
        health.sections_fallback,
        health.deletions_rejected_unverifiable + health.deletions_rejected_guardrail,
    )
    return flags
