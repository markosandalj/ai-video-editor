from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.transcription.models import Sentence, Transcript, Word

MIN_WORD_LENGTH = 3
MAX_PASSES = 5

PROMPT_STRICT = """Pregledaj sljedeći transkript video lekcije na hrvatskom jeziku i pronađi SVE krivo napisane riječi.

VAŽNO - Ovo je transkript govornog jezika:
- NE ispravljaj stilske odabire, poštapalice ili razgovorni jezik
- NE ispravljaj gramatiku rečenica - ljudi ne govore u savršenim rečenicama
- Ispravi SAMO pravopisne pogreške (zatipci, krivo napisane riječi)
- Zadrži TOČAN oblik riječi (veliko/malo slovo) - npr. ako je "Znači" na početku rečenice, vrati "Znači" a ne "znači"
- Vrati samo parove riječi koje su stvarno krivo napisane

PRIMJERI:
✓ "zomirali" → "zumirali" (zatipak)
✓ "korjen" → "korijen" (zatipak)
✗ "znači" → NE ispravljaj (poštapalica, ali ispravno napisana)
✗ nepotpune rečenice → NE ispravljaj (tako je govornik govorio)

{skipped_words_section}Transkript:
{transcript}"""

PROMPT_LENIENT = """Pregledaj sljedeći transkript video lekcije na hrvatskom jeziku i pronađi SAMO OČITE pravopisne pogreške.

VAŽNO - Ovo je već nekoliko puta provjereni tekst:
- Budi IZUZETNO STROG - ispravi samo ako je POTPUNO SIGURNO da je pogreška
- NE traži pogreške ako ih nema
- NE ispravljaj riječi koje bi MOGLE biti ispravne u kontekstu
- NE ispravljaj gramatiku ili stil govora
- Ispravi SAMO očite zatipke i potpuno pogrešno napisane riječi

{skipped_words_section}Transkript:
{transcript}"""


class WordCorrection(BaseModel):
    wrong: str = Field(..., description="Incorrectly written word (preserve casing)")
    correct: str = Field(..., description="Correctly written word (preserve casing)")


class CorrectionResult(BaseModel):
    corrections: list[WordCorrection] = Field(
        default_factory=list,
        description="List of word pairs to correct via search-and-replace",
    )


class GrammarReport(BaseModel):
    """Summary of all grammar correction passes."""
    passes: int = 0
    total_corrections: int = 0
    converged: bool = False
    corrections_log: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

def _merge_sentences(existing: list[Sentence], new: list[Sentence]) -> list[Sentence]:
    return new if new else existing


class CorrectionState(TypedDict):
    sentences: Annotated[list[Sentence], _merge_sentences]
    skipped_words: set[str]
    pass_num: int
    max_passes: int
    report: GrammarReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_gemini_key() -> str:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not found in environment. Add it to your .env file."
        )
    return key


