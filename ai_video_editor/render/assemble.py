from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from ai_video_editor.config.settings import RenderConfig
from ai_video_editor.duplicate.edl import EditAction, EditDecisionList


def render_video(
    video_path: Path,
    edl: EditDecisionList,
    denoised_audio_path: Path,
    cfg: RenderConfig | None = None,
) -> Path:
    """
    Render the final edited video by concatenating EDL keep segments.

    Uses the original video for the video stream and the denoised WAV
    for the audio stream.  All segments are re-encoded with the configured
    codec/CRF/preset, and 30ms audio fades are applied at splice boundaries.

    Returns the path to the rendered output file.
    """
    if cfg is None:
        cfg = RenderConfig()

    keep_segments = [d for d in edl.decisions if d.action == EditAction.KEEP]
    if not keep_segments:
        raise ValueError("EDL contains no keep segments — nothing to render")

    output_path = video_path.with_name(
        f"{video_path.stem}{cfg.output_suffix}.mp4"
    )
    fade_s = cfg.crossfade_ms / 1000.0
    n = len(keep_segments)

    filter_parts: list[str] = []
    v_concat_inputs: list[str] = []
    a_concat_inputs: list[str] = []

    for i, seg in enumerate(keep_segments):
        vl = f"[0:v]trim=start={seg.start}:end={seg.end},setpts=PTS-STARTPTS[v{i}]"
        filter_parts.append(vl)

        a_trim = (
            f"[1:a]atrim=start={seg.start}:end={seg.end},asetpts=PTS-STARTPTS"
        )
        if fade_s > 0:
            seg_dur = seg.end - seg.start
            fade_out_start = max(seg_dur - fade_s, 0)
            a_trim += f",afade=t=in:st=0:d={fade_s},afade=t=out:st={fade_out_start}:d={fade_s}"
        a_trim += f"[a{i}]"
        filter_parts.append(a_trim)

        v_concat_inputs.append(f"[v{i}]")
        a_concat_inputs.append(f"[a{i}]")

    concat_inputs = "".join(
        f"{v}{a}" for v, a in zip(v_concat_inputs, a_concat_inputs)
    )
    filter_parts.append(
        f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
    )

    filter_complex = ";\n".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(denoised_audio_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", cfg.codec,
        "-crf", str(cfg.crf),
        "-preset", cfg.preset,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.info(
        "Rendering {} keep segments → {} (codec={}, crf={}, preset={}, crossfade={}ms)",
        n, output_path.name, cfg.codec, cfg.crf, cfg.preset, cfg.crossfade_ms,
    )
    logger.debug("FFmpeg command: {}", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("FFmpeg stderr:\n{}", result.stderr[-2000:] if result.stderr else "(empty)")
        raise RuntimeError(
            f"FFmpeg render failed (exit {result.returncode}). "
            f"Check logs for details."
        )

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Render complete: {} ({:.1f} MB)", output_path.name, size_mb)
    return output_path
