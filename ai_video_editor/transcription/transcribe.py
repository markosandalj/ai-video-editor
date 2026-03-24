from __future__ import annotations

import gc
import os
from pathlib import Path

import torch
import whisperx
from loguru import logger

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.config.settings import Settings


def _load_dotenv() -> None:
    """Load .env from project root if present."""
    from dotenv import load_dotenv

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def transcribe_audio(audio_meta: AudioMeta, settings: Settings) -> dict:
    """
    Run WhisperX: transcribe + forced alignment.
    Returns raw WhisperX result dict with word-level timestamps.
    Model is loaded and unloaded within this call.

    Not used by the default CLI (ElevenLabs + grammar); kept for optional use.
    """
    _load_dotenv()

    cfg = settings.transcription
    audio_path = audio_meta.path

    logger.info(
        "Transcribing: {} (model={}, device={}, lang={})",
        Path(audio_path).name,
        cfg.model_size,
        cfg.device,
        cfg.language,
    )

    model = whisperx.load_model(
        cfg.model_size,
        cfg.device,
        compute_type=cfg.compute_type,
        language=cfg.language,
    )

    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=cfg.batch_size, language=cfg.language)

    logger.info(
        "Transcription complete: {} segments. Running forced alignment...",
        len(result["segments"]),
    )

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    hf_token = os.environ.get("HF_TOKEN")
    align_model, align_metadata = whisperx.load_align_model(
        language_code=cfg.language,
        device=cfg.device,
        model_name=None,
    )

    result = whisperx.align(
        result["segments"],
        align_model,
        align_metadata,
        audio,
        cfg.device,
        return_char_alignments=False,
    )

    del align_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    total_words = sum(len(seg.get("words", [])) for seg in result["segments"])
    logger.info("Forced alignment complete: {} words across {} segments", total_words, len(result["segments"]))

    return result
