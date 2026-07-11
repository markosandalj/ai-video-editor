from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class LangSmithStatus:
    tracing_enabled: bool
    project: str | None
    endpoint: str | None
    has_api_key: bool


def load_runtime_env(env_path: Path | None = None) -> Path | None:
    """Load local runtime environment without overriding exported values."""
    path = env_path or Path.cwd() / ".env"
    if not path.exists():
        return None

    load_dotenv(path, override=False)
    _clear_langsmith_env_caches()
    return path


def langsmith_status() -> LangSmithStatus:
    _clear_langsmith_env_caches()

    from langsmith import utils as langsmith_utils

    return LangSmithStatus(
        tracing_enabled=bool(langsmith_utils.tracing_is_enabled()),
        project=langsmith_utils.get_tracer_project(return_default_value=False),
        endpoint=_first_env("ENDPOINT"),
        has_api_key=_first_env("API_KEY") is not None,
    )


def configure_observability(env_path: Path | None = None) -> LangSmithStatus:
    load_runtime_env(env_path)
    return langsmith_status()


def _first_env(name: str) -> str | None:
    for namespace in ("LANGSMITH", "LANGCHAIN"):
        value = os.environ.get(f"{namespace}_{name}")
        if value and value.strip():
            return value
    return None


def _clear_langsmith_env_caches() -> None:
    try:
        from langsmith import utils as langsmith_utils
    except ImportError:
        return

    for func_name in ("get_env_var", "get_tracer_project"):
        cache_clear = getattr(
            getattr(langsmith_utils, func_name, None),
            "cache_clear",
            None,
        )
        if cache_clear is not None:
            cache_clear()
