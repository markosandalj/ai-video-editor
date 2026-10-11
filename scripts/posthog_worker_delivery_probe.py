"""One tiny real LLM call through the worker factory and local Django callback.

Requires an existing terminal local test job and its exact terminal snapshot.
Replays that snapshot with a real, labelled test receipt; never submits media.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import tempfile
from uuid import UUID

from dotenv import dotenv_values

from ai_video_editor.llm import build_chat_model, default_section_editor_model_config
from ai_video_editor.observability import load_runtime_env
from ai_video_editor.worker.callbacks import HttpCallbackClient
from ai_video_editor.worker.consumption import ConsumptionV1, consumption_scope
from ai_video_editor.worker.contracts import worker_snapshot_adapter
from ai_video_editor.worker.store import JobStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True, type=UUID)
    parser.add_argument("--terminal-snapshot", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("--run explicitly enables one paid provider call and local delivery")
    snapshot = worker_snapshot_adapter.validate_json(args.terminal_snapshot.read_text())
    if snapshot.job_id != args.job_id or snapshot.status not in {"completed", "failed"}:
        parser.error("--terminal-snapshot must be the selected job's existing terminal result")
    root = Path(__file__).resolve().parents[1]
    load_runtime_env(root / ".env")
    config = dotenv_values(root / ".env.worker.local")
    origin = config["GRADIVO_VIDEO_CALLBACK_BASE_URL"]
    if origin != "http://main.gradivo.localhost":
        raise RuntimeError("Only the verified local Gradivo callback is supported")
    receipts = []
    with tempfile.TemporaryDirectory(prefix="posthog-worker-delivery-") as directory:
        store = JobStore(Path(directory) / "state.db")
        store.initialize()
        model_config = default_section_editor_model_config()
        model_config.provider_kwargs.update(max_tokens=128, max_retries=0, timeout=45)
        with consumption_scope(store, args.job_id):
            model = build_chat_model(model_config)
            model.invoke("Return only OK.")
        client = HttpCallbackClient(
            base_url=origin, token=config["GRADIVO_VIDEO_CALLBACK_TOKEN"]
        )
        with sqlite3.connect(Path(directory) / "state.db") as connection:
            receipts = [
                json.loads(row[0]) for row in connection.execute(
                    "SELECT payload_json FROM consumption_attempts ORDER BY attempt_id"
                )
            ]
        bundle = [ConsumptionV1.model_validate(row) for row in receipts]
        assert bundle and all(row.outcome != "started" for row in bundle)
        assert client.deliver(snapshot, consumption=bundle)
        final = receipts[-1]
        # Replay the exact same completed delivery, without another provider call.
        assert client.deliver(snapshot, consumption=bundle)
    result = {
        "job_id": str(args.job_id),
        "environment": "local",
        "is_test": True,
        "receipts": receipts,
        "duplicate_terminal_delivery": True,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "job_id": str(args.job_id),
                "outcome": final["outcome"],
                "usage": final["usage"],
                "cost_amount": final["cost_amount"],
                "attempt_id": final["attempt_id"],
                "receipt_file": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
