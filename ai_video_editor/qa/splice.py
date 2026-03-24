from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from loguru import logger

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.qa.models import SpliceAnalysisResult

WINDOW_MS = 50
AMPLITUDE_THRESHOLD = 0.3


def analyze_splices(
    rendered_video: Path,
    edl: EditDecisionList,
    *,
    window_ms: int = WINDOW_MS,
    threshold: float = AMPLITUDE_THRESHOLD,
) -> SpliceAnalysisResult:
    """
    Check for harsh audio splices at cut boundaries in the rendered video.

    Extracts audio from the rendered file and measures amplitude deltas
    at each splice point (transition between consecutive keep segments
    in the recalculated timeline).
    """
    import subprocess
    import tempfile

    keep_segments = [d for d in edl.decisions if d.action == EditAction.KEEP]
    if len(keep_segments) < 2:
        return SpliceAnalysisResult(total_splices=0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(rendered_video), "-ac", "1",
         "-acodec", "pcm_s16le", str(tmp_path)],
        capture_output=True,
    )

    audio, sr = sf.read(str(tmp_path), dtype="float32")
    tmp_path.unlink(missing_ok=True)

    cumulative = 0.0
    splice_times: list[float] = []
    for i, seg in enumerate(keep_segments[:-1]):
        cumulative += seg.end - seg.start
        splice_times.append(cumulative)

    window_samples = int(sr * window_ms / 2000)
    details: list[dict] = []
    harsh_count = 0
    max_delta = 0.0

    for t in splice_times:
        sample_idx = int(t * sr)
        lo = max(0, sample_idx - window_samples)
        hi = min(len(audio), sample_idx + window_samples)

        if lo >= hi or sample_idx >= len(audio):
            continue

        before = audio[lo:sample_idx]
        after = audio[sample_idx:hi]

        if len(before) == 0 or len(after) == 0:
            continue

        rms_before = float(np.sqrt(np.mean(before ** 2)))
        rms_after = float(np.sqrt(np.mean(after ** 2)))
        delta = abs(rms_after - rms_before)

        is_harsh = delta > threshold
        if is_harsh:
            harsh_count += 1
        max_delta = max(max_delta, delta)

        details.append({
            "time": round(t, 3),
            "delta": round(delta, 4),
            "rms_before": round(rms_before, 4),
            "rms_after": round(rms_after, 4),
            "harsh": is_harsh,
        })

    result = SpliceAnalysisResult(
        total_splices=len(splice_times),
        harsh_splices=harsh_count,
        max_amplitude_delta=round(max_delta, 4),
        splice_details=details,
    )

    logger.info(
        "Splice analysis: {}/{} harsh (threshold={}, max_delta={:.4f})",
        harsh_count, len(splice_times), threshold, max_delta,
    )
    return result
