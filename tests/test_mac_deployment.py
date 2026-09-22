from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ai_video_editor.worker.app import _uvicorn_log_config, create_worker_app
from ai_video_editor.worker.settings import WorkerSettings
from deployment.mac.smoke_worker_status import (
    HttpResult,
    SmokeConfig,
    load_config,
    run_smoke,
)


ROOT = Path(__file__).parents[1]
DEPLOYMENT = ROOT / "deployment" / "mac"
JOB_ID = UUID("018f23bc-317a-7c8e-a614-17cf5ec82293")


def _env_keys(path: Path) -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    }


def test_worker_image_contains_locked_runtime_and_media_dependencies() -> None:
    dockerfile = (DEPLOYMENT / "Dockerfile").read_text()

    assert "UV_PROJECT_ENVIRONMENT=/opt/ai-video-worker" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "COPY --from=builder /opt/ai-video-worker /opt/ai-video-worker" in dockerfile
    assert "ffmpeg" in dockerfile
    assert "libsndfile1" in dockerfile
    assert 'ENTRYPOINT ["ai-video-worker"]' in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "COPY ." not in dockerfile


def test_compose_keeps_services_separate_and_host_state_explicit() -> None:
    compose = (DEPLOYMENT / "compose.yaml").read_text()

    assert "  worker:" in compose
    assert "  cloudflared:" in compose
    assert compose.count("restart: unless-stopped") == 2
    assert "/var/run/docker.sock" not in compose
    assert "ports:" not in compose
    assert "AI_VIDEO_WORKER_ENV_FILE" in compose
    assert "AI_VIDEO_CLOUDFLARED_ENV_FILE" in compose
    assert compose.count("type: bind") == 3
    assert "AI_VIDEO_WORKER_STATE_DIR" in compose
    assert "AI_VIDEO_WORKER_SCRATCH_DIR" in compose
    assert "AI_VIDEO_WORKER_LOG_DIR" in compose
    assert "http://worker:8000" not in compose


def test_worker_file_logging_is_bounded_and_uses_the_mounted_log_directory(
    tmp_path: Path,
) -> None:
    config = _uvicorn_log_config(tmp_path)
    file_handler = config["handlers"]["file"]

    assert file_handler["filename"] == str(tmp_path / "worker.log")
    assert file_handler["class"] == "logging.handlers.RotatingFileHandler"
    assert file_handler["maxBytes"] == 10 * 1024 * 1024
    assert file_handler["backupCount"] == 5


def test_container_health_endpoint_uses_application_authentication(tmp_path: Path) -> None:
    settings = WorkerSettings(
        AI_VIDEO_EDITOR_API_TOKEN="worker-api-token-000000000000",
        GRADIVO_VIDEO_CALLBACK_TOKEN="callback-token-0000000000000",
        GRADIVO_VIDEO_CALLBACK_BASE_URL="https://gradivo.example",
        VIDEO_PROCESSING_STATE_DB_PATH=tmp_path / "jobs.sqlite3",
    )
    app = create_worker_app(settings, start_callback_dispatcher=False)

    with TestClient(app) as client:
        missing = client.get("/healthz")
        authenticated = client.get(
            "/healthz",
            headers={"Authorization": "Bearer worker-api-token-000000000000"},
        )

    assert missing.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json() == {"status": "ok"}


def test_env_examples_are_separated_and_contain_no_real_secrets() -> None:
    worker_path = DEPLOYMENT / "env" / "worker.env.example"
    tunnel_path = DEPLOYMENT / "env" / "cloudflared.env.example"
    stack_path = DEPLOYMENT / "env" / "stack.env.example"
    worker_keys = _env_keys(worker_path)
    tunnel_keys = _env_keys(tunnel_path)
    stack_keys = _env_keys(stack_path)

    assert tunnel_keys == {"TUNNEL_TOKEN"}
    assert "TUNNEL_TOKEN" not in worker_keys
    assert "AI_VIDEO_EDITOR_API_TOKEN" in worker_keys
    assert "GRADIVO_VIDEO_CALLBACK_TOKEN" in worker_keys
    assert "VIDEO_PROCESSING_STATE_DB_PATH" not in worker_keys
    assert not worker_keys & stack_keys
    assert not tunnel_keys & stack_keys

    combined = "\n".join(
        path.read_text() for path in (worker_path, tunnel_path, stack_path)
    )
    assert "replace" in combined
    assert "latest" not in combined
    assert "-----BEGIN" not in combined


def test_smoke_cli_contract_requires_an_https_origin() -> None:
    environment = {
        "VIDEO_PROCESSING_HTTP_BASE_URL": "http://worker.example",
        "VIDEO_PROCESSING_SMOKE_JOB_ID": str(JOB_ID),
        "VIDEO_PROCESSING_CF_ACCESS_CLIENT_ID": "access-id",
        "VIDEO_PROCESSING_CF_ACCESS_CLIENT_SECRET": "access-secret",
        "AI_VIDEO_EDITOR_API_TOKEN": "application-token",
    }

    with pytest.raises(ValueError, match="HTTPS origin"):
        load_config(environment)


def test_smoke_proves_access_and_application_auth_without_media_or_internet() -> None:
    seen: list[dict[str, str]] = []

    def fake_https_get(url: str, headers: Mapping[str, str]) -> HttpResult:
        assert url == f"https://worker.example/v1/jobs/{JOB_ID}"
        seen.append(dict(headers))
        if (
            headers.get("CF-Access-Client-Id") != "access-id"
            or headers.get("CF-Access-Client-Secret") != "access-secret"
        ):
            return HttpResult(403, b'{"error":"access denied"}')
        if headers.get("Authorization") != "Bearer application-token":
            return HttpResult(401, b'{"error":{"code":"unauthorized"}}')
        return HttpResult(
            200,
            json.dumps(
                {
                    "job_id": str(JOB_ID),
                    "revision": 7,
                    "status": "completed",
                }
            ).encode(),
        )

    snapshot = run_smoke(
        SmokeConfig(
            base_url="https://worker.example",
            job_id=JOB_ID,
            access_client_id="access-id",
            access_client_secret="access-secret",
            api_token="application-token",
        ),
        get=fake_https_get,
    )

    assert snapshot["revision"] == 7
    assert len(seen) == 4
    assert "CF-Access-Client-Id" not in seen[0]
    assert seen[1]["CF-Access-Client-Id"].startswith("invalid.")
    assert seen[2]["Authorization"].startswith("Bearer invalid.")
    assert seen[3] == {
        "CF-Access-Client-Id": "access-id",
        "CF-Access-Client-Secret": "access-secret",
        "Authorization": "Bearer application-token",
    }
