from types import SimpleNamespace

from ai_video_editor.worker.diagnostics import exception_diagnostics


def test_provider_exception_keeps_status_and_stack_without_response_body():
    class ProviderError(Exception):
        resp = SimpleNamespace(status=403)

    try:
        raise ProviderError("private provider response body")
    except ProviderError as exc:
        details = exception_diagnostics(exc)
    assert details[0]["http_status"] == 403
    assert details[0]["frames"][-1]["function"] == "test_provider_exception_keeps_status_and_stack_without_response_body"
    assert "private provider response body" not in str(details)


def test_diagnostics_bound_and_redact_stderr_and_stop_cyclic_causes(monkeypatch):
    import subprocess

    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "fake-refresh-token")
    error = subprocess.CalledProcessError(
        1, ["ffmpeg"], stderr=(
            b"x" * 10000 + b"\nfake-refresh-token Bearer other-secret "
            b"https://example.com/file?signature=private\nUnknown encoder"
        ),
    )
    error.__cause__ = error
    details = exception_diagnostics(error)
    assert len(details) == 1
    assert details[0]["returncode"] == 1
    stderr = details[0]["stderr"]
    assert len(stderr) <= 4000
    assert stderr.endswith("Unknown encoder")
    assert not any(secret in stderr for secret in ("fake-refresh-token", "other-secret", "signature=private"))
