from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from ai_video_editor.llm import (
    LangChainModelConfig,
    default_cutting_model_config,
    default_section_editor_model_config,
)


LogLevel = Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]


class GeneralConfig(BaseModel):
    """Global settings. Extended in later phases."""

    model_config = ConfigDict(extra="allow")

    output_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "output",
        description="Directory for processed files and logs.",
    )
    temp_dir: Path = Field(
        default_factory=lambda: Path.cwd() / ".ai_video_editor_tmp",
        description="Scratch space for intermediate files.",
    )
    log_level: LogLevel = "INFO"

    @field_validator("output_dir", "temp_dir", mode="before")
    @classmethod
    def expand_path(cls, v: Path | str) -> Path:
        return Path(v).expanduser().resolve()


class AudioConfig(BaseModel):
    """Audio pre-processing parameters."""

    model_config = ConfigDict(extra="allow")

    noise_reduction_strength: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="prop_decrease for noisereduce (0 = no reduction, 1 = full). 0.3 preserves natural speech quality.",
    )
    silence_threshold_db: float = Field(
        default=-40.0,
        description="dB level below which audio is considered silent.",
    )
    silence_min_duration_s: float = Field(
        default=3.0,
        gt=0.0,
        description="Minimum silence duration (seconds) to trigger a cut.",
    )
    padding_ms: int = Field(
        default=500,
        ge=0,
        description="Milliseconds of padding before/after each speech segment.",
    )


class TranscriptionConfig(BaseModel):
    """ElevenLabs Scribe transcription followed by grammar correction."""

    model_config = ConfigDict(extra="allow")

    language: str = Field(
        default="hr",
        description="Language code for ElevenLabs.",
    )

    elevenlabs_model_id: str = Field(
        default="scribe_v2",
        description="ElevenLabs speech-to-text model id (e.g. scribe_v2).",
    )
    elevenlabs_tag_audio_events: bool = Field(
        default=True,
        description=(
            "If True, ElevenLabs tags non-speech events ((laughter), (cough), etc.). "
            "These tags are a strong signal for production-noise asides the human cut."
        ),
    )
    grammar_max_passes: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max iterative Gemini grammar passes after ElevenLabs.",
    )
    pause_split_s: float = Field(
        default=1.5,
        ge=0.0,
        description=(
            "Split a punctuation-delimited sentence wherever the gap between two "
            "consecutive words is >= this many seconds. These pauses are where "
            "speakers abandon a thought and restart, so splitting here gives the "
            "cut logic a false-start-shaped unit. 0 disables pause splitting."
        ),
    )

class DuplicateDetectionConfig(BaseModel):
    """Duplicate detection thresholds and behaviour."""

    model_config = ConfigDict(extra="allow")

    window_size: int = Field(
        default=5,
        ge=1,
        description="Lookahead window: each sentence compared against the next N sentences.",
    )

    lexical_definite: float = Field(
        default=90.0,
        ge=0.0,
        le=100.0,
        description="Lexical score (0-100) at or above which a pair is an automatic duplicate.",
    )
    lexical_maybe: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description="Lexical score (0-100) at or above which the pair advances to semantic tier.",
    )

    semantic_definite: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Cosine similarity at or above which a pair is an automatic duplicate.",
    )
    semantic_maybe: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Cosine similarity at or above which the pair advances to Gemini tier.",
    )

    gemini_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum Gemini confidence to accept a duplicate verdict.",
    )

    definite_min_words: int = Field(
        default=4,
        ge=0,
        description=(
            "Definite lexical/semantic pairs whose shorter sentence has fewer "
            "words than this are demoted to Gemini review instead of auto-cut. "
            "Short recurring interjections ('Dobro.', 'Ok.') score 100 lexical "
            "similarity but are discourse markers, not retakes — on the fixture "
            "corpus the human kept both copies in 9 of 10 such pairs."
        ),
    )

    take_selection: Literal["last", "gemini"] = Field(
        default="last",
        description=(
            "Which take to keep when a duplicate is confirmed. "
            "'last' (default): always keep the later take, deterministically — the "
            "LLM 'which to keep' pass is skipped, Gemini's preferred_index on "
            "borderline pairs is ignored, and each retake cluster keeps its "
            "highest-index member. A predictable rule professors can record for "
            "(flub, pause, redo clean) beats a marginally more accurate but "
            "unpredictable one, and the non-destructive review UI makes the rare "
            "wrong cut a cheap restore. 'gemini': let the model arbitrate the keep "
            "side (honours llm_keep_review and prefer_completeness) — higher "
            "historical accuracy on pre-existing footage at the cost of determinism."
        ),
    )
    llm_keep_review: bool = Field(
        default=False,
        description=(
            "Re-ask Gemini which side of every confirmed duplicate pair to keep "
            "(the pick_best_version pass). Only consulted when take_selection="
            "'gemini'. On the fixture corpus the human kept the later take in 71% "
            "of near-identical pairs and 82% of paraphrase pairs, so the "
            "deterministic keep-later default beats a completeness-first LLM "
            "re-litigation and removes a nondeterminism source."
        ),
    )

    context_window: int = Field(
        default=2,
        ge=0,
        description=(
            "Number of neighbouring sentences shown to Gemini on each side of a "
            "candidate duplicate pair. Context lets the model tell a retake "
            "(seconds apart, false start between) from a pedagogical recap."
        ),
    )
    cluster_retakes: bool = Field(
        default=True,
        description=(
            "Group connected duplicate pairs into retake clusters and keep exactly "
            "one survivor per cluster. Prevents chain inconsistencies where a "
            "sentence is both a keep-side and a cut-side of different pairs."
        ),
    )
    prefer_completeness: bool = Field(
        default=False,
        description=(
            "When choosing which duplicate to keep, prefer the more complete "
            "(longer) version over the later one. Only consulted when "
            "take_selection='gemini'; ignored under 'last'. Off by default: on the "
            "fixture corpus sentence length carried no signal (keep-longer was "
            "right 11/23 on near-identical pairs, 61% on paraphrase pairs) while "
            "keep-later was right 71%/82%."
        ),
    )


