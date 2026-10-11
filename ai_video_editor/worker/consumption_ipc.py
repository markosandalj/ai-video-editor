"""Send receipts over the existing execution event channel; only control persists them."""

from __future__ import annotations

import logging
import queue
import threading
import time
from uuid import UUID, uuid4

from ai_video_editor.worker.consumption import ConsumptionRecorder, ConsumptionV1

logger = logging.getLogger(__name__)


class SubprocessConsumptionRecorder:
    def __init__(self, events, acknowledgements, *, timeout_seconds: float = 1.0):
        self._events = events
        self._acknowledgements = acknowledgements
        self._timeout = timeout_seconds
        self._lock = threading.Lock()

    def record_consumption(self, payload: ConsumptionV1) -> None:
        # Serialize before Queue.put: its asynchronous feeder cannot report an
        # encoding failure to the provider wrapper's best-effort error handler.
        encoded = payload.model_dump(mode="json", by_alias=True)
        receipt_id = str(uuid4())
        deadline = time.monotonic() + self._timeout
        if not self._lock.acquire(timeout=self._timeout):
            raise TimeoutError("Consumption channel is busy")
        try:
            self._events.put({
                "type": "consumption",
                "receipt_id": receipt_id,
                "payload": encoded,
            })
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    acknowledged_id, saved = self._acknowledgements.get(timeout=remaining)
                except queue.Empty:
                    break
                # A previous receipt can be acknowledged after we timed out.
                if acknowledged_id != receipt_id:
                    continue
                if not saved:
                    raise RuntimeError("Control process could not save consumption")
                return
            raise TimeoutError("Control process did not acknowledge consumption")
        finally:
            self._lock.release()


def receive_consumption(
    event: dict,
    *,
    job_id: UUID,
    recorder: ConsumptionRecorder | None,
    acknowledgements,
) -> None:
    """Called in control. A bad receipt must never become a media failure."""
    saved = False
    try:
        payload = ConsumptionV1.model_validate(event.get("payload"))
        if payload.job_id != job_id:
            raise ValueError("Consumption job identity mismatch")
        if recorder is None:
            raise RuntimeError("Consumption recording is disabled")
        recorder.record_consumption(payload)
        saved = True  # Acknowledge only after the database transaction commits.
    except Exception:
        logger.exception("worker_consumption_write_failed job_id=%s", job_id)
    if acknowledgements is not None:
        try:
            acknowledgements.put_nowait((event.get("receipt_id"), saved))
        except (queue.Full, OSError, ValueError):
            # A timed-out or exited child must not stall the control process.
            logger.warning("worker_consumption_ack_unavailable job_id=%s", job_id)
