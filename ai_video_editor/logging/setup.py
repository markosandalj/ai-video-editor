from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from ai_video_editor.config.settings import Settings

_video_handler_ids: dict[str, int] = {}


def setup_logging(settings: Settings, *, run_id: str | None = None) -> Path:
    """
    Configure Loguru: console, per-run log file under output_dir/logs/.
    Returns path to the run log file.
    """
    logger.remove()

    log_level = settings.general.log_level
    logger.add(
        sys.stderr,
        level=log_level,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    logs_dir = settings.general.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_log_path = logs_dir / f"run_{rid}.log"

    logger.add(
        run_log_path,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        encoding="utf-8",
    )

    return run_log_path


def attach_video_log(settings: Settings, video_stem: str) -> Path:
    """Route messages with `logger.bind(video=video_stem)` to a dedicated file."""
    logs_dir = settings.general.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"video_{video_stem}.log"
    stem = video_stem

    def _filter(record: dict) -> bool:
        return record["extra"].get("video") == stem

    hid = logger.add(
        path,
        level="DEBUG",
        filter=_filter,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        encoding="utf-8",
    )
    _video_handler_ids[stem] = hid
    return path


def remove_video_log(video_stem: str) -> None:
    hid = _video_handler_ids.pop(video_stem, None)
    if hid is not None:
        logger.remove(hid)
