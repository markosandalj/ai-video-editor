from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


NonNegativeMilliseconds = Annotated[int, Field(strict=True, ge=0)]
PositiveMilliseconds = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceChecksum(ClosedModel):
    algorithm: Literal["md5"]
    value: str = Field(min_length=1)


class GoogleDriveSource(ClosedModel):
    type: Literal["google_drive"]
    file_id: str = Field(min_length=1)
    head_revision_id: str = Field(min_length=1)
    size_bytes: int = Field(strict=True, ge=0)
    mime_type: str = Field(pattern=r"^video/")
    checksum: SourceChecksum | None = None


class AnalysisJobRequest(ClosedModel):
    operation: Literal["analysis"]
    source: GoogleDriveSource


class S3ObjectReference(ClosedModel):
    type: Literal["s3_object"]
    key: str = Field(min_length=1)
    size_bytes: int = Field(strict=True, gt=0)
    mime_type: str = Field(min_length=1)
    etag: str = Field(min_length=1)


class GoogleDriveOutput(ClosedModel):
    type: Literal["google_drive"]
    folder_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class CutRange(ClosedModel):
    start_ms: NonNegativeMilliseconds
    end_ms: PositiveMilliseconds

    @model_validator(mode="after")
    def validate_range(self) -> CutRange:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class RenderEditV1(ClosedModel):
    schema_version: Literal["cut_ranges.v1"] = Field(alias="schema")
    duration_ms: PositiveMilliseconds
    cut_ranges: list[CutRange]

    @model_validator(mode="after")
    def validate_ranges(self) -> RenderEditV1:
        previous_end: int | None = None
        for cut_range in self.cut_ranges:
            if cut_range.end_ms > self.duration_ms:
                raise ValueError("cut range exceeds duration_ms")
            if previous_end is not None and cut_range.start_ms <= previous_end:
                raise ValueError(
                    "cut ranges must be sorted, non-overlapping, and non-touching"
                )
            previous_end = cut_range.end_ms
        return self


class RenderJobRequest(ClosedModel):
    operation: Literal["render"]
    render_profile: Literal["student_video.v1"]
    source: GoogleDriveSource
    processed_audio: S3ObjectReference
    output: GoogleDriveOutput
    edit: RenderEditV1

    @model_validator(mode="after")
    def validate_processed_audio(self) -> RenderJobRequest:
        if self.processed_audio.mime_type != "audio/flac":
            raise ValueError("processed_audio must be audio/flac")
        return self


class ResolvedRenderConfigV1(ClosedModel):
    """Worker-owned concrete configuration durably bound to a render attempt."""

    schema_version: Literal["resolved_render_config.v1"] = Field(alias="schema")
    render_profile: Literal["student_video.v1"]
    codec: str = Field(min_length=1)
    crf: int = Field(strict=True, ge=0, le=51)
    preset: str = Field(min_length=1)
    crossfade_ms: int = Field(strict=True, ge=0, le=500)
    output_suffix: str = Field(min_length=1)
    audio_codec: Literal["aac"]
    audio_bitrate: str = Field(min_length=1)
    movflags: Literal["+faststart"]


JobRequest = Annotated[
    AnalysisJobRequest | RenderJobRequest,
    Field(discriminator="operation"),
]
job_request_adapter = TypeAdapter(JobRequest)


class Progress(ClosedModel):
    percent: int = Field(strict=True, ge=0, le=100)
    stage: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class TimedWord(ClosedModel):
    idx: NonNegativeInteger
    sentence_idx: NonNegativeInteger
    text: str = Field(min_length=1)
    start_ms: NonNegativeMilliseconds
    end_ms: PositiveMilliseconds
    cut_in_ms: NonNegativeMilliseconds | None = None
    cut_out_ms: PositiveMilliseconds | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> TimedWord:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if (
            self.cut_in_ms is not None
            and self.cut_out_ms is not None
            and self.cut_out_ms <= self.cut_in_ms
        ):
            raise ValueError("cut_out_ms must be greater than cut_in_ms")
        return self


class AutomaticCutRange(ClosedModel):
    start_ms: NonNegativeMilliseconds
    end_ms: PositiveMilliseconds
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> AutomaticCutRange:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class Waveform(ClosedModel):
    sample_interval_ms: PositiveMilliseconds
    peaks: list[float]


