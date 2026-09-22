from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_video_editor.analysis import AnalysisUseCase
from ai_video_editor.config.settings import Settings
from ai_video_editor.duplicate.edl import (
    EditAction,
    EditDecision,
    EditDecisionList,
    EditReason,
)
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def create_tiny_video(path: Path, *, duration: float = 1.2) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=160x90:r=25:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=16000:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def fake_transcriber(denoised, video_path, settings) -> Transcript:
    del denoised, settings
    words = [
        Word(text="Prvi", start=0.1, end=0.35),
        Word(text="primjer", start=0.4, end=0.9),
    ]
    return Transcript(
        sentences=[Sentence(words=words, text="Prvi primjer", start=0.1, end=0.9)],
        source_video=str(video_path),
        language="hr",
        model_size="fake-stt",
    )


def fake_decisions(transcript, keeps, silences, settings, *, disruptions):
    del keeps, silences, settings, disruptions
    return EditDecisionList(
        source_video=transcript.source_video,
        total_duration=1.2,
        decisions=[
            EditDecision(
                start=0,
                end=0.5,
                action=EditAction.KEEP,
                reason=EditReason.SPEECH,
            ),
            EditDecision(
                start=0.5,
                end=0.8,
                action=EditAction.CUT,
                reason=EditReason.FALSE_START,
                confidence=0.8,
            ),
            EditDecision(
                start=0.8,
                end=1.2,
                action=EditAction.KEEP,
                reason=EditReason.SPEECH,
            ),
        ],
    )


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_analysis_use_case_builds_full_proxy_and_lossless_audio(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    create_tiny_video(source)
    settings = Settings().model_copy(
        update={
            "general": Settings().general.model_copy(
                update={"temp_dir": tmp_path / "scratch", "output_dir": tmp_path}
            )
        }
    )
    stages: list[str] = []

    output = AnalysisUseCase(
        settings,
        transcriber=fake_transcriber,
        decision_maker=fake_decisions,
    ).execute(source, progress=lambda percent, stage: stages.append(stage))

    assert output.duration_ms >= 1150
    assert output.processed_audio_path.exists()
    assert output.review_proxy_path.exists()
    assert probe(output.processed_audio_path)["streams"][0]["codec_name"] == "flac"
    proxy = probe(output.review_proxy_path)
    assert {stream["codec_type"] for stream in proxy["streams"]} == {"audio", "video"}
    assert float(proxy["format"]["duration"]) == pytest.approx(
        output.duration_ms / 1000,
        abs=0.08,
    )
    assert "transcribing" in stages
    assert "rendering_review_proxy" in stages
