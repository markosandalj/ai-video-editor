from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from loguru import logger

from ai_video_editor.transcription.models import AudioEvent, Word

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


def _parse_stt_tokens(raw_words: list[dict]) -> tuple[list[Word], list[AudioEvent]]:
    """Split ElevenLabs tokens into speech words and non-speech audio events.

    Scribe returns three token types: ``word``, ``spacing``, and ``audio_event``
    (e.g. ``(cough)``). We keep words and events; spacing is dropped. Events are
    returned separately so they never leak into the transcript text."""
    words: list[Word] = []
    events: list[AudioEvent] = []
    for w in raw_words:
        token_type = w.get("type")
        t = (w.get("text") or "").strip()
        if not t:
            continue
        if token_type == "word":
            words.append(Word(text=t, start=float(w["start"]), end=float(w["end"])))
        elif token_type == "audio_event":
            events.append(AudioEvent(text=t, start=float(w["start"]), end=float(w["end"])))
    return words, events


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
) -> tuple[list[Word], str, list[AudioEvent]]:
    """
    Transcribe audio or video via ElevenLabs Speech-to-Text (Scribe).

    Returns word-level timestamps (tokens with ``type == "word"``) plus any
    non-speech audio-event tokens (``type == "audio_event"``, e.g. ``(cough)``)
    when ``tag_audio_events`` is set. Spacing tokens are skipped. Audio events are
    returned separately so they never pollute the transcript text.

    Returns:
        (words, full_text, events) — ``full_text`` is the API transcript string.
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

    words, events = _parse_stt_tokens(raw_words)

    logger.info(
        "ElevenLabs STT complete: {} words, {} audio events, {} chars",
        len(words),
        len(events),
        len(text),
    )
    return words, text, events
