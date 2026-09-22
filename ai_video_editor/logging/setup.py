from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from ai_video_editor.config.settings import Settings

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
