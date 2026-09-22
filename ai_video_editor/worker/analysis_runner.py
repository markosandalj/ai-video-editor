from __future__ import annotations

import math
from typing import Callable
from uuid import UUID

from ai_video_editor.analysis import AnalysisOutput, AnalysisUseCase, InvalidMediaError
from ai_video_editor.audio.snap import acoustic_split_points, envelope_to_peaks
from ai_video_editor.config.settings import Settings
from ai_video_editor.config.settings import RenderConfig
from ai_video_editor.duplicate.edl import EditAction
from ai_video_editor.worker.contracts import (
    AnalysisJobRequest,
    AnalysisResultV1,
    AutomaticCutRange,
    Diagnostics,
    RenderJobRequest,
    RenderResultV1,
    ResolvedRenderConfigV1,
    S3ObjectReference,
    TimedWord,
    Waveform,
    job_request_adapter,
)
from ai_video_editor.worker.executor import MediaExecutionFailure
from ai_video_editor.worker.providers import (
    AnalysisArtifactStore,
    ArtifactUploadFailed,
    DriveSourceProvider,
    DriveOutputProvider,
    DuplicateOutputArtifacts,
    GoogleDriveSourceProvider,
    GoogleDriveOutputProvider,
    OutputUploadFailed,
    ProcessedAudioDownloadFailed,
    ProcessedAudioMissing,
    ProcessedAudioProvider,
    R2AnalysisArtifactStore,
    R2ProcessedAudioProvider,
    SourceAccessDenied,
    SourceChanged,
    SourceDownloadFailed,
    SourceNotFound,
)
from ai_video_editor.worker.settings import WorkerSettings
from ai_video_editor.render import (
    InvalidRenderMediaError,
    RenderProcessingError,
    RenderUseCase,
)


