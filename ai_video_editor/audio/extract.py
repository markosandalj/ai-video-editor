from __future__ import annotations

from pathlib import Path

import ffmpeg
from loguru import logger

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.config.settings import Settings


def _probe_audio(video_path: Path) -> dict:
    """Return the first audio stream info via ffprobe."""
    probe = ffmpeg.probe(str(video_path))
    audio_streams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    if not audio_streams:
        raise RuntimeError(f"No audio stream found in {video_path}")
    return audio_streams[0]


def extract_audio(video_path: Path, settings: Settings) -> AudioMeta:
    """
    Extract audio from *video_path* to a mono WAV in temp_dir.
    Preserves the source sample rate.
    """
    temp_dir = settings.general.temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)

    probe_info = _probe_audio(video_path)
    sample_rate = int(probe_info["sample_rate"])

    out_path = temp_dir / f"{video_path.stem}_raw.wav"

    logger.info(
        "Extracting audio: {} → {} ({}Hz mono)",
        video_path.name,
        out_path.name,
        sample_rate,
    )

    (
        ffmpeg.input(str(video_path))
        .output(str(out_path), acodec="pcm_s16le", ac=1, ar=sample_rate)
        .overwrite_output()
        .run(quiet=True)
    )

    duration_cmd = ffmpeg.probe(str(out_path))
    duration_s = float(duration_cmd["format"]["duration"])

    meta = AudioMeta(
        source_video=str(video_path),
        sample_rate=sample_rate,
        channels=1,
        duration_s=duration_s,
        path=str(out_path),
    )
    logger.debug("Audio extraction complete: {:.1f}s @ {}Hz", duration_s, sample_rate)
    return meta
