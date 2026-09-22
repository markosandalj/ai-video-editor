from __future__ import annotations

import os
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> None:
    """Verify that the authenticated control process is ready."""

    token = os.environ.get("AI_VIDEO_EDITOR_API_TOKEN")
    if not token:
        raise SystemExit(1)

    request = Request(
        "http://127.0.0.1:8000/healthz",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=3) as response:
            if response.status != 200 or response.read() != b'{"status":"ok"}':
                raise SystemExit(1)
    except (OSError, URLError) as exc:
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