def _apply_corrections(
    sentences: list[Sentence],
    corrections: list[WordCorrection],
    skipped_words: set[str],
    pass_num: int,
) -> tuple[list[Sentence], int, list[dict]]:
    """
    Apply word corrections via regex word-boundary search-and-replace.
    Returns (updated_sentences, replacement_count, log_entries).
    """
    total_replacements = 0
    log_entries: list[dict] = []

    for correction in corrections:
        if len(correction.wrong) < MIN_WORD_LENGTH:
            skipped_words.add(correction.wrong)
            continue

        pattern = r"\b" + re.escape(correction.wrong) + r"\b"
        count = 0

        new_sentences = []
        for sentence in sentences:
            new_text, n = re.subn(pattern, correction.correct, sentence.text)
            if n > 0:
                count += n
                new_words = []
                for w in sentence.words:
                    w_new_text, w_n = re.subn(pattern, correction.correct, w.text)
                    new_words.append(
                        Word(text=w_new_text, start=w.start, end=w.end)
                        if w_n > 0
                        else w
                    )
                new_sentences.append(
                    Sentence(
                        words=new_words,
                        text=new_text,
                        start=sentence.start,
                        end=sentence.end,
                    )
                )
            else:
                new_sentences.append(sentence)

        sentences = new_sentences

        if count > 0:
            total_replacements += count
            log_entries.append({
                "pass": pass_num,
                "wrong": correction.wrong,
                "correct": correction.correct,
                "replacements": count,
            })

    return sentences, total_replacements, log_entries


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def spell_check_node(state: CorrectionState) -> CorrectionState:
    """Send transcript to Gemini, get structured corrections back."""
    api_key = _load_gemini_key()
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.1,
        api_key=api_key,
    )
    structured_llm = llm.with_structured_output(CorrectionResult)

    sentences = state["sentences"]
    pass_num = state["pass_num"]
    max_passes = state["max_passes"]
    skipped_words = state["skipped_words"]
    report = state["report"]

    full_text = "\n".join(s.text for s in sentences if s.text)
    use_lenient = pass_num >= 3

    skipped_section = ""
    if skipped_words:
        skipped_list = ", ".join(sorted(skipped_words))
        skipped_section = (
            f"PRESKOČENE RIJEČI (ne vraćaj ih ponovno): {skipped_list}\n\n"
        )

    prompt = (PROMPT_LENIENT if use_lenient else PROMPT_STRICT).format(
        transcript=full_text,
        skipped_words_section=skipped_section,
    )

    logger.info(
        "[Grammar Pass {}/{}] Sending {} chars to Gemini ({})",
        pass_num, max_passes, len(full_text),
        "lenient" if use_lenient else "strict",
    )

    result: CorrectionResult = structured_llm.invoke(prompt)

    logger.info(
        "[Grammar Pass {}/{}] Gemini returned {} corrections",
        pass_num, max_passes, len(result.corrections),
    )

    if not result.corrections:
        report.passes = pass_num
        report.converged = True
        logger.info("Grammar correction converged after {} pass(es)", pass_num)
        return {
            "sentences": sentences,
            "skipped_words": skipped_words,
            "pass_num": pass_num,
            "max_passes": max_passes,
            "report": report,
        }

    sentences, replacements, entries = _apply_corrections(
        sentences, result.corrections, skipped_words, pass_num
    )
    report.total_corrections += replacements
    report.corrections_log.extend(entries)

    logger.info(
        "[Grammar Pass {}/{}] Applied {} replacements",
        pass_num, max_passes, replacements,
    )

    if replacements == 0:
        report.passes = pass_num
        report.converged = True
        logger.info(
            "Grammar correction converged after {} pass(es) (only short words suggested)",
            pass_num,
        )
    else:
        report.passes = pass_num

    return {
        "sentences": sentences,
        "skipped_words": skipped_words,
        "pass_num": pass_num + 1,
        "max_passes": max_passes,
        "report": report,
    }


def should_continue(state: CorrectionState) -> str:
    """Decide whether to loop back for another pass or finish."""
    report = state["report"]
    if report.converged:
        return "done"
    if state["pass_num"] > state["max_passes"]:
        logger.warning(
            "Grammar correction did NOT converge after {} passes",
            state["max_passes"],
        )
        return "done"
    return "check"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(CorrectionState)
    graph.add_node("check", spell_check_node)
    graph.set_entry_point("check")
    graph.add_conditional_edges("check", should_continue, {"check": "check", "done": END})
    return graph.compile()


_workflow = None


def _get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = _build_graph()
    return _workflow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def correct_grammar(
    transcript: Transcript,
    *,
    max_passes: int = MAX_PASSES,
) -> tuple[Transcript, GrammarReport]:
    """
    Iterative Gemini spell-check on a Transcript using LangGraph.

    Each pass sends full transcript text to Gemini via LangChain's
    structured output, gets word correction pairs, applies them via
    search-and-replace, and loops until convergence (0 corrections)
    or max_passes is reached.

    Timestamps are never modified -- only word/sentence text changes.

    Returns (corrected_transcript, report).
    """
    workflow = _get_workflow()

    initial_state: CorrectionState = {
        "sentences": [s.model_copy(deep=True) for s in transcript.sentences],
        "skipped_words": set(),
        "pass_num": 1,
        "max_passes": max_passes,
        "report": GrammarReport(),
    }

    final_state = workflow.invoke(initial_state)

    corrected = transcript.model_copy(update={"sentences": final_state["sentences"]})
    return corrected, final_state["report"]
