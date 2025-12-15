"""Simple file-based single instance lock."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Optional


class SingleInstanceError(RuntimeError):
    """Raised when another process already holds the lock."""

    def __init__(self, message: str, lock_path: Path) -> None:
        super().__init__(message)
        self.user_message = message
        self.lock_path = lock_path


def _write_conflict_log(log_path: Optional[Path], message: str) -> None:
    if not log_path:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}{os.linesep}")
    except OSError:
        return


@contextlib.contextmanager
def acquire_single_instance_lock(
    name: str,
    log_path: Optional[Path] = None,
    *,
    lock_dir: Optional[Path] = None,
):
    """Acquire a file lock to avoid concurrent runs."""
    directory = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir())
    directory.mkdir(parents=True, exist_ok=True)
    lock_file = directory / f"{name}.lock"
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\nstarted={time.time()}\n")
        try:
            yield
        finally:
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
    except FileExistsError:
        message = (
            f"Another instance is already running (lock file {lock_file}). "
            "If this looks stale, remove the lock and re-run."
        )
        _write_conflict_log(log_path, message)
        raise SingleInstanceError(message, lock_file)
