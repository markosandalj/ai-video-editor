from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ai_video_editor.render import RenderUseCase
from ai_video_editor.worker.contracts import CutRange
from tests.test_analysis import create_tiny_video, probe


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_real_render_applies_half_open_millisecond_cuts(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    processed_audio = tmp_path / "processed.flac"
    create_tiny_video(source, duration=1.2)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "flac",
            str(processed_audio),
        ],
        check=True,
        capture_output=True,
    )

    rendered = RenderUseCase().execute_cut_ranges(
        source,
        processed_audio,
        duration_ms=1200,
        cut_ranges=[CutRange(start_ms=300, end_ms=700)],
    )

    media = probe(rendered)
    assert {stream["codec_type"] for stream in media["streams"]} == {
        "audio",
        "video",
    }
    assert float(media["format"]["duration"]) == pytest.approx(0.8, abs=0.08)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_render_failure_preserves_ffmpeg_stderr_as_internal_cause(tmp_path):
    from ai_video_editor.config.settings import RenderConfig
    from ai_video_editor.render import RenderProcessingError

    source = tmp_path / "source.mp4"
    create_tiny_video(source, duration=0.2)
    with pytest.raises(RenderProcessingError) as raised:
        RenderUseCase().execute_cut_ranges(
            source, source, duration_ms=200, cut_ranges=[],
            config=RenderConfig(codec="missing_test_encoder"),
        )
    cause = raised.value.__cause__
    assert isinstance(cause, subprocess.CalledProcessError)
    assert cause.returncode != 0
    assert "missing_test_encoder" in cause.stderr
    assert "missing_test_encoder" not in str(raised.value)
