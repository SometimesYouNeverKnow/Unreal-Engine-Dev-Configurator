"""Single-instance guard to prevent concurrent uecfg runs."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


class SingleInstanceError(RuntimeError):
    """Raised when another instance is already running."""

    def __init__(self, message: str, holder: Optional[str] = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.holder = holder


def _lock_name(app_name: str) -> str:
    return f"Global\\{app_name}_single_instance_lock"


@contextlib.contextmanager
def _windows_mutex_lock(app_name: str):
    """Use a named mutex; auto-released on crash/exit."""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ERROR_ALREADY_EXISTS = 183
    name = _lock_name(app_name)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise SingleInstanceError("Unable to create instance lock (CreateMutexW failed).")
    try:
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            raise SingleInstanceError(
                f"{app_name} is already running (another instance holds the lock). Exiting."
            )
        yield
    finally:
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def _file_lock(app_name: str):
    """Fallback cross-platform file lock."""
    lock_dir = Path(tempfile.gettempdir())
    lock_file = lock_dir / f"{app_name}.lock"
    holder_info = None
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()}\nstarted={time.time()}\n")
        try:
            yield
        finally:
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
    except FileExistsError:
        try:
            holder_info = lock_file.read_text(encoding="utf-8").strip()
        except Exception:
            holder_info = None
        raise SingleInstanceError(
            f"{app_name} is already running (another instance holds the lock). Exiting.",
            holder=holder_info,
        )


def acquire_single_instance_lock(app_name: str, log_path: Optional[str] = None):
    """Acquire a single-instance lock. Raises SingleInstanceError on contention."""
    if os.name == "nt":
        return _windows_mutex_lock(app_name)
    return _file_lock(app_name)