class SectionEditorConfig(BaseModel):
    """Section-based cutting: a strong LLM reads paragraph-sized windows and
    proposes verbatim spans to delete (whole sentences *or* partial spans), which
    are then mapped back to word-level timestamps deterministically. This replaces
    the tiered pair-comparison duplicate detector for the text-judgment cuts; the
    audio lane (silence, disruptions, asides) still runs alongside."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description=(
            "Use the LLM section editor for text-judgment cuts instead of the "
            "tiered duplicate detector."
        ),
    )
    llm: LangChainModelConfig = Field(
        default_factory=default_section_editor_model_config,
        description=(
            "Chat model that judges each section. The default is the GPT-5.6 Sol "
            "configuration selected by the section-editor evaluation."
        ),
    )
    target_words: int = Field(
        default=1200,
        ge=200,
        description="Preferred section size in words; boundaries snap to the largest pause near this.",
    )
    max_words: int = Field(
        default=2000,
        ge=400,
        description="Hard cap on a section's word count before a boundary is forced.",
    )
    overlap_sentences: int = Field(
        default=2,
        ge=0,
        description=(
            "Sentences of context shown on each side of a section's owned range so "
            "a retake pair straddling a boundary is still visible. Ownership stays "
            "disjoint — a deletion is only accepted for the section that owns it — "
            "so overlap never double-cuts."
        ),
    )
    section_max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Maximum attempts for one section. This catches malformed successful "
            "provider responses that bypass transport-level retries."
        ),
    )
    section_retry_backoff_s: float = Field(
        default=1.0,
        ge=0.0,
        le=30.0,
        description="Linear backoff in seconds between section attempts.",
    )
    min_span_match_ratio: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "A proposed deletion's verbatim text must match this fraction of a "
            "contiguous word run in the named sentence or it is rejected. This is "
            "the verify-the-claim guardrail: the model may only delete text that "
            "actually exists."
        ),
    )
    full_sentence_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description=(
            "If a matched span covers at least this fraction of the sentence's "
            "words, cut the whole sentence; otherwise emit a word-level trim."
        ),
    )
    protect_min_words: int = Field(
        default=4,
        ge=0,
        description=(
            "Whole-sentence retake deletions of sentences shorter than this are "
            "rejected — short near-identical lines ('Dobro.', 'Ok.') are usually "
            "recurring discourse markers, not retakes (mirrors "
            "DuplicateDetectionConfig.definite_min_words)."
        ),
    )
    retake_max_gap_s: float = Field(
        default=60.0,
        ge=0.0,
        description=(
            "Retake deletions whose surviving twin is farther than this in time are "
            "rejected — a large gap means recap, not retake. On the corpus, "
            "correct duplicate cuts sit a "
            "median 10s from their twin; wrong ones 25s with a long tail."
        ),
    )
    reject_types: list[str] = Field(
        default_factory=lambda: ["redundant"],
        description=(
            "Deletion types rejected instead of auto-cut. These can remove unique "
            "content and require a human-review system before they are safe to use."
        ),
    )


class AsideDetectionConfig(BaseModel):
    """Detection of non-lesson asides / production noise (not duplicates)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Run the aside/noise detection pass.",
    )
    flank_silence_s: float = Field(
        default=2.0,
        ge=0.0,
        description=(
            "A short sentence touching a silence gap >= this on either side is an "
            "aside candidate — production interruptions are bracketed by pauses."
        ),
    )
    silence_adjacency_s: float = Field(
        default=0.75,
        ge=0.0,
        description="How close a silence must be to a sentence boundary to count as flanking.",
    )
    max_words: int = Field(
        default=12,
        ge=1,
        description="Only sentences with at most this many words are aside candidates.",
    )
    gemini_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum Gemini confidence to cut an aside candidate.",
    )


