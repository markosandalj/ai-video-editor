from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import ffmpeg

from ai_video_editor.audio import (
    build_audio_envelope,
    build_disruptions,
    compute_keep_regions,
    detect_silences,
    extract_audio,
    reduce_noise,
    snap_edl_boundaries,
)
from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.audio.snap import AudioEnvelope
from ai_video_editor.config.settings import Settings
from ai_video_editor.decisions import decide_edits
from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.transcription.models import Transcript
from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar


ProgressReporter = Callable[[int, str], None]


class Transcriber(Protocol):
    def __call__(
        self,
        denoised: AudioMeta,
        video_path: Path,
        settings: Settings,
    ) -> Transcript: ...


class DecisionMaker(Protocol):
    def __call__(
        self,
        transcript: Transcript,
        keeps: list,
        silences: list,
        settings: Settings,
        *,
        disruptions: list,
    ) -> EditDecisionList: ...


@dataclass(frozen=True)
class AnalysisOutput:
    source_path: Path
    duration_ms: int
    transcript: Transcript
    edl: EditDecisionList
    waveform: AudioEnvelope
    processed_audio_path: Path
    review_proxy_path: Path
    warnings: tuple[str, ...] = ()


class InvalidMediaError(Exception):
    """The source could not produce the required complete media artifacts."""

    def __init__(self, message: str, *, stage: str):
        super().__init__(message)
        self.stage = stage


class AnalysisUseCase:
    """Analyze one verified local recording for a worker job."""

    def __init__(
        self,
        settings: Settings,
        *,
        transcriber: Transcriber = transcribe_with_elevenlabs_and_grammar,
        decision_maker: DecisionMaker = decide_edits,
    ):
        self.settings = settings
        self._transcriber = transcriber
        self._decision_maker = decision_maker

    def execute(
        self,
        video_path: Path,
        *,
        progress: ProgressReporter | None = None,
    ) -> AnalysisOutput:
        source = video_path.expanduser().resolve()
        report = progress or (lambda percent, stage: None)
        try:
            source_duration_s = _probe_source_duration(source)
            report(10, "extracting_audio")
            extracted = extract_audio(source, self.settings)
            report(25, "reducing_noise")
            denoised = reduce_noise(extracted, self.settings)
        except InvalidMediaError:
            raise
        except Exception as exc:
            raise InvalidMediaError(
                "Source is not a supported video with audio",
                stage="extracting_audio",
            ) from exc

        silences = detect_silences(denoised, self.settings)
        keeps = compute_keep_regions(
            silences,
            denoised.duration_s,
            self.settings,
        )

        report(45, "transcribing")
        transcript = self._transcriber(denoised, source, self.settings)

        report(65, "deciding_edits")
        disruptions = build_disruptions(
            Path(extracted.path),
            transcript,
            self.settings.disruption,
        )
        edl = self._decision_maker(
            transcript,
            keeps,
            silences,
            self.settings,
            disruptions=disruptions,
        )

        report(78, "building_review_artifacts")
        envelope = build_audio_envelope(Path(denoised.path))
        edl = snap_edl_boundaries(edl, transcript, envelope)

        artifacts_dir = self.settings.general.temp_dir
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        processed_audio = artifacts_dir / f"{source.stem}-processed-audio.flac"
        review_proxy = artifacts_dir / f"{source.stem}-review-proxy.mp4"
        _encode_processed_audio(Path(denoised.path), processed_audio)

        report(88, "rendering_review_proxy")
        _render_review_proxy(
            source,
            Path(denoised.path),
            review_proxy,
            duration_s=source_duration_s,
        )
        duration_ms = max(1, math.floor(source_duration_s * 1000 + 0.5))
        return AnalysisOutput(
            source_path=source,
            duration_ms=duration_ms,
            transcript=transcript,
            edl=edl,
            waveform=envelope,
            processed_audio_path=processed_audio,
            review_proxy_path=review_proxy,
        )


def _run_ffmpeg(command: list[str], *, failure: str, stage: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise InvalidMediaError(failure, stage=stage)


def _probe_source_duration(source: Path) -> float:
    probe = ffmpeg.probe(str(source))
    if not any(stream.get("codec_type") == "video" for stream in probe["streams"]):
        raise InvalidMediaError(
            "Source has no video stream",
            stage="extracting_audio",
        )
    duration = float(probe["format"]["duration"])
    if duration <= 0:
        raise InvalidMediaError(
            "Source has no positive duration",
            stage="extracting_audio",
        )
    return duration


def _encode_processed_audio(source_audio: Path, output: Path) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_audio),
            "-map",
            "0:a:0",
            "-c:a",
            "flac",
            str(output),
        ],
        failure="Could not encode lossless processed audio",
        stage="building_review_artifacts",
    )


def _render_review_proxy(
    source_video: Path,
    processed_audio: Path,
    output: Path,
    *,
    duration_s: float,
) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(processed_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            f"{duration_s:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ],
        failure="Could not render the full review proxy",
        stage="rendering_review_proxy",
    )
