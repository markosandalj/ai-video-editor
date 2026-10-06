from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.audio.silence import detect_silences
from ai_video_editor.config.settings import Settings


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.parametrize("silence_s, expected_count", [(1.99, 0), (2.01, 1)])
def test_default_detection_threshold_on_real_audio(
    tmp_path: Path, silence_s: float, expected_count: int,
) -> None:
    sample_rate = 16000
    tone_duration_s = 0.5
    tone_times = np.arange(round(tone_duration_s * sample_rate)) / sample_rate
    tone = 0.25 * np.sin(2 * np.pi * 440 * tone_times)
    samples = np.concatenate([tone, np.zeros(round(silence_s * sample_rate)), tone])
    audio_path = tmp_path / "two-second-boundary.wav"
    sf.write(audio_path, samples, sample_rate, subtype="PCM_16")
    audio = AudioMeta(
        source_video=str(audio_path),
        path=str(audio_path),
        sample_rate=sample_rate,
        channels=1,
        duration_s=len(samples) / sample_rate,
    )

    silences = detect_silences(audio, Settings())

    assert len(silences) == expected_count
    if expected_count:
        assert silences[0].start == pytest.approx(tone_duration_s, abs=0.001)
        assert silences[0].end == pytest.approx(tone_duration_s + silence_s, abs=0.001)
