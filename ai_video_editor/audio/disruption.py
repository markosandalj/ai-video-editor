"""Acoustic disruption detection — loud non-speech bursts inside pauses.

The edit pipeline is otherwise text-driven: it decides what to cut from the
transcript. But a human editor also *hears* the recording, and one of the
strongest cues for a flubbed take is a cough, throat-clear, mic bump, or other
noise in a pause. A speaker finishes a thought, coughs, mumbles a half-restart,
then redoes the line — the transcript shows only an innocuous short phrase, so
text-only logic keeps it. The cough is the tell.

This module finds those bursts. It deliberately looks *only* in the gaps between
transcribed words: a loud burst that doesn't overlap any word is, by
construction, non-speech. That sidesteps the hard problem of distinguishing a
cough from speech by timbre — we let the transcript define where speech is and
flag the loud stuff in between.

Detection is energy-based and self-calibrating: the noise floor is estimated
per file (a low percentile of frame energy), and a burst must rise a configured
margin above that floor. No model, no network — it runs on the same denoised WAV
the silence detector already uses.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from loguru import logger

from ai_video_editor.audio.models import DisruptionRegion
from ai_video_editor.config.settings import DisruptionConfig
from ai_video_editor.transcription.models import Sentence, Transcript


def _load_mono(path: Path, sample_rate: int) -> np.ndarray:
    """Decode any audio/video file to a mono float32 array via ffmpeg."""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(path),
        "-ac", "1", "-ar", str(sample_rate),
        "-f", "f32le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg decode failed for {path}: {proc.stderr.decode('utf-8', 'ignore')[:300]}"
        )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _frame_db(x: np.ndarray, frame: int, hop: int) -> np.ndarray:
    """Per-frame RMS in dBFS, computed cheaply via a cumulative energy sum."""
    if x.size < frame:
        return np.empty(0, dtype=np.float64)
    energy = np.square(x.astype(np.float64))
    csum = np.concatenate([[0.0], np.cumsum(energy)])
    n = 1 + (len(x) - frame) // hop
    starts = np.arange(n) * hop
    win_energy = csum[starts + frame] - csum[starts]
    rms = np.sqrt(win_energy / frame)
    return 20.0 * np.log10(rms + 1e-9)


def _speech_mask(
    sentences: list[Sentence], n_frames: int, hop: int, sample_rate: int, pad_s: float
) -> np.ndarray:
    """Frames that overlap a transcribed word (± pad) are speech, not disruptions."""
    mask = np.zeros(n_frames, dtype=bool)
    frames_per_s = sample_rate / hop
    for s in sentences:
        for w in s.words:
            a = int(max(0.0, w.start - pad_s) * frames_per_s)
            b = int((w.end + pad_s) * frames_per_s) + 1
            mask[a:min(b, n_frames)] = True
    return mask


def detect_disruptions(
    audio_path: Path,
    sentences: list[Sentence],
    cfg: DisruptionConfig,
    *,
    sample_rate: int = 16000,
) -> list[DisruptionRegion]:
    """Find loud non-speech bursts (coughs/noise) sitting inside pauses."""
    if not cfg.enabled:
        return []

    x = _load_mono(Path(audio_path), sample_rate)
    frame = max(1, int(cfg.frame_ms / 1000.0 * sample_rate))
    hop = max(1, int(cfg.hop_ms / 1000.0 * sample_rate))

    db = _frame_db(x, frame, hop)
    if db.size == 0:
        return []

    floor = float(np.percentile(db, cfg.noise_floor_pct))
    threshold = floor + cfg.threshold_db

    loud = db >= threshold
    speech = _speech_mask(sentences, db.size, hop, sample_rate, cfg.speech_pad_s)
    candidate = loud & ~speech

    regions: list[DisruptionRegion] = []
    i = 0
    n = db.size
    while i < n:
        if not candidate[i]:
            i += 1
            continue
        j = i
        while j < n and candidate[j]:
            j += 1
        start = i * hop / sample_rate
        end = (j * hop + frame) / sample_rate
        duration = end - start
        if cfg.min_burst_s <= duration <= cfg.max_burst_s:
            regions.append(DisruptionRegion(
                start=round(start, 3),
                end=round(end, 3),
                peak_db=round(float(db[i:j].max()), 1),
                floor_db=round(floor, 1),
            ))
        i = j

    logger.info(
        "Disruption detection: {} bursts (floor={:.0f}dB, threshold={:.0f}dB)",
        len(regions), floor, threshold,
    )
    return regions


def build_disruptions(
    audio_path: Path,
    transcript: Transcript,
    cfg: DisruptionConfig,
    *,
    sample_rate: int = 16000,
) -> list[DisruptionRegion]:
    """Combine energy-detected bursts with any STT-tagged audio events.

    Both feed the audio false-start rule. STT events (``(cough)``, ``(laughter)``)
    are a complementary, model-confirmed source — used when present, but the
    energy detector stands on its own when the transcript has no events (every
    cached transcript today)."""
    acoustic = detect_disruptions(audio_path, transcript.sentences, cfg, sample_rate=sample_rate)
    event_regions = [
        DisruptionRegion(
            start=e.start, end=e.end, peak_db=0.0, floor_db=0.0,
            source="stt_event", label=e.text,
        )
        for e in transcript.events
    ]
    return sorted(acoustic + event_regions, key=lambda d: d.start)
