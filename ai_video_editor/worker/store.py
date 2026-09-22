from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ai_video_editor.worker.contracts import (
    AnalysisJobRequest,
    AnalysisResultV1,
    CompletedSnapshot,
    FailedSnapshot,
    ProcessingSnapshot,
    Progress,
    RenderJobRequest,
    RenderResultV1,
    ResolvedRenderConfigV1,
    WorkerError,
    WorkerSnapshot,
    job_request_adapter,
    semantic_payload,
    worker_snapshot_adapter,
)


class JobPayloadMismatchError(Exception):
    pass


class WorkerAtCapacityError(Exception):
    pass


@dataclass(frozen=True)
class AcceptedJob:
    created: bool
    request: AnalysisJobRequest | RenderJobRequest
    snapshot: WorkerSnapshot
    resolved_render_config: ResolvedRenderConfigV1 | None


@dataclass(frozen=True)
class OutboxEntry:
    id: int
    job_id: UUID
    revision: int
    snapshot: WorkerSnapshot
    terminal: bool
    attempts: int


class JobStore:
    """The single SQLite ownership boundary for jobs, slots, and callbacks."""

    def __init__(
        self,
        path: Path | str,
        *,
        capacity: int = 1,
        resolved_render_config: ResolvedRenderConfigV1 | None = None,
    ):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("worker capacity must be a positive integer")
        self._path = Path(path)
        self._capacity = capacity
        self._resolved_render_config = resolved_render_config or _default_render_config()
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL CHECK (operation IN ('analysis', 'render')),
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    resolved_render_config_json TEXT,
                    snapshot_json TEXT NOT NULL,
                    slot_reserved INTEGER NOT NULL CHECK (slot_reserved IN (0, 1)),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS callback_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    delivered_at REAL,
                    UNIQUE(job_id, revision)
                );

                CREATE INDEX IF NOT EXISTS callback_outbox_pending
                ON callback_outbox(delivered_at, available_at, id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "resolved_render_config_json" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN resolved_render_config_json TEXT"
                )
            connection.commit()

    def accept(
        self,
        job_id: UUID,
        request: AnalysisJobRequest | RenderJobRequest,
    ) -> AcceptedJob:
        payload_json, payload_hash = semantic_payload(request)
        initial = ProcessingSnapshot(
            job_id=job_id,
            operation=request.operation,
            revision=1,
            status="processing",
            progress=Progress(percent=0, stage="accepted"),
        )
        initial_json = self._snapshot_json(initial)
        now = time.time()
        with self._transaction() as connection:
            existing = connection.execute(
                """SELECT payload_hash, payload_json, resolved_render_config_json,
                          snapshot_json
                   FROM jobs WHERE job_id = ?""",
                (str(job_id),),
            ).fetchone()
            if existing is not None:
                if (
                    existing["payload_hash"] != payload_hash
                    or existing["payload_json"] != payload_json
                ):
                    raise JobPayloadMismatchError
                stored_request = job_request_adapter.validate_json(existing["payload_json"])
                return AcceptedJob(
                    created=False,
                    request=stored_request,
                    snapshot=worker_snapshot_adapter.validate_json(existing["snapshot_json"]),
                    resolved_render_config=_parse_resolved_config(
                        existing["resolved_render_config_json"]
                    ),
                )

            occupied = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE slot_reserved = 1"
            ).fetchone()[0]
            if occupied >= self._capacity:
                raise WorkerAtCapacityError

            resolved_config = (
                self._resolved_render_config.model_dump_json(
                    by_alias=True,
                    exclude_none=True,
                )
                if request.operation == "render"
                else None
            )

            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, operation, payload_json, payload_hash,
                    resolved_render_config_json, snapshot_json, slot_reserved,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    str(job_id),
                    request.operation,
                    payload_json,
                    payload_hash,
                    resolved_config,
                    initial_json,
                    now,
                    now,
                ),
            )
            self._insert_outbox(connection, initial, terminal=False, now=now)
        return AcceptedJob(
            created=True,
            request=request,
            snapshot=initial,
            resolved_render_config=(
                self._resolved_render_config if request.operation == "render" else None
            ),
        )

    def get_snapshot(self, job_id: UUID) -> WorkerSnapshot | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
        if row is None:
            return None
        return worker_snapshot_adapter.validate_json(row["snapshot_json"])

    def get_resolved_render_config(
        self, job_id: UUID
    ) -> ResolvedRenderConfigV1 | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT resolved_render_config_json FROM jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
        return None if row is None else _parse_resolved_config(
            row["resolved_render_config_json"]
        )

    def record_progress(self, job_id: UUID, progress: Progress) -> ProcessingSnapshot | None:
        with self._transaction() as connection:
            row = self._job_row(connection, job_id)
            snapshot = worker_snapshot_adapter.validate_json(row["snapshot_json"])
            if not isinstance(snapshot, ProcessingSnapshot):
                return None
            if progress.percent < snapshot.progress.percent:
                raise ValueError("progress percent cannot decrease")
            updated = ProcessingSnapshot(
                job_id=job_id,
                operation=snapshot.operation,
                revision=snapshot.revision + 1,
                status="processing",
                progress=progress,
            )
            self._write_snapshot(connection, updated, reserve_slot=True)
            self._insert_outbox(connection, updated, terminal=False)
            return updated

    def complete(
        self,
        job_id: UUID,
        result: AnalysisResultV1 | RenderResultV1,
    ) -> CompletedSnapshot | None:
        with self._transaction() as connection:
            row = self._job_row(connection, job_id)
            snapshot = worker_snapshot_adapter.validate_json(row["snapshot_json"])
            if not isinstance(snapshot, ProcessingSnapshot):
                return None
            completed = CompletedSnapshot(
                job_id=job_id,
                operation=snapshot.operation,
                revision=snapshot.revision + 1,
                status="completed",
                progress=Progress(percent=100, stage="completed"),
                result=result,
            )
            self._write_snapshot(connection, completed, reserve_slot=False)
            self._insert_outbox(connection, completed, terminal=True)
            return completed

    def fail(self, job_id: UUID, error: WorkerError) -> FailedSnapshot | None:
        with self._transaction() as connection:
            row = self._job_row(connection, job_id)
            snapshot = worker_snapshot_adapter.validate_json(row["snapshot_json"])
            if not isinstance(snapshot, ProcessingSnapshot):
                return None
            failed = FailedSnapshot(
                job_id=job_id,
                operation=snapshot.operation,
                revision=snapshot.revision + 1,
                status="failed",
                progress=Progress(
                    percent=snapshot.progress.percent,
                    stage=error.stage,
                ),
                error=error,
            )
            self._write_snapshot(connection, failed, reserve_slot=False)
            self._insert_outbox(connection, failed, terminal=True)
            return failed

    def recover_interrupted(self) -> list[FailedSnapshot]:
        recovered: list[FailedSnapshot] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT job_id, snapshot_json FROM jobs WHERE slot_reserved = 1"
            ).fetchall()
            for row in rows:
                snapshot = worker_snapshot_adapter.validate_json(row["snapshot_json"])
                if not isinstance(snapshot, ProcessingSnapshot):
                    connection.execute(
                        "UPDATE jobs SET slot_reserved = 0 WHERE job_id = ?",
                        (row["job_id"],),
                    )
                    continue
                failed = FailedSnapshot(
                    job_id=snapshot.job_id,
                    operation=snapshot.operation,
                    revision=snapshot.revision + 1,
                    status="failed",
                    progress=Progress(
                        percent=snapshot.progress.percent,
                        stage=snapshot.progress.stage,
                    ),
                    error=WorkerError(
                        code="worker_interrupted",
                        stage=snapshot.progress.stage,
                        message="Worker stopped while the job was processing",
                    ),
                )
                self._write_snapshot(connection, failed, reserve_slot=False)
                self._insert_outbox(connection, failed, terminal=True)
                recovered.append(failed)
        return recovered

    def next_outbox(self, *, now: float | None = None) -> OutboxEntry | None:
        available = time.time() if now is None else now
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, job_id, revision, snapshot_json, terminal, attempts
                FROM callback_outbox
                WHERE delivered_at IS NULL AND available_at <= ?
                ORDER BY id
                LIMIT 1
                """,
                (available,),
            ).fetchone()
        if row is None:
            return None
        return OutboxEntry(
            id=row["id"],
            job_id=UUID(row["job_id"]),
            revision=row["revision"],
            snapshot=worker_snapshot_adapter.validate_json(row["snapshot_json"]),
            terminal=bool(row["terminal"]),
            attempts=row["attempts"],
        )

    def mark_outbox_delivered(self, entry_id: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE callback_outbox SET delivered_at = ? WHERE id = ?",
                (time.time(), entry_id),
            )

    def reschedule_outbox(self, entry_id: int, *, delay_seconds: float) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE callback_outbox
                SET attempts = attempts + 1, available_at = ?
                WHERE id = ? AND delivered_at IS NULL
                """,
                (time.time() + delay_seconds, entry_id),
            )

    def pending_outbox_count(self) -> int:
        with self._lock, closing(self._connect()) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM callback_outbox WHERE delivered_at IS NULL"
            ).fetchone()[0]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(self):
        # Each context unwinds even when opening the connection or BEGIN fails.
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _job_row(connection: sqlite3.Connection, job_id: UUID) -> sqlite3.Row:
        row = connection.execute(
            "SELECT snapshot_json FROM jobs WHERE job_id = ?", (str(job_id),)
        ).fetchone()
        if row is None:
            raise KeyError(str(job_id))
        return row

    def _write_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: WorkerSnapshot,
        *,
        reserve_slot: bool,
    ) -> None:
        connection.execute(
            """
            UPDATE jobs
            SET snapshot_json = ?, slot_reserved = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                self._snapshot_json(snapshot),
                int(reserve_slot),
                time.time(),
                str(snapshot.job_id),
            ),
        )

    def _insert_outbox(
        self,
        connection: sqlite3.Connection,
        snapshot: WorkerSnapshot,
        *,
        terminal: bool,
        now: float | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO callback_outbox (
                job_id, revision, snapshot_json, terminal, available_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(snapshot.job_id),
                snapshot.revision,
                self._snapshot_json(snapshot),
                int(terminal),
                time.time() if now is None else now,
            ),
        )

    @staticmethod
    def _snapshot_json(snapshot: WorkerSnapshot) -> str:
        return json.dumps(
            snapshot.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


def _default_render_config() -> ResolvedRenderConfigV1:
    return ResolvedRenderConfigV1(
        schema="resolved_render_config.v1",
        render_profile="student_video.v1",
        codec="libx264",
        crf=28,
        preset="ultrafast",
        crossfade_ms=30,
        output_suffix="-final",
        audio_codec="aac",
        audio_bitrate="192k",
        movflags="+faststart",
    )


def _parse_resolved_config(value: str | None) -> ResolvedRenderConfigV1 | None:
    if value is None:
        return None
    return ResolvedRenderConfigV1.model_validate_json(value)
