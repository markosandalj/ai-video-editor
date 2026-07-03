from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_video_editor.config.settings import RenderConfig
from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.render import render_video
from ai_video_editor.review import (
    ReviewPayload,
    ReviewSaveRequest,
    ReviewSaveResponse,
    ReviewVideoSummary,
    load_review_payload,
    review_edl_path_for,
    save_reviewed_edl,
)
from ai_video_editor.web.diff import DiffPayload, build_diff_payload


class RenderResponse(BaseModel):
    output_path: str
    output_name: str


def create_app(
    media_root: Path | str = Path.cwd(),
    frontend_dist: Path | str | None = None,
) -> FastAPI:
    root = Path(media_root).expanduser().resolve()
    app = FastAPI(title="AI Video Editor Review API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/videos", response_model=list[ReviewVideoSummary])
    def list_videos() -> list[ReviewVideoSummary]:
        return [_summary_for(path) for path in _discover_videos(root)]

    @app.get("/api/videos/{video_id}/review", response_model=ReviewPayload)
    def get_review(video_id: str) -> ReviewPayload:
        video_path = _video_by_id(root, video_id)
        try:
            return load_review_payload(video_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/videos/{video_id}/diff", response_model=DiffPayload)
    def get_diff(video_id: str) -> DiffPayload:
        """Dev-only: raw transcript with pipeline vs human-edit cuts overlaid."""
        video_path = _video_by_id(root, video_id)
        try:
            return build_diff_payload(video_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/videos/{video_id}/review", response_model=ReviewSaveResponse)
    def save_review(video_id: str, request: ReviewSaveRequest) -> ReviewSaveResponse:
        video_path = _video_by_id(root, video_id)
        try:
            return save_reviewed_edl(video_path, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/videos/{video_id}/render", response_model=RenderResponse)
    def render_review(video_id: str) -> RenderResponse:
        video_path = _video_by_id(root, video_id)
        review_path = review_edl_path_for(video_path)
        if not review_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Reviewed EDL not found: {review_path.name}",
            )

        denoised = _denoised_audio_path(video_path)
        if denoised is None:
            raise HTTPException(
                status_code=404,
                detail=f"Denoised audio not found for {video_path.name}",
            )

        edl = EditDecisionList.model_validate_json(review_path.read_text(encoding="utf-8"))
        cfg = RenderConfig(output_suffix="_reviewed")
        output = render_video(video_path, edl, denoised, cfg)
        return RenderResponse(output_path=str(output), output_name=output.name)

    @app.get("/media/{video_id}")
    def media(video_id: str) -> FileResponse:
        video_path = _video_by_id(root, video_id)
        return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)

    dist = Path(frontend_dist).expanduser().resolve() if frontend_dist else _default_frontend_dist()
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


def _default_frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _discover_videos(root: Path) -> list[Path]:
    videos = []
    for path in sorted(root.rglob("*.mp4")):
        if path.name.endswith("_edited.mp4") or path.name.endswith("_reviewed.mp4"):
            continue
        if path.with_suffix(".edl.json").exists() and path.with_suffix(".transcript.json").exists():
            videos.append(path)
    return videos


def _video_by_id(root: Path, video_id: str) -> Path:
    if "/" in video_id or "\\" in video_id or ".." in video_id:
        raise HTTPException(status_code=400, detail="Invalid video id")

    matches = [path for path in _discover_videos(root) if path.stem == video_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Video not found: {video_id}")
    return matches[0]


def _summary_for(video_path: Path) -> ReviewVideoSummary:
    try:
        payload = load_review_payload(video_path)
        duration = payload.video.duration
    except FileNotFoundError:
        duration = 0.0

    return ReviewVideoSummary(
        id=video_path.stem,
        source_name=video_path.name,
        source_path=str(video_path),
        has_review=review_edl_path_for(video_path).exists(),
        duration=duration,
    )


def _denoised_audio_path(video_path: Path) -> Path | None:
    filename = f"{video_path.stem}_denoised.wav"
    candidates = [
        Path.cwd() / ".ai_video_editor_tmp" / filename,
        video_path.parent / ".ai_video_editor_tmp" / filename,
        video_path.parent.parent / ".ai_video_editor_tmp" / filename,
        video_path.with_name(filename),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
