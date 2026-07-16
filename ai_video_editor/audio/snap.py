"""Acoustic cut-boundary snapping.

Transcript timestamps describe words, but they are not reliable edit points.  This
module persists a compact RMS envelope and chooses a quiet, safe point near each
transcript boundary so preview and render can share the same splice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from ai_video_editor.audio.disruption import _frame_db


SCHEMA_VERSION = "audio.v1"
DB_MIN = -100.0
DB_MAX = 0.0


class TimedWord(Protocol):
    start: float
    end: float


class AudioEnvelope(BaseModel):
    """Quantized per-frame RMS energy stored beside a processed video."""

    version: str = SCHEMA_VERSION
    hop_ms: int = Field(gt=0)
    frame_ms: int = Field(gt=0)
    noise_floor_db: float
    duration_s: float = Field(ge=0.0)
    energy: list[int]
    db_min: float = DB_MIN
    db_max: float = DB_MAX

    @classmethod
    def from_db(
        cls,
        db: np.ndarray,
        *,
        hop_ms: int,
        frame_ms: int,
        noise_floor_db: float | None = None,
        duration_s: float | None = None,
    ) -> "AudioEnvelope":
        values = np.asarray(db, dtype=np.float64)
        floor = (
            float(np.percentile(values, 10))
            if noise_floor_db is None and values.size
            else float(noise_floor_db if noise_floor_db is not None else DB_MIN)
        )
        clipped = np.clip(values, DB_MIN, DB_MAX)
        quantized = np.rint((clipped - DB_MIN) * 255.0 / (DB_MAX - DB_MIN)).astype(np.uint8)
        inferred_duration = (
            ((max(0, len(values) - 1) * hop_ms) + frame_ms) / 1000.0
            if values.size
            else 0.0
        )
        return cls(
            hop_ms=hop_ms,
            frame_ms=frame_ms,
            noise_floor_db=round(floor, 3),
            duration_s=duration_s if duration_s is not None else inferred_duration,
            energy=quantized.tolist(),
        )

    def db_values(self) -> np.ndarray:
        values = np.asarray(self.energy, dtype=np.float64)
        return self.db_min + values * (self.db_max - self.db_min) / 255.0

    def frame_times(self) -> np.ndarray:
        center_s = self.frame_ms / 2000.0
        return center_s + np.arange(len(self.energy), dtype=np.float64) * self.hop_ms / 1000.0


def audio_envelope_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}.audio.json")


def build_audio_envelope(
    audio_path: Path,
    *,
    frame_ms: int = 25,
    hop_ms: int = 10,
) -> AudioEnvelope:
    samples, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    frame = max(1, round(frame_ms / 1000.0 * sample_rate))
    hop = max(1, round(hop_ms / 1000.0 * sample_rate))
    db = _frame_db(np.asarray(samples), frame, hop)
    floor = float(np.percentile(db, 10)) if db.size else DB_MIN
    return AudioEnvelope.from_db(
        db,
        hop_ms=hop_ms,
        frame_ms=frame_ms,
        noise_floor_db=floor,
        duration_s=len(samples) / sample_rate,
    )


def write_audio_envelope(video_path: Path, envelope: AudioEnvelope) -> Path:
    output = audio_envelope_path_for(video_path)
    output.write_text(envelope.model_dump_json(), encoding="utf-8")
    return output


def load_audio_envelope(video_path: Path) -> AudioEnvelope | None:
    path = audio_envelope_path_for(video_path)
    if not path.exists():
        return None
    return AudioEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def ensure_audio_envelope(video_path: Path, audio_path: Path | None) -> AudioEnvelope | None:
    envelope = load_audio_envelope(video_path)
    if envelope is not None or audio_path is None or not audio_path.exists():
        return envelope
    envelope = build_audio_envelope(audio_path)
    write_audio_envelope(video_path, envelope)
    return envelope


def envelope_to_peaks(envelope: AudioEnvelope, *, buckets: int) -> list[float]:
    """Downsample the RMS envelope into ``buckets`` normalized 0..1 peaks.

    Each bucket is the loudest frame within it, rescaled so the noise floor maps
    to ~0 and 0 dBFS maps to 1 — silence reads flat, speech reads tall. Suitable
    for a waveform strip; the client mirrors the values vertically.
    """
    db = envelope.db_values()
    count = db.size
    if count == 0:
        return []
    bucket_count = max(1, min(buckets, count))
    floor = envelope.noise_floor_db
    span = max(1e-6, envelope.db_max - floor)
    edges = np.linspace(0, count, bucket_count + 1).astype(int)
    peaks: list[float] = []
    for i in range(bucket_count):
        lo = edges[i]
        hi = max(lo + 1, edges[i + 1])
        peak_db = float(db[lo:hi].max())
        norm = (peak_db - floor) / span
        peaks.append(round(min(1.0, max(0.0, norm)), 3))
    return peaks


def snap_cut_boundary(
    timestamp: float,
    envelope: AudioEnvelope,
    *,
    window_s: float = 0.25,
    lo: float,
    hi: float,
    quiet_margin_db: float = 6.0,
) -> float:
    """Return the safest quiet frame near ``timestamp`` within ``lo``/``hi``.

    A sustained quiet run is safer than a one-frame energy dip. If no frame is
    below the noise-relative threshold, the lowest-energy frame is used.
    """
    lower = max(0.0, min(lo, hi))
    upper = max(lower, min(hi, envelope.duration_s or hi))
    fallback = round(min(max(timestamp, lower), upper), 3)
    db = envelope.db_values()
    if db.size == 0:
        return fallback

    times = envelope.frame_times()
    search_lo = max(lower, timestamp - window_s)
    search_hi = min(upper, timestamp + window_s)
    candidate_indices = np.flatnonzero((times >= search_lo) & (times <= search_hi))
    if candidate_indices.size == 0:
        return fallback

    candidate_db = db[candidate_indices]
    quiet = candidate_db <= envelope.noise_floor_db + quiet_margin_db
    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for pos, is_quiet in enumerate(quiet):
        if is_quiet and run_start is None:
            run_start = pos
        elif not is_quiet and run_start is not None:
            runs.append((run_start, pos - 1))
            run_start = None
    if run_start is not None:
        runs.append((run_start, len(quiet) - 1))

    if runs:
        start, end = min(
            runs,
            key=lambda run: (
                -(run[1] - run[0] + 1),
                abs(times[candidate_indices[(run[0] + run[1]) // 2]] - timestamp),
            ),
        )
        chosen = candidate_indices[(start + end) // 2]
    else:
        minimum = float(candidate_db.min())
        minima = candidate_indices[np.flatnonzero(candidate_db == minimum)]
        chosen = int(min(minima, key=lambda idx: abs(times[idx] - timestamp)))
    return round(min(max(float(times[chosen]), lower), upper), 3)


def acoustic_split_points(
    words: Sequence[TimedWord],
    envelope: AudioEnvelope,
    *,
    total_duration: float,
) -> list[float]:
    """One safe split before the first word, between each word, and after the last."""
    if not words:
        return []
    midpoints = [(word.start + word.end) / 2.0 for word in words]
    splits = [
        snap_cut_boundary(words[0].start, envelope, lo=0.0, hi=midpoints[0])
    ]
    for idx, (left, right) in enumerate(zip(words, words[1:])):
        target = (left.end + right.start) / 2.0
        splits.append(
            snap_cut_boundary(
                target,
                envelope,
                lo=midpoints[idx],
                hi=midpoints[idx + 1],
            )
        )
    splits.append(
        snap_cut_boundary(
            words[-1].end,
            envelope,
            lo=midpoints[-1],
            hi=total_duration,
        )
    )
    return splits


def snap_edl_boundaries(edl, transcript, envelope: AudioEnvelope):
    """Move every EDL action transition to a nearby safe acoustic split.

    The midpoint of the word on either side is a hard guard: even when no quiet
    frame exists, snapping cannot consume more than half of either word.
    """
    decisions = [decision.model_copy() for decision in edl.decisions]
    if len(decisions) < 2:
        return edl.model_copy(update={"decisions": decisions})

    words = sorted(
        (word for sentence in transcript.sentences for word in sentence.words),
        key=lambda word: (word.start, word.end),
    )
    midpoints = [(word.start + word.end) / 2.0 for word in words]
    splits = acoustic_split_points(words, envelope, total_duration=edl.total_duration)
    if not splits:
        return edl.model_copy(update={"decisions": decisions})
    previous = 0.0
    for idx in range(len(decisions) - 1):
        left = decisions[idx]
        right = decisions[idx + 1]
        boundary = (left.end + right.start) / 2.0
        split_idx = sum(midpoint <= boundary for midpoint in midpoints)
        snapped = min(max(splits[split_idx], previous, left.start), right.end)
        decisions[idx] = left.model_copy(update={"end": snapped})
        decisions[idx + 1] = right.model_copy(update={"start": snapped})
        previous = snapped
    return edl.model_copy(update={"decisions": decisions})
