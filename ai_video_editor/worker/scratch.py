"""Cleanup for UUID-named scratch directories owned by one worker instance."""

import shutil
from pathlib import Path
from uuid import UUID


def remove_job_scratch(root: Path, job_id: UUID) -> None:
    path = root / str(job_id)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def remove_abandoned_scratch(root: Path) -> None:
    # Called before accepting jobs, after the previous worker has stopped.
    root.mkdir(parents=True, exist_ok=True)
    for path in root.iterdir():
        try:
            job_id = UUID(path.name)
        except ValueError:
            continue
        if str(job_id) == path.name:
            remove_job_scratch(root, job_id)
