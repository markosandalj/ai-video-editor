"""Check local worker and callback routing without creating jobs or calling providers."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import dotenv_values


def request_status(url, *, token=None, payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url, headers=headers,
        data=None if payload is None else json.dumps(payload).encode(),
        method="GET" if payload is None else "PUT",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main():
    values = {**dotenv_values(Path.cwd() / ".env.worker.local"), **os.environ}
    assert request_status("http://127.0.0.1:8000/healthz") == 401
    assert request_status("http://127.0.0.1:8000/healthz", token=values["AI_VIDEO_EDITOR_API_TOKEN"]) == 200
    print("Worker health: 200 authenticated; 401 without token")
    job_id = uuid4()
    url = f"{values['GRADIVO_VIDEO_CALLBACK_BASE_URL']}/wt/internal/api/video-processing/jobs/{job_id}/status"
    payload = {
        "job_id": str(job_id), "operation": "analysis", "revision": 1,
        "status": "processing", "progress": {"percent": 0, "stage": "accepted"},
    }
    assert request_status(url, payload=payload) == 401
    assert request_status(url, payload=payload, token=values["GRADIVO_VIDEO_CALLBACK_TOKEN"]) == 404
    print("Gradivo callback: 401 without token; authenticated request reaches missing-job lookup (404)")
    print("No jobs created; no external media/provider requests")


if __name__ == "__main__":
    main()