class DisruptionConfig(BaseModel):
    """Acoustic disruption detection — loud non-speech bursts (coughs, mic bumps)
    inside pauses. These bursts are computed from the denoised WAV and feed the
    audio-driven false-start rule."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Run acoustic disruption detection over the denoised audio.",
    )
    frame_ms: float = Field(
        default=25.0, gt=0.0, description="RMS analysis frame length in milliseconds."
    )
    hop_ms: float = Field(
        default=10.0, gt=0.0, description="RMS analysis hop length in milliseconds."
    )
    noise_floor_pct: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="Percentile of per-frame dB used as the per-file noise floor estimate.",
    )
    threshold_db: float = Field(
        default=22.0,
        gt=0.0,
        description=(
            "A burst must rise at least this many dB above the noise floor to count "
            "as a disruption. Coughs in these lessons sit 25-40 dB above the floor. "
            "98-video sweep: 22 (vs 15/18) cut false positives ~5x while keeping the "
            "real cough recoveries — marginal noise no longer qualifies."
        ),
    )
    speech_pad_s: float = Field(
        default=0.15,
        ge=0.0,
        description="Pad transcribed words by this much when masking out speech frames.",
    )
    min_burst_s: float = Field(
        default=0.05,
        ge=0.0,
        description="Ignore bursts shorter than this (clicks/sample noise).",
    )
    max_burst_s: float = Field(
        default=1.5,
        gt=0.0,
        description="Ignore bursts longer than this (sustained sound, not a transient).",
    )


class FalseStartAudioConfig(BaseModel):
    """Audio-driven false-start rule: cut a short, stranded phrase that sits right
    after an acoustic disruption (cough/noise) in a long pause and is followed by
    a prompt restart. This catches flubbed takes the transcript looks innocent for
    (e.g. a hesitant 'I dobro.' after the speaker coughs, before redoing the line)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Run the audio-driven false-start pass.",
    )
    max_words: int = Field(
        default=3,
        ge=1,
        description=(
            "Only short phrases (<= this many words) are candidates. 98-video sweep: "
            "3 (vs 4) roughly halves false positives — 4-word hits are mostly real "
            "content ('Što nam znači reschedule?'), 1-3-word hits are fillers."
        ),
    )
    min_gap_before_s: float = Field(
        default=4.0,
        ge=0.0,
        description=(
            "Require at least this long a pause before the phrase — flubbed restarts "
            "follow a noticeable hesitation, not a fluent hand-off."
        ),
    )
    max_gap_after_s: float = Field(
        default=3.5,
        ge=0.0,
        description=(
            "Require the speaker to resume within this long after the phrase — the "
            "real take follows promptly. Guards against cutting a genuine closing line."
        ),
    )
    require_disruption: bool = Field(
        default=True,
        description=(
            "Require an acoustic disruption (cough/noise) inside the preceding pause. "
            "The disruption is the distinctive cue; turning this off falls back to a "
            "long-pause-only heuristic (higher recall, lower precision)."
        ),
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence assigned to an audio-driven false-start flag.",
    )


class RenderConfig(BaseModel):
    """Video render / assembly parameters."""

    model_config = ConfigDict(extra="allow")

    codec: str = Field(
        default="libx264",
        description="FFmpeg video codec (e.g. libx264, libx265).",
    )
    crf: int = Field(
        default=28,
        ge=0,
        le=51,
        description="Constant Rate Factor — lower is higher quality.",
    )
    preset: str = Field(
        default="ultrafast",
        description="FFmpeg encoding preset (ultrafast … veryslow).",
    )
    crossfade_ms: int = Field(
        default=30,
        ge=0,
        le=500,
        description="Audio crossfade duration at splice points (ms).",
    )
    output_suffix: str = Field(
        default="_edited",
        description="Suffix appended to the stem for the output filename.",
    )


class Settings(BaseSettings):
    """Root settings object. Nested sections added as phases land. Loaded from Python only (no env / dotenv)."""

    model_config = SettingsConfigDict(extra="allow")

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    duplicate_detection: DuplicateDetectionConfig = Field(default_factory=DuplicateDetectionConfig)
    section_editor: SectionEditorConfig = Field(default_factory=SectionEditorConfig)
    aside_detection: AsideDetectionConfig = Field(default_factory=AsideDetectionConfig)
    disruption: DisruptionConfig = Field(default_factory=DisruptionConfig)
    false_start_audio: FalseStartAudioConfig = Field(default_factory=FalseStartAudioConfig)
    cutting_llm: LangChainModelConfig = Field(default_factory=default_cutting_model_config)
    render: RenderConfig = Field(default_factory=RenderConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def load_settings_from_py_file(path: Path) -> Settings:
    """Load a `Settings` instance from a Python file (must define `settings`)."""
    spec = importlib.util.spec_from_file_location("user_pipeline_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "settings"):
        raise ValueError(
            f"Config file {path} must define a top-level variable named `settings` (Settings instance)."
        )
    user_settings = module.settings
    if not isinstance(user_settings, Settings):
        raise TypeError(
            f"`settings` in {path} must be an instance of ai_video_editor.config.Settings, got {type(user_settings)}"
        )
    return user_settings


def get_settings(*, config_path: Path | None = None) -> Settings:
    if config_path is None:
        return Settings()
    return load_settings_from_py_file(config_path)
