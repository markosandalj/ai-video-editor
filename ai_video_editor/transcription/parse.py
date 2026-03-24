from __future__ import annotations

from loguru import logger

from ai_video_editor.transcription.models import Word


def parse_whisperx_output(result: dict) -> list[Word]:
    """
    Parse WhisperX result dict into a flat list of Word objects.
    Words with missing start/end timestamps are dropped.

    Used with :func:`transcribe_audio` only; the CLI uses ElevenLabs + grammar.
    """
    words: list[Word] = []
    dropped = 0

    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            start = w.get("start")
            end = w.get("end")
            text = w.get("word", "").strip()

            if start is None or end is None or not text:
                dropped += 1
                continue

            words.append(Word(text=text, start=float(start), end=float(end)))

    if dropped:
        logger.warning("Dropped {} words with missing timestamps", dropped)

    logger.debug("Parsed {} words from WhisperX output", len(words))
    return words
