"""Bounded internal failure details, kept separate from the public job contract."""

from __future__ import annotations

import os
import re
import subprocess
import traceback


_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|ACCESS_KEY", re.I)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
_BEARER = re.compile(r"\bBearer\s+[^\s\"',;]+", re.I)


def _redact(value: str, *, limit: int = 4000) -> str:
    # Redact before truncation so a partially truncated credential cannot escape.
    secrets = sorted(
        {
            value
            for key, value in os.environ.items()
            if value and _SECRET_NAME.search(key)
        },
        key=len,
        reverse=True,
    )
    for secret in secrets:
        value = value.replace(secret, "[redacted]")
    value = _URL.sub("[url omitted]", value)
    value = _BEARER.sub("Bearer [redacted]", value)
    return value[-limit:]


def exception_diagnostics(error: BaseException | None) -> list[dict[str, object]]:
    """Retain cause types, stack locations and FFmpeg stderr, without locals/bodies."""
    chain: list[dict[str, object]] = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen and len(chain) < 8:
        seen.add(id(error))
        detail: dict[str, object] = {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "frames": [
                {
                    "file": _redact(frame.f_code.co_filename),
                    "line": line,
                    "function": frame.f_code.co_name,
                }
                for frame, line in list(traceback.walk_tb(error.__traceback__))[-20:]
            ],
        }
        # SDK exception messages may embed response bodies or request credentials.
        # Keep their type, stack and HTTP status instead of serializing the body.
        if isinstance(error, subprocess.CalledProcessError):
            detail["returncode"] = error.returncode
        elif (
            type(error).__module__ == "builtins"
            or type(error).__module__.startswith("ai_video_editor.")
        ):
            detail["message"] = _redact(str(error))
        status = getattr(getattr(error, "resp", None), "status", None)
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            metadata = response.get("ResponseMetadata")
            if isinstance(metadata, dict):
                status = metadata.get("HTTPStatusCode")
        if type(status) is int:
            detail["http_status"] = status
        stderr = getattr(error, "stderr", None)
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if isinstance(stderr, str) and stderr:
            detail["stderr"] = _redact(stderr)
        chain.append(detail)
        error = error.__cause__ or (
            None if error.__suppress_context__ else error.__context__
        )
    return chain
