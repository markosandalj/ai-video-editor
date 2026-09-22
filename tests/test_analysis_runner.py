from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ai_video_editor.analysis import AnalysisOutput, AnalysisUseCase
from ai_video_editor.audio.snap import AudioEnvelope
from ai_video_editor.duplicate.edl import (
    EditAction,
    EditDecision,
    EditDecisionList,
    EditReason,
)
from ai_video_editor.transcription.models import Sentence, Transcript, Word
from ai_video_editor.worker.analysis_runner import (
    analysis_result_from_output,
    execute_analysis_job,
    execute_render_job,
)
from ai_video_editor.worker.contracts import (
    GoogleDriveFinalVideo,
    ResolvedRenderConfigV1,
    S3ObjectReference,
    job_request_adapter,
)
from ai_video_editor.worker.executor import MediaExecutionFailure
from ai_video_editor.worker.providers import (
    DuplicateOutputArtifacts,
    OutputUploadFailed,
    ProcessedAudioDownloadFailed,
    ProcessedAudioMissing,
    ProcessedAudioSourceMismatch,
    SourceAccessDenied,
    SourceChanged,
    SourceDownloadFailed,
    SourceNotFound,
)
from ai_video_editor.worker.settings import WorkerSettings
from tests.test_analysis import create_tiny_video, fake_decisions, fake_transcriber, probe


FIXTURES = Path(__file__).parent / "data" / "worker_contract"


def worker_settings(tmp_path: Path) -> WorkerSettings:
    return WorkerSettings(
        AI_VIDEO_EDITOR_API_TOKEN="a" * 32,
        GRADIVO_VIDEO_CALLBACK_TOKEN="b" * 32,
        GRADIVO_VIDEO_CALLBACK_BASE_URL="https://gradivo.example",
        VIDEO_PROCESSING_STATE_DB_PATH=tmp_path / "jobs.sqlite3",
        VIDEO_PROCESSING_SCRATCH_DIR=tmp_path / "scratch",
    )


class FakeDrive:
    def __init__(self, source: Path):
        self.source = source

    def download(self, manifest, destination: Path) -> Path:
        del manifest
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.source, destination)
        return destination


class FakeArtifacts:
    def __init__(self):
        self.uploads: dict[str, bytes] = {}
        self.source_identities = {}

    def upload(self, source: Path, *, key: str, mime_type: str, source_identity=None) -> S3ObjectReference:
        content = source.read_bytes()
        self.uploads[key] = content
        self.source_identities[key] = source_identity
        return S3ObjectReference(
            type="s3_object",
            key=key,
            size_bytes=len(content),
            mime_type=mime_type,
            etag=f"etag-{len(self.uploads)}",
        )


def fake_use_case(settings):
    return AnalysisUseCase(
        settings,
        transcriber=fake_transcriber,
        decision_maker=fake_decisions,
    )


