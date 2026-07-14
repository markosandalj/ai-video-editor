from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.config.settings import Settings
from ai_video_editor.transcription.chunking import chunk_into_sentences
from ai_video_editor.transcription.elevenlabs_stt import transcribe_elevenlabs
from ai_video_editor.transcription.grammar import correct_grammar
from ai_video_editor.transcription.grammar_report import save_grammar_report
from ai_video_editor.transcription.models import Transcript


def transcribe_with_elevenlabs_and_grammar(
    denoised: AudioMeta,
    video_path: Path,
    settings: Settings,
) -> Transcript:
    """
    Denoised audio → ElevenLabs Scribe → sentence chunking → Gemini grammar pass.
    """
    cfg = settings.transcription
    audio_path = Path(denoised.path)

    words, _, events = transcribe_elevenlabs(
        audio_path,
        language_code=cfg.language,
        model_id=cfg.elevenlabs_model_id,
        tag_audio_events=cfg.elevenlabs_tag_audio_events,
    )
    sentences = chunk_into_sentences(words, pause_split_s=cfg.pause_split_s)
    draft = Transcript(
        sentences=sentences,
        source_video=str(video_path),
        language=cfg.language,
        model_size=f"elevenlabs-{cfg.elevenlabs_model_id}",
        events=events,
    )

    corrected, report = correct_grammar(draft, max_passes=cfg.grammar_max_passes)
    save_grammar_report(video_path, report)
    logger.info(
        "Grammar correction: passes={} converged={} total_suggestions={} total_replacements={}",
        report.passes,
        report.converged,
        report.total_suggestions,
        report.total_corrections,
    )
    # The grammar pass only rewrites sentence text; carry the audio events
    # through untouched so the edit layer can use them.
    if not corrected.events and events:
        corrected = corrected.model_copy(update={"events": events})
    return corrected
