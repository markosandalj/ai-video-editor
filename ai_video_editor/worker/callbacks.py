from __future__ import annotations

import json
import logging
import threading
from typing import Protocol
from urllib.request import Request, urlopen

from ai_video_editor.worker.contracts import WorkerSnapshot
from ai_video_editor.worker.store import JobStore

logger = logging.getLogger(__name__)


class CallbackClient(Protocol):
    def deliver(self, snapshot: WorkerSnapshot) -> None: ...


class HttpCallbackClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def deliver(self, snapshot: WorkerSnapshot) -> None:
        body = json.dumps(
            snapshot.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        url = (
            f"{self._base_url}/wt/internal/api/video-processing/jobs/"
            f"{snapshot.job_id}/status"
        )
        request = Request(
            url,
            data=body,
            method="PUT",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "ai-video-worker/1.0",
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            if not 200 <= response.status < 300:
                raise OSError(f"callback returned HTTP {response.status}")


class CallbackDispatcher:
    def __init__(
        self,
        store: JobStore,
        client: CallbackClient,
        *,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 300.0,
        idle_wait_seconds: float = 0.25,
    ):
        self._store = store
        self._client = client
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._idle_wait_seconds = idle_wait_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="video-callback-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def notify(self) -> None:
        self._wake.set()

    def dispatch_once(self) -> bool:
        entry = self._store.next_outbox()
        if entry is None:
            return False
        try:
            self._client.deliver(entry.snapshot)
        except Exception as exc:
            # Exception messages/HTTP bodies may contain credentials or signed URLs.
            logger.warning(
                "callback_failed job_id=%s revision=%s terminal=%s attempt=%s error_type=%s",
                entry.snapshot.job_id,
                entry.snapshot.revision,
                entry.terminal,
                entry.attempts + 1,
                type(exc).__name__,
            )
            if entry.terminal:
                delay = min(
                    self._retry_base_seconds * (2 ** min(entry.attempts, 30)),
                    self._retry_max_seconds,
                )
                self._store.reschedule_outbox(entry.id, delay_seconds=delay)
            else:
                # Progress is explicitly best effort; a newer revision supersedes it.
                self._store.mark_outbox_delivered(entry.id)
        else:
            self._store.mark_outbox_delivered(entry.id)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.dispatch_once():
                self._wake.wait(self._idle_wait_seconds)
                self._wake.clear()
