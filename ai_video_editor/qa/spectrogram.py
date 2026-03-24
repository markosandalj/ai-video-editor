from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from loguru import logger

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.qa.models import SpectrogramComparisonResult

SIMILARITY_THRESHOLD = 0.85


def _load_audio_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, sr


def _extract_audio_to_wav(video_path: Path) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-ac", "1",
         "-acodec", "pcm_s16le", tmp.name],
        capture_output=True,
    )
    return Path(tmp.name)


def _spectrogram(audio: np.ndarray, sr: int, n_fft: int = 1024) -> np.ndarray:
    """Compute magnitude spectrogram using STFT with numpy."""
    hop = n_fft // 4
    window = np.hanning(n_fft)
    n_frames = (len(audio) - n_fft) // hop + 1
    if n_frames <= 0:
        return np.array([[]])

    frames = np.stack([
        audio[i * hop : i * hop + n_fft] * window
        for i in range(n_frames)
    ])
    return np.abs(np.fft.rfft(frames, axis=1)).T


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Flatten and compute cosine similarity between two spectrograms."""
    min_cols = min(a.shape[1], b.shape[1])
    if min_cols == 0:
        return 0.0
    a_flat = a[:, :min_cols].flatten()
    b_flat = b[:, :min_cols].flatten()
    denom = np.linalg.norm(a_flat) * np.linalg.norm(b_flat)
    if denom == 0:
        return 0.0
    return float(np.dot(a_flat, b_flat) / denom)


def compare_spectrograms(
    rendered_video: Path,
    denoised_audio: Path,
    edl: EditDecisionList,
    *,
    threshold: float = SIMILARITY_THRESHOLD,
) -> SpectrogramComparisonResult:
    """
    Compare spectrogram of rendered audio against "expected" audio
    (the denoised WAV keep segments stitched in memory).
    """
    rendered_wav = _extract_audio_to_wav(rendered_video)
    rendered_audio, sr_r = _load_audio_mono(rendered_wav)
    rendered_wav.unlink(missing_ok=True)

    denoised_full, sr_d = _load_audio_mono(denoised_audio)

    keep_segments = [d for d in edl.decisions if d.action == EditAction.KEEP]
    expected_parts: list[np.ndarray] = []
    for seg in keep_segments:
        start_sample = int(seg.start * sr_d)
        end_sample = int(seg.end * sr_d)
        expected_parts.append(denoised_full[start_sample:end_sample])

    expected_audio = np.concatenate(expected_parts) if expected_parts else np.array([])

    min_len = min(len(rendered_audio), len(expected_audio))
    if min_len < 1024:
        logger.warning("Audio too short for spectrogram comparison")
        return SpectrogramComparisonResult(similarity_score=0.0, passed=False)

    spec_r = _spectrogram(rendered_audio[:min_len], sr_r)
    spec_e = _spectrogram(expected_audio[:min_len], sr_d)

    sim = _cosine_similarity(spec_r, spec_e)
    passed = sim >= threshold

    logger.info(
        "Spectrogram comparison: similarity={:.4f} threshold={} passed={}",
        sim, threshold, passed,
    )
    return SpectrogramComparisonResult(
        similarity_score=round(sim, 4),
        passed=passed,
    )