def test_real_analysis_media_with_fake_external_adapters(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    create_tiny_video(source)
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    artifacts = FakeArtifacts()
    stages: list[str] = []
    job_id = uuid4()

    result = execute_analysis_job(
        job_id,
        request,
        settings=worker_settings(tmp_path),
        drive=FakeDrive(source),
        artifacts=artifacts,
        progress=lambda percent, stage: stages.append(stage),
        use_case_factory=fake_use_case,
    )

    assert result.schema_version == "analysis_result.v1"
    assert result.transcript[0].start_ms == 100
    assert result.automatic_cut_ranges[0].reason == "false_start"
    assert result.review_proxy.key == f"jobs/{job_id}/review-proxy.mp4"
    assert result.processed_audio.key == f"jobs/{job_id}/processed-audio.flac"
    assert set(artifacts.uploads) == {result.review_proxy.key, result.processed_audio.key}
    assert artifacts.source_identities[result.processed_audio.key] == request.source
    assert artifacts.source_identities[result.review_proxy.key] is None
    assert probe(tmp_path / "scratch" / str(job_id) / "source-review-proxy.mp4")["format"]
    payload = result.model_dump(mode="json", by_alias=True)
    assert str(tmp_path) not in str(payload)
    assert "uploading_artifacts" in stages


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (SourceNotFound, "source_not_found"),
        (SourceAccessDenied, "source_access_denied"),
        (SourceChanged, "source_changed"),
        (SourceDownloadFailed, "source_download_failed"),
    ],
)
@pytest.mark.parametrize("operation", ["analysis", "render"])
def test_source_failures_have_stable_codes(tmp_path: Path, failure, code: str, operation) -> None:
    request = job_request_adapter.validate_json(
        (FIXTURES / f"{operation}-request.v1.json").read_text()
    )

    class FailingDrive:
        def download(self, manifest, destination):
            del manifest, destination
            raise failure

    class UnusedOutput:
        def find_completed(self, job_id, output):
            return None

    config = worker_settings(tmp_path)
    with pytest.raises(MediaExecutionFailure) as raised:
        common = dict(
            settings=config, drive=FailingDrive(), progress=lambda percent, stage: None,
        )
        if operation == "analysis":
            execute_analysis_job(
                UUID("018f1000-0000-7000-8000-000000000001"), request,
                artifacts=FakeArtifacts(), use_case_factory=fake_use_case, **common,
            )
        else:
            execute_render_job(
                UUID("018f1000-0000-7000-8000-000000000001"), request,
                resolved_config=config.resolve_render_config(),
                processed_audio=None, output=UnusedOutput(), **common,
            )

    assert isinstance(raised.value.__cause__, failure)
    assert raised.value.code == code
    assert raised.value.stage == "downloading_source"


def test_boundary_adapter_drops_sub_millisecond_cut_and_out_of_duration_word(
    tmp_path: Path,
) -> None:
    transcript = Transcript(
        sentences=[
            Sentence(
                text="inside outside",
                start=0.1,
                end=1.2,
                words=[
                    Word(text="inside", start=0.1, end=0.3),
                    Word(text="outside", start=1.1, end=1.2),
                ],
            )
        ],
        source_video=str(tmp_path / "source.mp4"),
        language="hr",
        model_size="fake",
    )
    output = AnalysisOutput(
        source_path=tmp_path / "source.mp4",
        duration_ms=1000,
        transcript=transcript,
        edl=EditDecisionList(
            source_video=transcript.source_video,
            total_duration=1,
            decisions=[
                EditDecision(
                    start=0.5,
                    end=0.5004,
                    action=EditAction.CUT,
                    reason=EditReason.SILENCE,
                )
            ],
        ),
        waveform=AudioEnvelope(
            hop_ms=10,
            frame_ms=25,
            noise_floor_db=-80,
            duration_s=1,
            energy=[10, 20, 30],
        ),
        processed_audio_path=tmp_path / "processed.flac",
        review_proxy_path=tmp_path / "proxy.mp4",
    )
    reference = S3ObjectReference(
        type="s3_object",
        key="jobs/job/artifact",
        size_bytes=1,
        mime_type="application/octet-stream",
        etag="etag",
    )

    result = analysis_result_from_output(output, reference, reference)

    assert [word.text for word in result.transcript] == ["inside"]
    assert result.transcript[0].idx == 0
    assert result.automatic_cut_ranges == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_real_render_job_uses_closed_inputs_without_analysis(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input.mp4"
    audio = tmp_path / "processed.flac"
    create_tiny_video(source, duration=1.2)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-vn", "-c:a", "flac", str(audio)],
        check=True,
        capture_output=True,
    )
    payload = json.loads(
        (FIXTURES / "render-request.v1.json").read_text()
    )
    payload["edit"] = {
        "schema": "cut_ranges.v1",
        "duration_ms": 1200,
        "cut_ranges": [{"start_ms": 300, "end_ms": 700}],
    }
    request = job_request_adapter.validate_python(payload)
    job_id = uuid4()
    stages: list[str] = []

    class FakeProcessedAudio:
        def download(self, reference, destination, *, source_identity):
            del reference
            shutil.copyfile(audio, destination)
            return destination

    class FakeOutput:
        rendered: bytes | None = None

        def find_completed(self, checked_job_id, destination):
            del checked_job_id, destination
            return None

        def upload(self, uploaded_job_id, rendered, destination):
            del uploaded_job_id, destination
            self.rendered = rendered.read_bytes()
            return GoogleDriveFinalVideo(
                type="google_drive",
                file_id="drive-final-1",
                head_revision_id="revision-final-1",
                size_bytes=len(self.rendered),
                mime_type="video/mp4",
                checksum={
                    "algorithm": "md5",
                    "value": hashlib.md5(
                        self.rendered, usedforsecurity=False
                    ).hexdigest(),
                },
            )

    monkeypatch.setattr(
        "ai_video_editor.analysis.AnalysisUseCase.execute",
        lambda *args, **kwargs: pytest.fail("render must not run analysis"),
    )
    fake_output = FakeOutput()
    result = execute_render_job(
        job_id,
        request,
        resolved_config=_resolved_render_config(),
        settings=worker_settings(tmp_path),
        drive=FakeDrive(source),
        processed_audio=FakeProcessedAudio(),
        output=fake_output,
        progress=lambda percent, stage: stages.append(stage),
    )

    assert result.schema_version == "render_result.v1"
    assert result.final_video.file_id == "drive-final-1"
    assert fake_output.rendered
    rendered_path = tmp_path / "rendered.mp4"
    rendered_path.write_bytes(fake_output.rendered)
    assert float(probe(rendered_path)["format"]["duration"]) == pytest.approx(
        0.8, abs=0.08
    )
    assert stages == [
        "checking_output",
        "downloading_source",
        "downloading_processed_audio",
        "rendering_final_video",
        "uploading_output",
    ]
    assert str(tmp_path) not in str(
        result.model_dump(mode="json", by_alias=True)
    )


