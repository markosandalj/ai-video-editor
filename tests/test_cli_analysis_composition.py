from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ai_video_editor.analysis import AnalysisOutput
from ai_video_editor.audio.snap import AudioEnvelope
from ai_video_editor.cli.app import app
from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.transcription.models import Transcript


def test_process_command_composes_shared_analysis_use_case(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    processed_audio = tmp_path / "processed.flac"
    processed_audio.write_bytes(b"audio")
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"proxy")
    transcript = Transcript(
        sentences=[],
        source_video=str(source),
        language="hr",
        model_size="fake",
    )
    edl = EditDecisionList(source_video=str(source), total_duration=1)
    output = AnalysisOutput(
        source_path=source,
        duration_ms=1000,
        transcript=transcript,
        edl=edl,
        waveform=AudioEnvelope(
            hop_ms=10,
            frame_ms=25,
            noise_floor_db=-80,
            duration_s=1,
            energy=[0],
        ),
        processed_audio_path=processed_audio,
        review_proxy_path=proxy,
    )
    calls: list[tuple] = []

    class FakeAnalysisUseCase:
        def __init__(self, settings, *, persistence):
            calls.append(("init", settings, persistence))

        def execute(self, video_path, *, force):
            calls.append(("execute", video_path, force))
            return output

    class FakeRenderUseCase:
        def __init__(self):
            calls.append(("render_init",))

        def execute(self, video_path, decisions, audio_path, render_settings):
            calls.append(("render", video_path, decisions, audio_path, render_settings))
            rendered = tmp_path / "input_edited.mp4"
            rendered.write_bytes(b"rendered")
            return rendered

    monkeypatch.setattr("ai_video_editor.analysis.AnalysisUseCase", FakeAnalysisUseCase)
    monkeypatch.setattr("ai_video_editor.render.RenderUseCase", FakeRenderUseCase)

    result = CliRunner().invoke(app, ["process", str(source)])

    assert result.exit_code == 0, result.output
    assert [call[0] for call in calls] == ["init", "execute", "render_init", "render"]
    assert calls[3][3] == processed_audio
