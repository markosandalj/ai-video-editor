"""Durable provider evidence collected during execution and sent with the terminal callback."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import httpx
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class ConsumptionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: Literal["consumption.v1"] = Field(
        default="consumption.v1", alias="schema"
    )
    job_id: UUID
    attempt_id: UUID
    revision: int = Field(ge=1)
    operation: str = Field(min_length=1, max_length=100)
    provider: str = Field(max_length=50)
    model: str = Field(default="", max_length=160)
    provider_request_id: str = Field(default="", max_length=200)
    started_at: datetime
    outcome: Literal["started", "succeeded", "failed", "interrupted"]
    usage: dict[str, Any] = Field(default_factory=dict)
    cost_amount: str | None = None
    currency: str = ""
    cost_basis: Literal["charged", "estimated", "unavailable"] = "unavailable"
    coverage_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_timing(cls, values):
        # Existing durable outbox entries must still deliver their usage/cost.
        if isinstance(values, dict):
            values = {
                key: value
                for key, value in values.items()
                if key not in {"duration_ms", "timing_scope"}
            }
        return values


class ConsumptionRecorder(Protocol):
    def record_consumption(self, payload: ConsumptionV1) -> None: ...


@dataclass
class ConsumptionContext:
    store: ConsumptionRecorder
    job_id: UUID
    issues: set[str] = field(default_factory=set)


_context: ContextVar[ConsumptionContext | None] = ContextVar(
    "worker_consumption", default=None
)


def current_context():
    return _context.get()


def _persist(attempt: ConsumptionV1):
    context = current_context()
    if context is None:
        return
    try:
        context.store.record_consumption(attempt)
    except Exception:
        context.issues.add("worker_ledger_write_failed")
        logger.exception(
            "worker_consumption_write_failed attempt_id=%s", attempt.attempt_id
        )


def start_attempt(operation, provider, model="", *, usage=None):
    context = current_context()
    if context is None:
        return None
    attempt = ConsumptionV1(
        job_id=context.job_id,
        attempt_id=uuid4(),
        revision=1,
        operation=operation,
        provider=provider,
        model=model,
        started_at=datetime.now(UTC),
        outcome="started",
        usage=usage or {},
    )
    _persist(attempt)
    return attempt


def finish_attempt(
    started, *, outcome, payload=None, request_id="", usage=None, issues=()
):
    if started is None:
        return
    attempt = started
    payload = payload if isinstance(payload, dict) else {}
    raw_usage = (
        usage
        if usage is not None
        else payload.get("usage") or payload.get("usageMetadata") or {}
    )
    raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
    cost = raw_usage.get("cost") if attempt.provider == "openrouter" else None
    issues = set(issues)
    if cost is not None:
        try:
            amount = Decimal(str(cost))
            if not amount.is_finite() or amount < 0 or amount >= Decimal(1000000000000):
                raise InvalidOperation
            cost = str(amount.quantize(Decimal("0.000000000001")))
        except (ValueError, TypeError, InvalidOperation):
            cost = None
            issues.add("invalid_provider_cost")
    context = current_context()
    updated = attempt.model_copy(
        update={
            "revision": 2,
            "outcome": outcome,
            "usage": raw_usage,
            "model": str(
                payload.get("modelVersion") or payload.get("model") or attempt.model
            ),
            "provider_request_id": str(
                payload.get("responseId") or payload.get("id") or request_id or ""
            ),
            "cost_amount": cost,
            "currency": "USD" if cost is not None else "",
            "cost_basis": "charged" if cost is not None else "unavailable",
            "coverage_issues": sorted(
                set(issues) | (context.issues if context else set())
            ),
        }
    )
    _persist(updated)


@contextmanager
def consumption_scope(store: ConsumptionRecorder, job_id: UUID):
    token = _context.set(ConsumptionContext(store, job_id))
    try:
        # Production usage goes through the durable callback to PostHog.
        # Evaluation calls outside this scope keep their LangSmith setup.
        with tracing_context(enabled=False):
            yield
    finally:
        _context.reset(token)


class ConsumptionTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """One record per actual HTTP attempt, including SDK retries and timeouts.

    Reads only usage/identity fields into evidence; request prompts and response
    text are never persisted. Structured non-streaming provider calls use this.
    """

    def __init__(
        self,
        provider,
        model,
        operation,
        *,
        transport=None,
        async_transport=None,
        usage=None,
    ):
        self.provider, self.model, self.operation = provider, model, operation
        self.sync = transport or httpx.HTTPTransport()
        self.asynchronous = async_transport or httpx.AsyncHTTPTransport()
        self.usage = usage

    def _start(self, request):
        # Gemini file uploads/polling aren't inference attempts.
        if (
            self.provider == "google"
            and "generateContent" not in request.url.path
            and "streamGenerateContent" not in request.url.path
        ):
            return None
        return start_attempt(
            self.operation, self.provider, self.model, usage=self.usage
        )

    def _finish(self, started, response):
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        usage = self.usage if self.provider == "elevenlabs" else None
        finish_attempt(
            started,
            outcome="succeeded" if response.is_success else "failed",
            payload=payload,
            request_id=response.headers.get("x-request-id", ""),
            usage=usage,
            issues=("usage_unavailable",)
            if not usage
            and not (
                isinstance(payload, dict)
                and (payload.get("usage") or payload.get("usageMetadata"))
            )
            else (),
        )

    def handle_request(self, request):
        started = self._start(request)
        try:
            response = self.sync.handle_request(request)
            response.read()
        except Exception:
            finish_attempt(
                started, outcome="failed", issues=("provider_response_unavailable",)
            )
            raise
        self._finish(started, response)
        return response

    async def handle_async_request(self, request):
        started = self._start(request)
        try:
            response = await self.asynchronous.handle_async_request(request)
            await response.aread()
        except Exception:
            finish_attempt(
                started, outcome="failed", issues=("provider_response_unavailable",)
            )
            raise
        self._finish(started, response)
        return response

    def close(self):
        self.sync.close()

    async def aclose(self):
        await self.asynchronous.aclose()
