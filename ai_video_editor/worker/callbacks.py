from __future__ import annotations

import json
import logging
import threading
import time
from typing import Protocol
from urllib.request import Request, urlopen

from ai_video_editor.worker.contracts import WorkerSnapshot
from ai_video_editor.worker.consumption import ConsumptionV1
from ai_video_editor.worker.store import JobStore

logger = logging.getLogger(__name__)


class CallbackClient(Protocol):
    def deliver(
        self, snapshot: WorkerSnapshot, *, consumption: list[ConsumptionV1] | None = None
    ) -> bool: ...


class HttpCallbackClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def deliver(
        self, snapshot: WorkerSnapshot, *, consumption: list[ConsumptionV1] | None = None
    ) -> bool:
        payload = snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
        consumption_ready = True
        if consumption is not None:
            try:
                receipt_payload = [row.model_dump(mode="json", by_alias=True) for row in consumption]
                json.dumps(receipt_payload, allow_nan=False)
                payload["consumption"] = receipt_payload
            except Exception as exc:
                consumption_ready = False
                logger.warning(
                    "consumption_encoding_failed job_id=%s error_type=%s",
                    snapshot.job_id, type(exc).__name__,
                )
        body = json.dumps(
            payload,
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
            acknowledgement = json.load(response)
            if acknowledgement.get("acknowledged") is not True:
                raise OSError("Gradivo did not acknowledge the job result")
            return consumption_ready and (
                consumption is None or acknowledgement.get("consumption_acknowledged") is True
            )


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
        self._state_lock = threading.Lock()
        self._close_store_on_exit = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._close_store_on_exit = False
            self._thread = threading.Thread(
                target=self._run,
                name="video-callback-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 15.0, close_store: bool = False) -> None:
        with self._state_lock:
            self._stop.set()
            self._wake.set()
            if close_store:
                self._close_store_on_exit = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        should_close_now = False
        with self._state_lock:
            if thread is None or not thread.is_alive():
                if self._thread is thread:
                    self._thread = None
                if self._close_store_on_exit:
                    self._close_store_on_exit = False
                    should_close_now = True
        if should_close_now:
            self._store.close()

    def notify(self) -> None:
        self._wake.set()

    def dispatch_once(self) -> bool:
        entry = self._store.next_outbox()
        if entry is None:
            return False
        consumption = None
        consumption_ready = True
        if entry.terminal:
            try:
                consumption = self._store.consumption_for_terminal_job(entry.job_id)
            except Exception as exc:
                # Always send the video result, even if its optional evidence cannot be read.
                consumption_ready = False
                logger.warning(
                    "consumption_bundle_failed job_id=%s error_type=%s",
                    entry.job_id, type(exc).__name__,
                )
        try:
            if consumption is None:
                acknowledged = self._client.deliver(entry.snapshot)
            else:
                acknowledged = self._client.deliver(entry.snapshot, consumption=consumption)
            if entry.terminal and (not consumption_ready or acknowledged is not True):
                # The video is already accepted; replay is idempotent and only recovers consumption.
                raise OSError("Consumption remains pending after result delivery")
        except Exception as exc:  # noqa: BLE001 - Delivery must survive arbitrary client errors.
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
        try:
            while not self._stop.is_set():
                # Clear before checking the store so a notify() or stop() arriving
                # during dispatch/query stays visible to the wait below.
                self._wake.clear()
                if self._stop.is_set():
                    break
                try:
                    if self.dispatch_once():
                        continue
                    next_available_at = self._store.next_outbox_available_at()
                except Exception as exc:
                    logger.warning("callback_dispatch_failed error_type=%s", type(exc).__name__)
                    self._wake.wait(self._idle_wait_seconds)
                    continue

                if next_available_at is None:
                    self._wake.wait()
                else:
                    delay = next_available_at - time.time()
                    if delay > 0:
                        self._wake.wait(delay)
        finally:
            should_close = False
            with self._state_lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                if self._close_store_on_exit:
                    self._close_store_on_exit = False
                    should_close = True
            if should_close:
                self._store.close()
