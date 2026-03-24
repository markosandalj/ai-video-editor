from __future__ import annotations

from pathlib import Path

import numpy as np
import noisereduce as nr
import soundfile as sf
from loguru import logger

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.config.settings import Settings


def reduce_noise(audio_meta: AudioMeta, settings: Settings) -> AudioMeta:
    """
    Apply non-stationary spectral gating to the extracted audio.
    Returns updated AudioMeta pointing to the denoised WAV.
    """
    in_path = Path(audio_meta.path)
    temp_dir = settings.general.temp_dir
    out_path = temp_dir / f"{in_path.stem.removesuffix('_raw')}_denoised.wav"

    logger.info("Noise reduction: {} → {}", in_path.name, out_path.name)

    audio_data, sr = sf.read(str(in_path), dtype="float32")

    reduced = nr.reduce_noise(
        y=audio_data,
        sr=sr,
        stationary=False,
        prop_decrease=settings.audio.noise_reduction_strength,
    )

    sf.write(str(out_path), reduced, sr, subtype="PCM_16")

    logger.debug("Noise reduction complete: prop_decrease={}", settings.audio.noise_reduction_strength)

    return AudioMeta(
        source_video=audio_meta.source_video,
        sample_rate=sr,
        channels=1,
        duration_s=audio_meta.duration_s,
        path=str(out_path),
    )
