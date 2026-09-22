from __future__ import annotations

from uuid import UUID

from ai_video_editor.worker.callbacks import CallbackDispatcher
from ai_video_editor.worker.contracts import (
    AnalysisJobRequest,
    RenderJobRequest,
    WorkerError,
)
from ai_video_editor.worker.executor import (
    CompletedEvent,
    ExecutionEvent,
    FailedEvent,
    MediaExecutor,
    ProgressEvent,
)
from ai_video_editor.worker.store import AcceptedJob, JobStore


class WorkerService:
    def __init__(
        self,
        store: JobStore,
        executor: MediaExecutor,
        callback_dispatcher: CallbackDispatcher,
    ):
        self.store = store
        self._executor = executor
        self._callbacks = callback_dispatcher

    def startup(self, *, start_callback_dispatcher: bool = True) -> None:
        self.store.initialize()
        self.store.recover_interrupted()
        self._executor.startup()
        if start_callback_dispatcher:
            self._callbacks.start()
            self._callbacks.notify()

    def shutdown(self) -> None:
        try:
            self._executor.shutdown()
        finally:
            self._callbacks.stop()

    def dispatch_callbacks_once(self) -> bool:
        """Run one delivery attempt for deterministic control-plane integration tests."""

        return self._callbacks.dispatch_once()

    def submit(
        self,
        job_id: UUID,
        request: AnalysisJobRequest | RenderJobRequest,
    ) -> AcceptedJob:
        accepted = self.store.accept(job_id, request)
        if not accepted.created:
            return accepted

        try:
            self._executor.start(
                job_id,
                request,
                accepted.resolved_render_config,
                lambda event: self._handle_event(job_id, event),
            )
        except Exception:
            self.store.fail(
                job_id,
                WorkerError(
                    code="processing_failed",
                    stage="accepted",
                    message="Could not start media processing",
                ),
            )
        self._callbacks.notify()
        return accepted

    def _handle_event(self, job_id: UUID, event: ExecutionEvent) -> None:
        if isinstance(event, ProgressEvent):
            self.store.record_progress(job_id, event.progress)
        elif isinstance(event, CompletedEvent):
            self.store.complete(job_id, event.result)
        elif isinstance(event, FailedEvent):
            self.store.fail(job_id, event.error)
        self._callbacks.notify()