def _resolved_render_config() -> ResolvedRenderConfigV1:
    return ResolvedRenderConfigV1(
        schema="resolved_render_config.v1",
        render_profile="student_video.v1",
        codec="libx264",
        crf=28,
        preset="ultrafast",
        crossfade_ms=30,
        output_suffix="-final",
        audio_codec="aac",
        audio_bitrate="192k",
        movflags="+faststart",
    )


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ProcessedAudioMissing, "processed_audio_missing"),
        (ProcessedAudioSourceMismatch, "invalid_media"),
        (ProcessedAudioDownloadFailed, "processed_audio_download_failed"),
    ],
)
def test_render_processed_audio_failures_have_stable_codes(
    failure,
    code: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    request = job_request_adapter.validate_json(
        (FIXTURES / "render-request.v1.json").read_text()
    )

    class FailingProcessedAudio:
        def download(self, reference, destination, *, source_identity):
            del reference, destination
            raise failure

    class EmptyOutput:
        def find_completed(self, job_id, destination):
            del job_id, destination
            return None

    with pytest.raises(MediaExecutionFailure) as raised:
        execute_render_job(
            uuid4(),
            request,
            resolved_config=_resolved_render_config(),
            settings=worker_settings(tmp_path),
            drive=FakeDrive(source),
            processed_audio=FailingProcessedAudio(),
            output=EmptyOutput(),
            progress=lambda percent, stage: None,
        )

    assert raised.value.code == code
    assert raised.value.stage == "downloading_processed_audio"
    assert str(tmp_path) not in raised.value.message


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (DuplicateOutputArtifacts, "duplicate_output_artifacts"),
        (OutputUploadFailed, "output_upload_failed"),
    ],
)
def test_render_output_lookup_failures_have_stable_codes(
    failure,
    code: str,
    tmp_path: Path,
) -> None:
    request = job_request_adapter.validate_json(
        (FIXTURES / "render-request.v1.json").read_text()
    )

    class FailingOutput:
        def find_completed(self, job_id, destination):
            del job_id, destination
            raise failure

    with pytest.raises(MediaExecutionFailure) as raised:
        execute_render_job(
            uuid4(),
            request,
            resolved_config=_resolved_render_config(),
            settings=worker_settings(tmp_path),
            drive=FakeDrive(tmp_path / "unused"),
            processed_audio=None,
            output=FailingOutput(),
            progress=lambda percent, stage: None,
        )

    assert raised.value.code == code
    assert raised.value.stage == "checking_output"
    assert str(tmp_path) not in raised.value.message
