from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.transcription.models import Transcript


def cache_path_for(video_path: Path) -> Path:
    return video_path.with_suffix(".transcript.json")


def load_cached_transcript(video_path: Path) -> Transcript | None:
    path = cache_path_for(video_path)
    if not path.exists():
        return None
    logger.info("Loading cached transcript: {}", path.name)
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


def save_transcript(video_path: Path, transcript: Transcript) -> Path:
    path = cache_path_for(video_path)
    path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved transcript cache: {}", path.name)
    return path
