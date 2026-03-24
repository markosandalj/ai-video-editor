from __future__ import annotations

import os
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.duplicate.models import SimilarityScore
from ai_video_editor.transcription.models import Sentence

DUPLICATE_PROMPT = """Jesi li ekspert za analizu govornog jezika na hrvatskom. Tvoj zadatak je odlučiti jesu li parovi rečenica iz video lekcije **ponavljanja** (govornik je rekao istu stvar dva puta, jednom pogrešno pa zatim ispravno).

PRAVILA:
- "Duplikat" znači da je govornik ponovio istu misao — NE da su rečenice slične po temi
- Ako govornik objašnjava istu temu ali dodaje nove informacije, to NISU duplikati
- Ako je jedna rečenica nastavak prethodne misli, to NIJE duplikat
- Kratki frazni obrasci poput pozdrava ili uvodnih fraza ("Dobro, idemo dalje") JESU duplikati samo ako se ponavljaju uzastopno

Za svaki par navedi:
- is_duplicate: true/false
- confidence: 0.0-1.0 (koliko si siguran)
- reasoning: kratko objašnjenje na hrvatskom

Parovi rečenica za analizu:
{pairs_text}"""

FALSE_START_PROMPT = """Analiziraj sljedeći blok rečenica iz video lekcije na hrvatskom. Ove rečenice se nalaze IZMEĐU dva ponavljanja — govornik je rekao istu stvar prije i poslije ovog bloka.

Tvoj zadatak: odluči koje od ovih rečenica su **lažni počeci, nedovršene misli ili filler** koji se mogu izbaciti, a koje su **stvarni sadržaj** koji treba zadržati.

PRAVILA:
- "Lažni početak" = govornik je počeo rečenicu pa odustao i krenuo ispočetka
- "Filler" = poštapalice bez sadržaja ("znači", "evo", "dakle" same za sebe)
- Ako rečenica nosi novu informaciju ili objašnjenje, to NIJE filler — ZADRŽI je
- Budi konzervativan: ako nisi siguran, označi kao "zadrži"

Rečenice (s indeksima):
{block_text}

Kontekst — rečenica PRIJE bloka:
{before}

Kontekst — rečenica NAKON bloka:
{after}"""


class DuplicateVerdict(BaseModel):
    """Gemini's judgment on a single sentence pair."""
    pair_id: int = Field(..., description="Zero-based index into the input pairs list")
    is_duplicate: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class DuplicateVerdicts(BaseModel):
    """Container for batch duplicate verdicts."""
    verdicts: list[DuplicateVerdict] = Field(default_factory=list)


class FalseStartVerdict(BaseModel):
    """Gemini's judgment on which sentences in a block are filler/false starts."""
    filler_indices: list[int] = Field(
        default_factory=list,
        description="Indices of sentences that are filler/false starts (relative to the block)",
    )
    reasoning: str = ""


def _load_gemini_key() -> str:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found. Add it to your .env file.")
    return key


def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.1,
        api_key=_load_gemini_key(),
    )


def verify_duplicates_with_gemini(
    pairs: list[SimilarityScore],
    sentences: list[Sentence],
) -> list[DuplicateVerdict]:
    """
    Ask Gemini whether borderline sentence pairs are real duplicates.

    *pairs* contains ``(idx_a, idx_b)`` references into *sentences*.
    Returns one ``DuplicateVerdict`` per input pair.
    """
    if not pairs:
        return []

    lines: list[str] = []
    for k, p in enumerate(pairs):
        a_text = sentences[p.idx_a].text
        b_text = sentences[p.idx_b].text
        lines.append(f"Par {k}:\n  A (rečenica {p.idx_a}): \"{a_text}\"\n  B (rečenica {p.idx_b}): \"{b_text}\"")

    prompt = DUPLICATE_PROMPT.format(pairs_text="\n\n".join(lines))

    llm = _get_llm()
    structured = llm.with_structured_output(DuplicateVerdicts)

    logger.info("Gemini duplicate verification: {} pairs", len(pairs))
    result: DuplicateVerdicts = structured.invoke(prompt)

    logger.info(
        "Gemini returned {} verdicts ({} duplicates)",
        len(result.verdicts),
        sum(1 for v in result.verdicts if v.is_duplicate),
    )
    return result.verdicts


def detect_false_starts_with_gemini(
    block_sentences: list[Sentence],
    before_sentence: Sentence | None,
    after_sentence: Sentence | None,
) -> FalseStartVerdict:
    """
    Given a block of sentences between a confirmed duplicate pair, ask Gemini
    which ones are filler or false starts that can be removed.
    """
    if not block_sentences:
        return FalseStartVerdict(filler_indices=[], reasoning="Empty block")

    block_lines = "\n".join(
        f"  [{i}] \"{s.text}\"" for i, s in enumerate(block_sentences)
    )
    before = f"\"{before_sentence.text}\"" if before_sentence else "(početak transkripta)"
    after = f"\"{after_sentence.text}\"" if after_sentence else "(kraj transkripta)"

    prompt = FALSE_START_PROMPT.format(
        block_text=block_lines,
        before=before,
        after=after,
    )

    llm = _get_llm()
    structured = llm.with_structured_output(FalseStartVerdict)

    logger.info("Gemini false-start detection: {} sentences in block", len(block_sentences))
    result: FalseStartVerdict = structured.invoke(prompt)

    logger.info(
        "Gemini flagged {} false starts out of {} block sentences",
        len(result.filler_indices),
        len(block_sentences),
    )
    return result
