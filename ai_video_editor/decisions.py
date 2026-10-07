"""Orchestration of the edit-decision layer.

Single source of truth for how raw transcript + silence/keep regions become an
EDL for the analysis use case:

    audio candidates → section editor → asides → retained-span protection → EDL

The worker projects this EDL into portable automatic cut ranges for Gradivo.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.audio.models import DisruptionRegion, KeepRegion, SilenceRegion
from ai_video_editor.config.settings import Settings
from ai_video_editor.duplicate.aside import detect_asides
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.false_start_audio import detect_audio_false_start_candidates
from ai_video_editor.duplicate.models import DuplicateFlag, RejectedCut
from ai_video_editor.duplicate.safeguards import protect_kept_spans
from ai_video_editor.duplicate.section_editor import SectionTrace, detect_section_edits
from ai_video_editor.llm import LangChainModelConfig
from ai_video_editor.transcription.models import Transcript


def _implementation_digest() -> str:
    """Identify the decision code without relying on a Git checkout at runtime."""
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in (
        "decisions.py", "config/settings.py", "duplicate/section_editor.py",
        "duplicate/safeguards.py", "duplicate/local_corrections.py",
        "duplicate/false_start_audio.py", "duplicate/edl.py",
    ):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


class DecisionTrace(BaseModel):
    version: str = "edit_decisions.v2"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    section: SectionTrace = Field(default_factory=SectionTrace)
    aside_flags: list[DuplicateFlag] = Field(default_factory=list)
    rejected_conflicts: list[RejectedCut] = Field(default_factory=list)
    final_flags: list[DuplicateFlag] = Field(default_factory=list)
    transcript: Transcript | None = None
    edl_before_snapping: EditDecisionList | None = None
    implementation_sha256: str = ""
    silences: list[SilenceRegion] = Field(default_factory=list)
    keeps: list[KeepRegion] = Field(default_factory=list)
    disruptions: list[DisruptionRegion] = Field(default_factory=list)


def detect_all_flags(
    transcript: Transcript,
    silences: list[SilenceRegion],
    disruptions: list[DisruptionRegion],
    settings: Settings,
    *,
    cutting_llm_config: LangChainModelConfig | None = None,
    trace: DecisionTrace | None = None,
) -> list[DuplicateFlag]:
    """Review acoustic hints as text, then protect replacements across all lanes."""
    trace = trace if trace is not None else DecisionTrace()
    audio_candidates = detect_audio_false_start_candidates(
        transcript.sentences, disruptions, set(), settings.false_start_audio,
    )
    flags = detect_section_edits(
        transcript.sentences,
        settings.section_editor,
        llm_config=settings.section_editor.llm,
        audio_candidates=audio_candidates,
        trace=trace.section,
    )
    flagged = {f.idx for f in flags if not f.word_trims}

    aside_flags = detect_asides(
        transcript.sentences,
        silences,
        flagged,
        settings.aside_detection,
        llm_config=cutting_llm_config or settings.cutting_llm,
    )
    trace.aside_flags = [flag.model_copy(update={"source": "aside"}) for flag in aside_flags]
    trace.final_flags = protect_kept_spans(
        flags + trace.aside_flags, transcript.sentences,
        protected=trace.section.protected_spans, rejected=trace.rejected_conflicts,
    )
    return trace.final_flags


def decide_edits(
    transcript: Transcript,
    keeps: list[KeepRegion],
    silences: list[SilenceRegion],
    settings: Settings,
    *,
    disruptions: list[DisruptionRegion] | None = None,
) -> EditDecisionList:
    """Produce the final EDL from the active cutting lanes."""
    trace = DecisionTrace(
        transcript=transcript, silences=silences, keeps=keeps, disruptions=disruptions or [],
        implementation_sha256=_implementation_digest(),
    )
    flags = detect_all_flags(transcript, silences, disruptions or [], settings, trace=trace)
    edl = build_edl(transcript, keeps, flags)
    trace.edl_before_snapping = edl
    trace_dir = settings.general.output_dir / "decision-traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{Path(transcript.source_video).stem}-{uuid4().hex}.json"
    trace_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Edit decision trace: {}", trace_path)
    return edl
