from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_video_editor.worker.callbacks import (
    CallbackClient,
    CallbackDispatcher,
    HttpCallbackClient,
)
from ai_video_editor.worker.contracts import JobRequest, WorkerSnapshot
from ai_video_editor.worker.executor import (
    MediaExecutor,
    SubprocessMediaExecutor,
)
from ai_video_editor.worker.analysis_runner import run_configured_media_job
from ai_video_editor.worker.service import WorkerService
from ai_video_editor.worker.settings import WorkerSettings
from ai_video_editor.worker.store import (
    JobPayloadMismatchError,
    JobStore,
    WorkerAtCapacityError,
)


def create_worker_app(
    settings: WorkerSettings,
    *,
    executor: MediaExecutor | None = None,
    callback_client: CallbackClient | None = None,
    start_callback_dispatcher: bool = True,
) -> FastAPI:
    store = JobStore(
        settings.state_db_path,
        capacity=settings.max_number_of_jobs,
        resolved_render_config=settings.resolve_render_config(),
    )
    media_executor = executor or SubprocessMediaExecutor(
        run_configured_media_job,
        analysis_timeout_seconds=settings.analysis_timeout_seconds,
        render_timeout_seconds=settings.render_timeout_seconds,
    )
    callback_dispatcher = CallbackDispatcher(
        store,
        callback_client
        or HttpCallbackClient(
            base_url=settings.callback_base_url,
            token=settings.callback_token,
        ),
        retry_base_seconds=settings.callback_retry_base_seconds,
        retry_max_seconds=settings.callback_retry_max_seconds,
    )
    service = WorkerService(store, media_executor, callback_dispatcher)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        service.startup(start_callback_dispatcher=start_callback_dispatcher)
        try:
            yield
        finally:
            service.shutdown()

    app = FastAPI(
        title="AI Video Editor Worker API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.worker_service = service
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        valid = (
            credentials is not None
            and credentials.scheme.lower() == "bearer"
            and secrets.compare_digest(credentials.credentials, settings.api_token)
        )
        if not valid:
            raise WorkerHttpError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.exception_handler(WorkerHttpError)
    async def worker_error_handler(
        request: Request, exc: WorkerHttpError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": {"code": "invalid_request"}},
        )

    @app.put(
        "/v1/jobs/{job_id}",
        response_model=WorkerSnapshot,
        responses={200: {}, 201: {}, 400: {}, 401: {}, 409: {}, 429: {}},
    )
    def submit_job(
        job_id: UUID,
        request: JobRequest,
        _auth: None = Depends(authenticate),
    ):
        try:
            accepted = service.submit(job_id, request)
        except JobPayloadMismatchError as exc:
            raise WorkerHttpError(
                status_code=status.HTTP_409_CONFLICT,
                code="job_payload_mismatch",
            ) from exc
        except WorkerAtCapacityError as exc:
            raise WorkerHttpError(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="worker_at_capacity",
                retryable=True,
                headers={"Retry-After": "30"},
            ) from exc
        return JSONResponse(
            status_code=(
                status.HTTP_201_CREATED if accepted.created else status.HTTP_200_OK
            ),
            content=accepted.snapshot.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
        )

    @app.get("/healthz", include_in_schema=False)
    def healthcheck(_auth: None = Depends(authenticate)) -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/v1/jobs/{job_id}",
        response_model=WorkerSnapshot,
        responses={400: {}, 401: {}, 404: {}},
    )
    def get_job(
        job_id: UUID,
        _auth: None = Depends(authenticate),
    ) -> WorkerSnapshot:
        snapshot = store.get_snapshot(job_id)
        if snapshot is None:
            raise WorkerHttpError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="job_not_found",
            )
        return snapshot

    return app


class WorkerHttpError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.error: dict[str, object] = {"code": code}
        if retryable is not None:
            self.error["retryable"] = retryable
        self.headers = headers


def main() -> None:
    settings = WorkerSettings()
    settings.scratch_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        create_worker_app(settings),
        host="0.0.0.0",
        port=8000,
        log_config=_uvicorn_log_config(settings.log_dir),
    )


def _uvicorn_log_config(log_dir: Path) -> dict[str, object]:
    """Keep container stdout while retaining bounded worker-owned host logs."""

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(asctime)s %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "access_console": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": str(log_dir / "worker.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "ai_video_editor.worker": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["access_console", "file"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
