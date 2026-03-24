from __future__ import annotations

import re
import subprocess
from pathlib import Path

from loguru import logger

from ai_video_editor.audio.models import AudioMeta, SilenceRegion
from ai_video_editor.config.settings import Settings

_RE_SILENCE_START = re.compile(r"silence_start:\s*([\d.]+)")
_RE_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")


def detect_silences(audio_meta: AudioMeta, settings: Settings) -> list[SilenceRegion]:
    """
    Run FFmpeg silencedetect on the audio file.
    Returns a list of SilenceRegion sorted by start time.
    """
    threshold = settings.audio.silence_threshold_db
    min_dur = settings.audio.silence_min_duration_s
    audio_path = audio_meta.path

    logger.info(
        "Silence detection: {} (threshold={}dB, min_duration={}s)",
        Path(audio_path).name,
        threshold,
        min_dur,
    )

    cmd = [
        "ffmpeg",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={threshold}dB:d={min_dur}",
        "-f", "null",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    starts: list[float] = [float(m.group(1)) for m in _RE_SILENCE_START.finditer(stderr)]
    ends: list[float] = [float(m.group(1)) for m in _RE_SILENCE_END.finditer(stderr)]

    if len(starts) > len(ends):
        ends.append(audio_meta.duration_s)

    regions = [SilenceRegion(start=s, end=e) for s, e in zip(starts, ends)]

    logger.info("Found {} silence regions (total {:.1f}s of silence)", len(regions), sum(r.duration for r in regions))
    for r in regions:
        logger.debug("  silence: {:.2f}s – {:.2f}s ({:.2f}s)", r.start, r.end, r.duration)

    return regions
