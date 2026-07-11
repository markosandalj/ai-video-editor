"""Aside / production-noise detection.

This pass is deliberately *not* duplicate-anchored. Most of the sentences a human
editor cuts are not repetitions at all — they are off-topic asides, abandoned
remarks, and production noise ("Khm.", "Čekaj, otvaraju se vrata.", "a ne mogu
više pričati"). The tiered duplicate detector is structurally blind to these.

Candidates are short sentences that are either flanked by long silences
(production interruptions are bracketed by pauses) or carry an ElevenLabs audio
event tag. Candidates are confirmed by Gemini asking a single, focused question:
"is this part of the lesson?" — distinct from "is this a duplicate?".
"""
from __future__ import annotations

import re

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from ai_video_editor.audio.models import SilenceRegion
from ai_video_editor.config.settings import AsideDetectionConfig
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.llm import (
    LangChainModelConfig,
    build_chat_model,
    default_cutting_model_config,
)
from ai_video_editor.transcription.models import Sentence

# ElevenLabs tags non-speech events in parentheses, e.g. "(cough)", "(laughter)".
_AUDIO_EVENT = re.compile(r"\([^)]+\)")


def _has_audio_event(sentence: Sentence) -> bool:
    return bool(_AUDIO_EVENT.search(sentence.text))


def _flanking_silence(
    sentence: Sentence,
    silences: list[SilenceRegion],
    *,
    adjacency_s: float,
    min_silence_s: float,
) -> bool:
    """True if a long silence touches either boundary of the sentence."""
    for sil in silences:
        if sil.duration < min_silence_s:
            continue
        touches_start = abs(sil.end - sentence.start) <= adjacency_s
        touches_end = abs(sil.start - sentence.end) <= adjacency_s
        if touches_start or touches_end:
            return True
    return False


def detect_aside_candidates(
    sentences: list[Sentence],
    silences: list[SilenceRegion],
    flagged_indices: set[int],
    cfg: AsideDetectionConfig,
) -> list[int]:
    """Return indices of short sentences that look like asides / production noise."""
    candidates: list[int] = []
    for i, s in enumerate(sentences):
        if i in flagged_indices:
            continue
        if len(s.words) > cfg.max_words:
            continue
        if _has_audio_event(s) or _flanking_silence(
            s,
            silences,
            adjacency_s=cfg.silence_adjacency_s,
            min_silence_s=cfg.flank_silence_s,
        ):
            candidates.append(i)
    logger.info("Aside detection: {} candidates", len(candidates))
    return candidates


ASIDE_PROMPT = """Ti si profesionalni video editor za edukacijske lekcije na hrvatskom. Pregledaj sljedeće kandidate u kontekstu okolnih rečenica.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Tvoj zadatak: za SVAKI kandidat odluči je li dio LEKCIJE ili je usputni komentar / smetnja koju treba izbaciti.

IZBACI (is_aside=true) ako je kandidat:
- usputni komentar koji ne pripada lekciji ("Čekaj, otvaraju se vrata.", "Ne mogu više pričati.")
- zvuk/smetnja ((kašalj), (smijeh), nakašljavanje "Khm.")
- prekid snimanja ili obraćanje nekome izvan lekcije

ZADRŽI (is_aside=false) ako kandidat:
- nosi bilo kakav sadržaj lekcije (korak, definicija, prijelaz, najava sljedećeg koraka)
- je prirodan govorni prijelaz ("Dobro", "Evo", "Idemo dalje")

Budi oprezan: ako nisi siguran, ZADRŽI (is_aside=false).

Kandidati (svaki s kontekstom; kandidat označen s <<<):
{candidates_text}"""


class AsideVerdict(BaseModel):
    sentence_index: int
    is_aside: bool = False
    confidence: float = 0.5
    reasoning: str = ""

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class AsideReview(BaseModel):
    verdicts: list[AsideVerdict] = Field(default_factory=list)


def verify_asides_with_gemini(
    candidate_indices: list[int],
    sentences: list[Sentence],
    *,
    context_window: int = 3,
    llm_config: LangChainModelConfig | None = None,
) -> list[AsideVerdict]:
    if not candidate_indices:
        return []

    parts: list[str] = []
    for idx in candidate_indices:
        lo = max(0, idx - context_window)
        hi = min(len(sentences), idx + context_window + 1)
        lines = []
        for j in range(lo, hi):
            mark = " <<< KANDIDAT" if j == idx else ""
            lines.append(f'  [{j}] "{sentences[j].text}"{mark}')
        parts.append("\n".join(lines))

    prompt = ASIDE_PROMPT.format(candidates_text="\n\n---\n\n".join(parts))

    llm = build_chat_model(llm_config or default_cutting_model_config())
    structured = llm.with_structured_output(AsideReview)

    logger.info("Gemini aside verification: {} candidates", len(candidate_indices))
    result: AsideReview = structured.invoke(prompt)

    valid = set(candidate_indices)
    verdicts = [v for v in result.verdicts if v.sentence_index in valid]
    for v in verdicts:
        logger.info(
            "Aside verdict: sentence {} → {} (conf={:.0%}, {})",
            v.sentence_index,
            "CUT" if v.is_aside else "KEEP",
            v.confidence,
            v.reasoning[:70],
        )
    return verdicts


def detect_asides(
    sentences: list[Sentence],
    silences: list[SilenceRegion],
    flagged_indices: set[int],
    cfg: AsideDetectionConfig,
    *,
    llm_config: LangChainModelConfig | None = None,
) -> list[DuplicateFlag]:
    """Full aside-detection pass: candidate generation + Gemini confirmation."""
    if not cfg.enabled:
        return []

    candidates = detect_aside_candidates(sentences, silences, flagged_indices, cfg)
    if not candidates:
        return []

    verdicts = verify_asides_with_gemini(
        candidates,
        sentences,
        llm_config=llm_config,
    )
    flags: list[DuplicateFlag] = []
    for v in verdicts:
        if (
            v.is_aside
            and v.confidence >= cfg.gemini_confidence_threshold
            and v.sentence_index not in flagged_indices
        ):
            flags.append(DuplicateFlag(
                idx=v.sentence_index,
                reason=FlagReason.ASIDE,
                confidence=v.confidence,
                note=f"Aside: {v.reasoning}",
            ))
    logger.info("Aside detection: {} sentences flagged as asides", len(flags))
    return flags
