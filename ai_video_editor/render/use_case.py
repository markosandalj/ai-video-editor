from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, Protocol

from ai_video_editor.config.settings import RenderConfig
from ai_video_editor.duplicate.edl import (
    EditAction,
    EditDecision,
    EditDecisionList,
    EditReason,
)
from ai_video_editor.render.assemble import render_video


class MillisecondRange(Protocol):
    start_ms: int
    end_ms: int


class InvalidRenderMediaError(Exception):
    """The closed render inputs cannot produce a valid video."""


class RenderProcessingError(Exception):
    """FFmpeg failed after the closed render inputs were validated."""


class RenderUseCase:
    """Reusable headless final-render operation shared by the CLI and worker."""

    def execute(
        self,
        video_path: Path,
        edl: EditDecisionList,
        processed_audio_path: Path,
        config: RenderConfig | None = None,
    ) -> Path:
        _validate_media(video_path, processed_audio_path)
        try:
            return render_video(video_path, edl, processed_audio_path, config)
        except ValueError as exc:
            raise InvalidRenderMediaError("No media remains after applying cuts") from exc
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            raise RenderProcessingError("Final video rendering failed") from exc

    def execute_cut_ranges(
        self,
        video_path: Path,
        processed_audio_path: Path,
        *,
        duration_ms: int,
        cut_ranges: Iterable[MillisecondRange],
        config: RenderConfig | None = None,
    ) -> Path:
        edl = edit_decision_list_from_cut_ranges(
            video_path,
            duration_ms=duration_ms,
            cut_ranges=cut_ranges,
        )
        return self.execute(video_path, edl, processed_audio_path, config)


def edit_decision_list_from_cut_ranges(
    video_path: Path,
    *,
    duration_ms: int,
    cut_ranges: Iterable[MillisecondRange],
) -> EditDecisionList:
    """Convert canonical half-open millisecond cuts to a complete render EDL."""

    decisions: list[EditDecision] = []
    cursor_ms = 0
    for cut_range in cut_ranges:
        if cut_range.start_ms > cursor_ms:
            decisions.append(
                _decision(cursor_ms, cut_range.start_ms, EditAction.KEEP)
            )
        decisions.append(
            _decision(cut_range.start_ms, cut_range.end_ms, EditAction.CUT)
        )
        cursor_ms = cut_range.end_ms
    if cursor_ms < duration_ms:
        decisions.append(_decision(cursor_ms, duration_ms, EditAction.KEEP))
    return EditDecisionList(
        source_video=str(video_path),
        total_duration=duration_ms / 1000,
        decisions=decisions,
    )


def _decision(start_ms: int, end_ms: int, action: EditAction) -> EditDecision:
    return EditDecision(
        start=start_ms / 1000,
        end=end_ms / 1000,
        action=action,
        reason=EditReason.SPEECH if action == EditAction.KEEP else EditReason.SILENCE,
    )


def _validate_media(video_path: Path, audio_path: Path) -> None:
    if not video_path.is_file() or not audio_path.is_file():
        raise InvalidRenderMediaError("Render media is missing")
    try:
        video = _probe(video_path)
        audio = _probe(audio_path)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidRenderMediaError("Render media could not be inspected") from exc
    if not any(stream.get("codec_type") == "video" for stream in video["streams"]):
        raise InvalidRenderMediaError("Source has no video stream")
    if not any(stream.get("codec_type") == "audio" for stream in audio["streams"]):
        raise InvalidRenderMediaError("Processed audio has no audio stream")


def _probe(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get("streams"), list):
        raise ValueError("Invalid ffprobe response")
    return payload