class Diagnostics(ClosedModel):
    pipeline_version: str = Field(min_length=1)
    warnings: list[str]


class AnalysisResultV1(ClosedModel):
    schema_version: Literal["analysis_result.v1"] = Field(alias="schema")
    duration_ms: PositiveMilliseconds
    transcript: list[TimedWord]
    automatic_cut_ranges: list[AutomaticCutRange]
    waveform: Waveform
    review_proxy: S3ObjectReference
    processed_audio: S3ObjectReference
    diagnostics: Diagnostics

    @model_validator(mode="after")
    def validate_timeline(self) -> AnalysisResultV1:
        previous_word_end = 0
        for word in self.transcript:
            if word.end_ms > self.duration_ms:
                raise ValueError("transcript word exceeds duration_ms")
            if word.cut_in_ms is not None and word.cut_in_ms > self.duration_ms:
                raise ValueError("word cut_in_ms exceeds duration_ms")
            if word.cut_out_ms is not None and word.cut_out_ms > self.duration_ms:
                raise ValueError("word cut_out_ms exceeds duration_ms")
            if word.start_ms < previous_word_end:
                raise ValueError("transcript words must be sorted and non-overlapping")
            previous_word_end = word.end_ms

        previous_cut_end = 0
        for cut_range in self.automatic_cut_ranges:
            if cut_range.end_ms > self.duration_ms:
                raise ValueError("cut range exceeds duration_ms")
            if cut_range.start_ms < previous_cut_end:
                raise ValueError("cut ranges must be sorted and non-overlapping")
            previous_cut_end = cut_range.end_ms
        return self


class GoogleDriveFinalVideo(ClosedModel):
    type: Literal["google_drive"]
    file_id: str = Field(min_length=1)
    head_revision_id: str = Field(min_length=1)
    size_bytes: int = Field(strict=True, gt=0)
    mime_type: Literal["video/mp4"]
    checksum: SourceChecksum


class RenderResultV1(ClosedModel):
    schema_version: Literal["render_result.v1"] = Field(alias="schema")
    final_video: GoogleDriveFinalVideo
    diagnostics: Diagnostics


JobResult = Annotated[
    AnalysisResultV1 | RenderResultV1,
    Field(discriminator="schema_version"),
]
job_result_adapter = TypeAdapter(JobResult)


class WorkerError(ClosedModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    stage: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=500)


class ProcessingSnapshot(ClosedModel):
    job_id: UUID
    operation: Literal["analysis", "render"]
    revision: int = Field(strict=True, gt=0)
    status: Literal["processing"]
    progress: Progress

    @model_validator(mode="after")
    def validate_progress(self) -> ProcessingSnapshot:
        if self.progress.percent >= 100:
            raise ValueError("processing progress must be below 100")
        return self


class CompletedSnapshot(ClosedModel):
    job_id: UUID
    operation: Literal["analysis", "render"]
    revision: int = Field(strict=True, gt=0)
    status: Literal["completed"]
    progress: Progress
    result: AnalysisResultV1 | RenderResultV1

    @model_validator(mode="after")
    def validate_result(self) -> CompletedSnapshot:
        if self.progress.percent != 100:
            raise ValueError("completed progress must equal 100")
        if self.operation == "analysis" and not isinstance(
            self.result, AnalysisResultV1
        ):
            raise ValueError("analysis completion requires analysis_result.v1")
        if self.operation == "render" and not isinstance(self.result, RenderResultV1):
            raise ValueError("render completion requires render_result.v1")
        return self


class FailedSnapshot(ClosedModel):
    job_id: UUID
    operation: Literal["analysis", "render"]
    revision: int = Field(strict=True, gt=0)
    status: Literal["failed"]
    progress: Progress
    error: WorkerError

    @model_validator(mode="after")
    def validate_failure(self) -> FailedSnapshot:
        if self.progress.percent >= 100:
            raise ValueError("failed progress must be below 100")
        if self.progress.stage != self.error.stage:
            raise ValueError("failed progress and error stages must match")
        return self


WorkerSnapshot = Annotated[
    ProcessingSnapshot | CompletedSnapshot | FailedSnapshot,
    Field(discriminator="status"),
]
worker_snapshot_adapter = TypeAdapter(WorkerSnapshot)


def semantic_payload(request: AnalysisJobRequest | RenderJobRequest) -> tuple[str, str]:
    payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return canonical_json, hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
