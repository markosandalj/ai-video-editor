from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from loguru import logger

from ai_video_editor.transcription.models import Word

MIME_BY_SUFFIX: dict[str, str] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


def _load_api_key() -> str:
    load_dotenv(Path.cwd() / ".env")
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not found. Add it to your .env file."
        )
    return key


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MIME_BY_SUFFIX:
        return MIME_BY_SUFFIX[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def transcribe_elevenlabs(
    file_path: Path,
    *,
    language_code: str = "hr",
    model_id: str = "scribe_v2",
    tag_audio_events: bool = False,
) -> tuple[list[Word], str]:
    """
    Transcribe audio or video via ElevenLabs Speech-to-Text (Scribe).

    Returns word-level timestamps (tokens with ``type == "word"`` only; spacing
    tokens from the API are skipped).

    Returns:
        (words, full_text) — ``full_text`` is the API transcript string.
    """
    path = file_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    api_key = _load_api_key()
    client = ElevenLabs(api_key=api_key)
    mime = _guess_mime(path)
    name = path.name

    logger.info(
        "ElevenLabs STT: {} (model={}, lang={}, mime={})",
        name,
        model_id,
        language_code,
        mime,
    )

    with open(path, "rb") as f:
        response = client.speech_to_text.convert(
            model_id=model_id,
            file=(name, f, mime),
            language_code=language_code,
            timestamps_granularity="word",
            tag_audio_events=tag_audio_events,
        )

    data = response.model_dump()
    text = (data.get("text") or "").strip()
    raw_words = data.get("words") or []

    words: list[Word] = []
    for w in raw_words:
        if w.get("type") != "word":
            continue
        t = (w.get("text") or "").strip()
        if not t:
            continue
        start = float(w["start"])
        end = float(w["end"])
        words.append(Word(text=t, start=start, end=end))

    logger.info(
        "ElevenLabs STT complete: {} words, {} chars",
        len(words),
        len(text),
    )
    return words, text
