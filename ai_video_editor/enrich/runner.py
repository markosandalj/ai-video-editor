from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, NamedTuple

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.config.settings import EnrichmentConfig
from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.enrich.models import (
    EnrichmentResult,
    EnrichmentStatus,
    EnrichmentTag,
    SentenceEnrichment,
    derive_status,
    reconcile_word_salience,
)
from ai_video_editor.transcription.models import Sentence, Transcript


ENRICH_PROMPT = """Ti si iskusni video editor koji montira edukacijske lekcije na hrvatskom jeziku, snimljene neformalnim govornim stilom. Za SVAKU rečenicu NEOVISNO procijeni pripada li u finalnu montažu. Rečenice su dane redoslijedom kako su izgovorene, pa koristi susjedne rečenice da prepoznaš ponavljanja.

KAKO LJUDSKI EDITOR ODLUČUJE:
- ZADRŽAVA: svaki jedinstven sadržaj (korak, definiciju, formulu, međurezultat, odgovor) I prirodan govorni tok — kratke potvrde i prijelaze ("Okej", "Dobro", "Evo", "Pa evo", "Znači", "Dakle", "Jel tako?"). Prirodne poštapalice koje zvuče normalno OSTAJU u videu.
- IZBACUJE: rečenicu koja DOSLOVNO PONAVLJA sadržaj susjedne rečenice, lažni početak (govornik krene pa se odmah ispravi) i nedovršenu misao koju odmah preformulira.

Za SVAKU rečenicu vrati:
- sentence_idx: indeks rečenice (točno kako je dan)
- keep_confidence: broj 0-100 = koliko si SIGURAN da rečenica TREBA biti u finalnom videu
    85-100 = jedinstven sadržaj ILI prirodan govorni prijelaz → ZADRŽI
    0-30 = doslovno ponavljanje, lažni početak ili nedovršena misao → IZBACI
    sredina = stvarno granično
- tags: lista oznaka SAMO iz ovog skupa: {tags}
- rationale: kratko objašnjenje na HRVATSKOM (jedna rečenica)
- word_salience: lista 0-100, JEDAN broj po svakoj riječi istim redoslijedom (100 = ključna riječ, 0 = nebitan filler). Točno onoliko brojeva koliko rečenica ima riječi.

VAŽNO:
- Procjenjuj SADRŽAJ, ne stil. Kratke poštapalice i prijelazi NISU greška — daj im visok keep_confidence.
- Nizak keep_confidence daj SAMO kada rečenica doslovno ponavlja susjednu, kada je lažni početak ili nedovršena misao.
- Budi ODLUČAN: ne ograđuj se ocjenom ~50 osim za stvarno granične slučajeve.

Rečenice (redoslijedom; svaka s riječima):
{sentences_block}"""


class SentenceEnrichmentLLM(BaseModel):
    """Raw per-sentence output from Gemini (status is derived afterward)."""

    sentence_idx: int
    keep_confidence: float = Field(ge=0.0, le=100.0)
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""
    word_salience: list[float] = Field(default_factory=list)


class EnrichmentBatch(BaseModel):
    sentences: list[SentenceEnrichmentLLM] = Field(default_factory=list)


class SentenceContext(NamedTuple):
    idx: int
    sentence: Sentence
    is_cut: bool
    reason: str


