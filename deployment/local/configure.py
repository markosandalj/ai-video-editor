"""Prepare independent local worker/Gradivo configuration without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[2]
LITERAL_ENV_HEADER = "# Generated literal Compose environment\n"
CREDENTIAL_KEYS = (
    "GOOGLE_DRIVE_CLIENT_ID",
    "GOOGLE_DRIVE_CLIENT_SECRET",
    "GOOGLE_DRIVE_REFRESH_TOKEN",
    "VIDEO_PROCESSING_S3_ENDPOINT_URL",
    "VIDEO_PROCESSING_S3_BUCKET",
    "VIDEO_PROCESSING_S3_ACCESS_KEY_ID",
    "VIDEO_PROCESSING_S3_SECRET_ACCESS_KEY",
    "ELEVENLABS_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "PRODUCTION_CONSUMPTION_ENABLED",
)


def write_env(path: Path, values: dict[str, str]) -> None:
    # JSON quoting protects whitespace, hashes, quotes and backslashes;
    # Compose's $$ escape prevents a second interpolation of credentials.
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Local configuration requires single-line values")
    with open(
        path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)
    ) as stream:
        stream.write(LITERAL_ENV_HEADER)
        stream.writelines(
            f"{key}={json.dumps(value.replace('$', '$$'), ensure_ascii=False)}\n"
            for key, value in values.items()
        )
    path.chmod(0o600)


def read_env(path: Path) -> dict:
    values = dotenv_values(path, interpolate=False)
    if path.is_file() and path.read_text().startswith(LITERAL_ENV_HEADER):
        # python-dotenv understands quoting but not Compose's dollar escape.
        return {
            key: value.replace("$$", "$") if value is not None else None
            for key, value in values.items()
        }
    return values


def update_env(path: Path, values: dict[str, str]) -> None:
    """Update only worker settings in Gradivo's existing environment file."""
    if not path.is_file():
        raise ValueError("Prepare Gradivo's normal .env before configuring the worker")
    for key, value in values.items():
        set_key(path, key, value, quote_mode="never")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gradivo-dir", type=Path, required=True)
    parser.add_argument("--callback-url", required=True)
    args = parser.parse_args()
    parsed = urlparse(args.callback_url)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or not parsed.hostname.endswith(".gradivo.localhost")
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        parser.error("callback-url must be a local http://*.gradivo.localhost URL")
    gradivo = args.gradivo_dir.resolve()
    if not (gradivo / "docker-compose.worktree.yml").is_file():
        parser.error(
            "gradivo-dir must contain the Gradivo local worktree configuration"
        )
    if not (gradivo / ".env").is_file():
        parser.error("Prepare Gradivo's normal .env before configuring the worker")

    local_path = ROOT / ".env.worker.local"
    existing = read_env(local_path) if local_path.exists() else {}
    source = {
        **read_env(ROOT / ".env"),
        **read_env(ROOT / ".env.worker"),
    }
    source.update(existing)
    values = {key: source[key] for key in CREDENTIAL_KEYS if source.get(key)}
    stack_defaults = dotenv_values(ROOT / "deployment/mac/env/stack.env.example")
    local_data = ROOT / ".ai_video_editor_tmp/local-worker"
    defaults = dict(
        MAX_NUMBER_OF_JOBS="1",
        COMPOSE_PROJECT_NAME="ai-video-worker-local",
        AI_VIDEO_WORKER_IMAGE="ai-video-worker:local",
        AI_VIDEO_WORKER_STATE_DIR=str(local_data / "state"),
        AI_VIDEO_WORKER_SCRATCH_DIR=str(local_data / "scratch"),
        AI_VIDEO_WORKER_LOG_DIR=str(local_data / "logs"),
        AI_VIDEO_WORKER_BIND_ADDRESS="127.0.0.1",
        AI_VIDEO_WORKER_PORT="8000",
        # Compose resolves every service even when only worker is selected.
        # The local override disables cloudflared unless explicitly profiled in.
        CLOUDFLARED_IMAGE=stack_defaults["CLOUDFLARED_IMAGE"],
        AI_VIDEO_CLOUDFLARED_ENV_FILE=str(
            ROOT / "deployment/mac/env/cloudflared.env.example"
        ),
    )
    # Existing local overrides win over setup defaults, including settings this
    # helper does not know about (render quality, timeouts and future options).
    values = {
        **defaults,
        **values,
        **{k: v for k, v in existing.items() if v is not None},
    }
    # These values describe this invocation/checkout, rather than worker tuning.
    values.update(
        AI_VIDEO_EDITOR_API_TOKEN=existing.get("AI_VIDEO_EDITOR_API_TOKEN")
        or secrets.token_hex(32),
        GRADIVO_VIDEO_CALLBACK_TOKEN=existing.get("GRADIVO_VIDEO_CALLBACK_TOKEN")
        or secrets.token_hex(32),
        GRADIVO_VIDEO_CALLBACK_BASE_URL=args.callback_url.rstrip("/"),
        AI_VIDEO_WORKER_CALLBACK_HOST=parsed.hostname,
        COMPOSE_FILE=f"{ROOT / 'deployment/mac/compose.yaml'}:{ROOT / 'deployment/local/compose.yaml'}",
        AI_VIDEO_WORKER_ENV_FILE=str(local_path),
        # Local bind mounts belong to this host user, not the image's UID 10001.
        AI_VIDEO_WORKER_UID=str(os.getuid()),
        AI_VIDEO_WORKER_GID=str(os.getgid()),
    )
    for key in (
        "AI_VIDEO_WORKER_STATE_DIR",
        "AI_VIDEO_WORKER_SCRATCH_DIR",
        "AI_VIDEO_WORKER_LOG_DIR",
    ):
        Path(values[key]).mkdir(parents=True, exist_ok=True)
    write_env(local_path, values)
    gradivo_values = {
        "VIDEO_PROCESSING_BACKEND": "http",
        "VIDEO_PROCESSING_HTTP_BASE_URL": f"http://host.docker.internal:{values['AI_VIDEO_WORKER_PORT']}",
        "AI_VIDEO_EDITOR_API_TOKEN": values["AI_VIDEO_EDITOR_API_TOKEN"],
        "GRADIVO_VIDEO_CALLBACK_TOKEN": values["GRADIVO_VIDEO_CALLBACK_TOKEN"],
    }
    # Gradivo must sign Review Proxy URLs for the same bucket used by the worker.
    for key in ("VIDEO_PROCESSING_S3_ENDPOINT_URL", "VIDEO_PROCESSING_S3_BUCKET"):
        if key in values:
            gradivo_values[key] = values[key]
    update_env(gradivo / ".env", gradivo_values)
    missing = [key for key in CREDENTIAL_KEYS if not values.get(key)]
    print(
        f"Prepared {local_path}; updated worker settings in {gradivo / '.env'} (mode 0600)"
    )
    print(
        f"Worker: http://localhost:{values['AI_VIDEO_WORKER_PORT']}; Gradivo callback: {args.callback_url}"
    )
    print("Credential fields absent: " + (", ".join(missing) or "none"))


if __name__ == "__main__":
    main()