def run_configured_media_job(
    job_id: UUID,
    payload: dict[str, object],
    resolved_render_config: dict[str, object] | None,
    progress: Callable[[int, str], None],
) -> dict[str, object]:
    request = job_request_adapter.validate_python(payload)
    settings = WorkerSettings()
    drive = GoogleDriveSourceProvider.from_oauth(
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret,
        refresh_token=settings.google_drive_refresh_token,
    )
    if isinstance(request, AnalysisJobRequest):
        artifacts = R2AnalysisArtifactStore.from_credentials(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
        return execute_analysis_job(
            job_id,
            request,
            settings=settings,
            drive=drive,
            artifacts=artifacts,
            progress=progress,
        ).model_dump(mode="json", by_alias=True)

    if resolved_render_config is None:
        raise MediaExecutionFailure(
            code="processing_failed",
            stage="accepted",
            message="Render configuration is missing",
        )
    config = ResolvedRenderConfigV1.model_validate(resolved_render_config)
    processed_audio = R2ProcessedAudioProvider.from_credentials(
        endpoint_url=settings.s3_endpoint_url,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
    output = GoogleDriveOutputProvider.from_oauth(
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret,
        refresh_token=settings.google_drive_refresh_token,
    )
    return execute_render_job(
        job_id,
        request,
        resolved_config=config,
        settings=settings,
        drive=drive,
        processed_audio=processed_audio,
        output=output,
        progress=progress,
    ).model_dump(mode="json", by_alias=True)


def execute_analysis_job(
    job_id: UUID,
    request: AnalysisJobRequest,
    *,
    settings: WorkerSettings,
    drive: DriveSourceProvider,
    artifacts: AnalysisArtifactStore,
    progress: Callable[[int, str], None],
    use_case_factory: Callable[[Settings], AnalysisUseCase] = AnalysisUseCase,
) -> AnalysisResultV1:
    job_dir = settings.scratch_dir / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / "source.mp4"
    progress(5, "downloading_source")
    try:
        drive.download(request.source, source_path)
    except SourceNotFound as exc:
        raise _source_failure("source_not_found", "Source media was not found") from exc
    except SourceAccessDenied as exc:
        raise _source_failure("source_access_denied", "Source media access was denied") from exc
    except SourceChanged as exc:
        raise _source_failure("source_changed", "Source media changed after confirmation") from exc
    except SourceDownloadFailed as exc:
        raise _source_failure("source_download_failed", "Could not download source media") from exc

    default_pipeline_settings = Settings()
    pipeline_settings = default_pipeline_settings.model_copy(
        update={
            "general": default_pipeline_settings.general.model_copy(
                update={"temp_dir": job_dir}
            )
        }
    )
    try:
        output = use_case_factory(pipeline_settings).execute(
            source_path,
            progress=progress,
        )
    except InvalidMediaError as exc:
        raise MediaExecutionFailure(
            code="invalid_media",
            stage=exc.stage,
            message="Source is not a supported video with audio",
        ) from exc

    progress(95, "uploading_artifacts")
    try:
        review_proxy = artifacts.upload(
            output.review_proxy_path,
            key=f"jobs/{job_id}/review-proxy.mp4",
            mime_type="video/mp4",
        )
        processed_audio = artifacts.upload(
            output.processed_audio_path,
            key=f"jobs/{job_id}/processed-audio.flac",
            mime_type="audio/flac",
        )
    except ArtifactUploadFailed as exc:
        raise MediaExecutionFailure(
            code="artifact_upload_failed",
            stage="uploading_artifacts",
            message="Could not upload analysis artifacts",
        ) from exc
    return analysis_result_from_output(output, review_proxy, processed_audio)


def execute_render_job(
    job_id: UUID,
    request: RenderJobRequest,
    *,
    resolved_config: ResolvedRenderConfigV1,
    settings: WorkerSettings,
    drive: DriveSourceProvider,
    processed_audio: ProcessedAudioProvider,
    output: DriveOutputProvider,
    progress: Callable[[int, str], None],
    use_case_factory: Callable[[], RenderUseCase] = RenderUseCase,
) -> RenderResultV1:
    if resolved_config.render_profile != request.render_profile:
        raise MediaExecutionFailure(
            code="processing_failed",
            stage="accepted",
            message="Render configuration does not match the request",
        )

    progress(3, "checking_output")
    try:
        existing = output.find_completed(job_id, request.output)
    except DuplicateOutputArtifacts as exc:
        raise MediaExecutionFailure(
            code="duplicate_output_artifacts",
            stage="checking_output",
            message="Multiple final videos exist for this render attempt",
        ) from exc
    except OutputUploadFailed as exc:
        raise MediaExecutionFailure(
            code="output_upload_failed",
            stage="checking_output",
            message="Could not inspect the final video destination",
        ) from exc
    if existing is not None:
        return RenderResultV1(
            schema="render_result.v1",
            final_video=existing,
            diagnostics=Diagnostics(
                pipeline_version="student_video.v1",
                warnings=["reused_existing_output"],
            ),
        )

    job_dir = settings.scratch_dir / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / "source.mp4"
    processed_audio_path = job_dir / "processed-audio.flac"

    progress(8, "downloading_source")
    try:
        drive.download(request.source, source_path)
    except SourceNotFound as exc:
        raise _source_failure("source_not_found", "Source media was not found") from exc
    except SourceAccessDenied as exc:
        raise _source_failure("source_access_denied", "Source media access was denied") from exc
    except SourceChanged as exc:
        raise _source_failure("source_changed", "Source media changed after confirmation") from exc
    except SourceDownloadFailed as exc:
        raise _source_failure("source_download_failed", "Could not download source media") from exc

    progress(18, "downloading_processed_audio")
    try:
        processed_audio.download(request.processed_audio, processed_audio_path)
    except ProcessedAudioMissing as exc:
        raise MediaExecutionFailure(
            code="processed_audio_missing",
            stage="downloading_processed_audio",
            message="Processed audio was not found",
        ) from exc
    except ProcessedAudioDownloadFailed as exc:
        raise MediaExecutionFailure(
            code="processed_audio_download_failed",
            stage="downloading_processed_audio",
            message="Could not download processed audio",
        ) from exc

    progress(30, "rendering_final_video")
    render_config = RenderConfig(
        codec=resolved_config.codec,
        crf=resolved_config.crf,
        preset=resolved_config.preset,
        crossfade_ms=resolved_config.crossfade_ms,
        output_suffix=resolved_config.output_suffix,
    )
    try:
        rendered = use_case_factory().execute_cut_ranges(
            source_path,
            processed_audio_path,
            duration_ms=request.edit.duration_ms,
            cut_ranges=request.edit.cut_ranges,
            config=render_config,
        )
    except InvalidRenderMediaError as exc:
        raise MediaExecutionFailure(
            code="invalid_media",
            stage="rendering_final_video",
            message="Render inputs are not valid media",
        ) from exc
    except RenderProcessingError as exc:
        raise MediaExecutionFailure(
            code="processing_failed",
            stage="rendering_final_video",
            message="Final video rendering failed",
        ) from exc

    progress(90, "uploading_output")
    try:
        final_video = output.upload(job_id, rendered, request.output)
    except DuplicateOutputArtifacts as exc:
        raise MediaExecutionFailure(
            code="duplicate_output_artifacts",
            stage="uploading_output",
            message="Multiple final videos exist for this render attempt",
        ) from exc
    except OutputUploadFailed as exc:
        raise MediaExecutionFailure(
            code="output_upload_failed",
            stage="uploading_output",
            message="Could not upload the final video",
        ) from exc

    return RenderResultV1(
        schema="render_result.v1",
        final_video=final_video,
        diagnostics=Diagnostics(
            pipeline_version="student_video.v1",
            warnings=[],
        ),
    )


def analysis_result_from_output(
    output: AnalysisOutput,
    review_proxy: S3ObjectReference,
    processed_audio: S3ObjectReference,
) -> AnalysisResultV1:
    words = [word for sentence in output.transcript.sentences for word in sentence.words]
    split_points = acoustic_split_points(
        words,
        output.waveform,
        total_duration=output.duration_ms / 1000,
    )
    transcript: list[TimedWord] = []
    source_word_index = 0
    previous_end_ms = 0
    for sentence_index, sentence in enumerate(output.transcript.sentences):
        for word in sentence.words:
            start_ms = max(previous_end_ms, _ms(word.start))
            end_ms = min(output.duration_ms, max(start_ms + 1, _ms(word.end)))
            if start_ms >= output.duration_ms:
                source_word_index += 1
                continue
            cut_in_ms = min(
                output.duration_ms - 1,
                _bounded_ms(
                    split_points[source_word_index],
                    output.duration_ms,
                ),
            )
            cut_out_ms = min(
                output.duration_ms,
                max(
                    cut_in_ms + 1,
                    _bounded_ms(
                        split_points[source_word_index + 1],
                        output.duration_ms,
                        positive=True,
                    ),
                ),
            )
            transcript.append(
                TimedWord(
                    idx=len(transcript),
                    sentence_idx=sentence_index,
                    text=word.text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    cut_in_ms=cut_in_ms,
                    cut_out_ms=cut_out_ms,
                )
            )
            previous_end_ms = end_ms
            source_word_index += 1

    cuts: list[AutomaticCutRange] = []
    for decision in output.edl.decisions:
        if decision.action != EditAction.CUT:
            continue
        start_ms = _bounded_ms(decision.start, output.duration_ms)
        end_ms = _bounded_ms(decision.end, output.duration_ms, positive=True)
        if end_ms <= start_ms:
            continue
        cuts.append(
            AutomaticCutRange(
                start_ms=start_ms,
                end_ms=end_ms,
                reason=decision.reason.value,
                confidence=decision.confidence,
            )
        )
    sample_interval_ms = 100
    peaks = envelope_to_peaks(
        output.waveform,
        buckets=max(1, math.ceil(output.duration_ms / sample_interval_ms)),
    )
    return AnalysisResultV1(
        schema="analysis_result.v1",
        duration_ms=output.duration_ms,
        transcript=transcript,
        automatic_cut_ranges=cuts,
        waveform=Waveform(sample_interval_ms=sample_interval_ms, peaks=peaks),
        review_proxy=review_proxy,
        processed_audio=processed_audio,
        diagnostics=Diagnostics(
            pipeline_version="analysis.v1",
            warnings=list(output.warnings),
        ),
    )


def _source_failure(code: str, message: str) -> MediaExecutionFailure:
    return MediaExecutionFailure(
        code=code,
        stage="downloading_source",
        message=message,
    )


def _ms(seconds: float) -> int:
    return math.floor(seconds * 1000 + 0.5)


def _bounded_ms(seconds: float, duration_ms: int, *, positive: bool = False) -> int:
    lower = 1 if positive else 0
    return min(duration_ms, max(lower, _ms(seconds)))
