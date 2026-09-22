#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


_ACCESS_REJECTION_STATUSES = {301, 302, 303, 307, 308, 401, 403}


class _DoNotFollowRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    job_id: UUID
    access_client_id: str
    access_client_secret: str
    api_token: str


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes

    def json(self) -> object:
        return json.loads(self.body)


def load_config(environment: Mapping[str, str] = os.environ) -> SmokeConfig:
    def required(name: str) -> str:
        value = environment.get(name, "").strip()
        if not value:
            raise ValueError(f"{name} is required")
        return value

    base_url = required("VIDEO_PROCESSING_HTTP_BASE_URL").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("VIDEO_PROCESSING_HTTP_BASE_URL must be an HTTPS origin")

    return SmokeConfig(
        base_url=base_url,
        job_id=UUID(required("VIDEO_PROCESSING_SMOKE_JOB_ID")),
        access_client_id=required("VIDEO_PROCESSING_CF_ACCESS_CLIENT_ID"),
        access_client_secret=required("VIDEO_PROCESSING_CF_ACCESS_CLIENT_SECRET"),
        api_token=required("AI_VIDEO_EDITOR_API_TOKEN"),
    )


def _get(url: str, headers: Mapping[str, str]) -> HttpResult:
    opener = build_opener(_DoNotFollowRedirects())
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(request, timeout=15) as response:
            return HttpResult(response.status, response.read())
    except HTTPError as exc:
        return HttpResult(exc.code, exc.read())
    except URLError as exc:
        raise RuntimeError(f"HTTPS origin is unreachable: {exc.reason}") from exc


def _access_headers(config: SmokeConfig) -> dict[str, str]:
    return {
        "CF-Access-Client-Id": config.access_client_id,
        "CF-Access-Client-Secret": config.access_client_secret,
    }


def run_smoke(
    config: SmokeConfig,
    *,
    get: Callable[[str, Mapping[str, str]], HttpResult] = _get,
) -> dict[str, object]:
    """Prove both authentication layers and return one existing durable status."""

    url = f"{config.base_url}/v1/jobs/{config.job_id}"
    application_header = {"Authorization": f"Bearer {config.api_token}"}

    missing_access = get(url, application_header)
    if missing_access.status not in _ACCESS_REJECTION_STATUSES:
        raise AssertionError(
            "request without Cloudflare Access credentials was not rejected "
            f"(HTTP {missing_access.status}); check for a public bypass"
        )

    invalid_access = get(
        url,
        {
            **application_header,
            "CF-Access-Client-Id": f"invalid.{config.access_client_id}",
            "CF-Access-Client-Secret": f"invalid.{config.access_client_secret}",
        },
    )
    if invalid_access.status not in _ACCESS_REJECTION_STATUSES:
        raise AssertionError(
            "request with invalid Cloudflare Access credentials was not rejected "
            f"(HTTP {invalid_access.status})"
        )

    wrong_bearer = get(
        url,
        {
            **_access_headers(config),
            "Authorization": f"Bearer invalid.{config.api_token}",
        },
    )
    if wrong_bearer.status != 401:
        raise AssertionError(
            "Cloudflare Access did not forward the request to the worker, or the "
            f"worker accepted a wrong application token (HTTP {wrong_bearer.status})"
        )
    try:
        wrong_bearer_payload = wrong_bearer.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AssertionError("worker 401 response was not JSON") from exc
    if wrong_bearer_payload != {"error": {"code": "unauthorized"}}:
        raise AssertionError("worker returned an unexpected wrong-token response")

    authenticated = get(
        url,
        {**_access_headers(config), **application_header},
    )
    if authenticated.status != 200:
        raise AssertionError(
            f"authenticated worker status failed with HTTP {authenticated.status}"
        )
    try:
        snapshot = authenticated.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AssertionError("authenticated worker status was not JSON") from exc
    if not isinstance(snapshot, dict):
        raise AssertionError("authenticated worker status was not a JSON object")
    if snapshot.get("job_id") != str(config.job_id):
        raise AssertionError("worker returned a different job identity")
    if snapshot.get("status") not in {"processing", "completed", "failed"}:
        raise AssertionError("worker returned an unknown public status")
    return snapshot


def main() -> None:
    try:
        snapshot = run_smoke(load_config())
    except (AssertionError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"SMOKE FAILED: {exc}") from exc
    print(
        "SMOKE PASSED: authenticated HTTPS status for "
        f"job {snapshot['job_id']} is {snapshot['status']} "
        f"at revision {snapshot['revision']}"
    )


if __name__ == "__main__":
    main()