BatchScorer = Callable[[list[SentenceContext]], list[SentenceEnrichmentLLM]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_transcript(
    transcript: Transcript,
    edl: EditDecisionList,
    config: EnrichmentConfig,
    *,
    scorer: BatchScorer | None = None,
) -> EnrichmentResult:
    """Score and tag every transcript sentence in a dedicated LLM pass.

    ``scorer`` is the batch-level seam: by default it calls Gemini, but tests
    can inject a deterministic scorer to run offline.
    """
    contexts = [
        SentenceContext(idx=i, sentence=s, **_cut_info(s, edl))
        for i, s in enumerate(transcript.sentences)
    ]

    if scorer is None:
        scorer = _make_gemini_scorer(config)

    enrichments: list[SentenceEnrichment] = []
    for batch in _batched(contexts, config.batch_size):
        try:
            raw_items = scorer(batch)
        except Exception:  # noqa: BLE001 — never let one batch abort the pipeline
            logger.exception("Enrichment batch failed; using neutral fallback for {} sentences", len(batch))
            raw_items = []

        by_idx = {item.sentence_idx: item for item in raw_items}
        for ctx in batch:
            item = by_idx.get(ctx.idx)
            enrichments.append(
                _build_enrichment(ctx, item, config)
                if item is not None
                else _fallback_enrichment(ctx, config)
            )

    return EnrichmentResult(
        source_video=transcript.source_video,
        sentences=enrichments,
    )


def restatus_against_edl(
    enrichment: EnrichmentResult,
    transcript: Transcript,
    edl: EditDecisionList,
    config: EnrichmentConfig,
) -> EnrichmentResult:
    """Recompute each sentence's status against a (possibly revised) EDL.

    Pure / no API: ``keep_confidence`` and tags are unchanged; only the derived
    GREEN/YELLOW/RED/RESTORE tier moves to match the final cut/keep state. Used
    after the arbiter rewrites the EDL so the review sidecar stays truthful.
    """
    sentence_by_idx = {i: s for i, s in enumerate(transcript.sentences)}
    updated: list[SentenceEnrichment] = []
    for item in enrichment.sentences:
        sentence = sentence_by_idx.get(item.sentence_idx)
        is_cut = bool(_cut_info(sentence, edl)["is_cut"]) if sentence is not None else False
        status = derive_status(
            item.keep_confidence,
            is_cut,
            green_threshold=config.green_threshold,
            restore_threshold=config.restore_threshold,
        )
        word_count = len(sentence.words) if sentence is not None else 0
        if status == EnrichmentStatus.RESTORE and word_count < RESTORE_MIN_WORDS:
            status = EnrichmentStatus.RED
        updated.append(item.model_copy(update={"status": status}))
    return enrichment.model_copy(update={"sentences": updated})


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# A "restore" suggestion only makes sense for a cut that removed real content.
# Cuts of very short utterances (filler / confirmations like "Okej.", "Dobro.")
# are pacing decisions, not lost content, so they must never surface as restore.
RESTORE_MIN_WORDS = 4


def _build_enrichment(
    ctx: SentenceContext,
    item: SentenceEnrichmentLLM,
    config: EnrichmentConfig,
) -> SentenceEnrichment:
    keep_confidence = max(0.0, min(100.0, item.keep_confidence))
    word_count = len(ctx.sentence.words)
    status = derive_status(
        keep_confidence,
        ctx.is_cut,
        green_threshold=config.green_threshold,
        restore_threshold=config.restore_threshold,
    )
    # Suppress restore on short cut filler — confirms the cut instead of flagging it.
    if status == EnrichmentStatus.RESTORE and word_count < RESTORE_MIN_WORDS:
        status = EnrichmentStatus.RED
    return SentenceEnrichment(
        sentence_idx=ctx.idx,
        keep_confidence=keep_confidence,
        status=status,
        tags=_coerce_tags(item.tags),
        rationale=item.rationale.strip(),
        word_salience=reconcile_word_salience(item.word_salience, word_count, keep_confidence),
    )


def _fallback_enrichment(ctx: SentenceContext, config: EnrichmentConfig) -> SentenceEnrichment:
    # Bias toward attention: failed scoring becomes yellow (kept) / red (cut),
    # never a false green.
    keep_confidence = 0.0 if ctx.is_cut else max(0.0, config.green_threshold - 1.0)
    word_count = len(ctx.sentence.words)
    return SentenceEnrichment(
        sentence_idx=ctx.idx,
        keep_confidence=keep_confidence,
        status=derive_status(
            keep_confidence,
            ctx.is_cut,
            green_threshold=config.green_threshold,
            restore_threshold=config.restore_threshold,
        ),
        tags=[EnrichmentTag.NEEDS_REVIEW],
        rationale="Automatska procjena nije uspjela — provjeri ručno.",
        word_salience=[keep_confidence] * word_count,
    )


def _coerce_tags(raw: list[str]) -> list[EnrichmentTag]:
    valid = {tag.value for tag in EnrichmentTag}
    out: list[EnrichmentTag] = []
    for value in raw:
        normalized = str(value).strip().lower()
        if normalized in valid:
            out.append(EnrichmentTag(normalized))
    return out


def _cut_info(sentence: Sentence, edl: EditDecisionList) -> dict[str, object]:
    duration = max(sentence.end - sentence.start, 0.0)
    if duration <= 0:
        return {"is_cut": False, "reason": ""}

    kept = 0.0
    cut_reason = ""
    for decision in edl.decisions:
        overlap = max(0.0, min(sentence.end, decision.end) - max(sentence.start, decision.start))
        if overlap <= 0:
            continue
        if decision.action == EditAction.KEEP:
            kept += overlap
        elif not cut_reason:
            cut_reason = decision.reason.value
    is_cut = (kept / duration) < 0.5
    return {"is_cut": is_cut, "reason": cut_reason if is_cut else ""}


def _batched(items: list[SentenceContext], size: int) -> list[list[SentenceContext]]:
    size = max(1, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------
# Gemini scorer
# ---------------------------------------------------------------------------

def _make_gemini_scorer(config: EnrichmentConfig) -> BatchScorer:
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=config.model,
        temperature=config.temperature,
        api_key=_load_gemini_key(),
        timeout=180,
        max_retries=4,
    )
    structured = llm.with_structured_output(EnrichmentBatch)
    tag_list = ", ".join(tag.value for tag in EnrichmentTag)

    def scorer(batch: list[SentenceContext]) -> list[SentenceEnrichmentLLM]:
        prompt = ENRICH_PROMPT.format(tags=tag_list, sentences_block=_format_batch(batch))
        logger.info("Gemini enrichment: scoring {} sentences", len(batch))
        result: EnrichmentBatch = structured.invoke(prompt)
        return result.sentences

    return scorer


# The pipeline decision is deliberately withheld from the model: when shown the
# KEEP/CUT verdict (and its reason) the model just rubber-stamps it and can never
# flag a pipeline error. Independent judgment + derive_status() surfaces the
# disagreements that actually need a human look.
def _format_batch(batch: list[SentenceContext]) -> str:
    blocks: list[str] = []
    for ctx in batch:
        words = " ".join(f'[{i}]"{w.text}"' for i, w in enumerate(ctx.sentence.words))
        blocks.append(
            f"[{ctx.idx}]\n"
            f"  riječi: {words}\n"
            f'  tekst: "{ctx.sentence.text}"'
        )
    return "\n\n".join(blocks)


def _load_gemini_key() -> str:
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found. Add it to your .env file.")
    return key
