"""Single-instance guard to prevent concurrent uecfg runs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from ue_configurator import __version__
from ue_configurator.locks.single_instance_lock import (
    SingleInstanceError,
    acquire_single_instance_lock as _acquire_single_instance_lock,
)


def acquire_single_instance_lock(
    app_name: str,
    log_path: Optional[str] = None,
    *,
    lock_dir: Optional[Path | str] = None,
    repo_root: Optional[Path | str] = None,
    command: Optional[Sequence[str]] = None,
):
    """Acquire a single-instance lock. Raises SingleInstanceError on contention."""
    resolved_log = Path(log_path) if log_path else None
    resolved_lock_dir = Path(lock_dir) if lock_dir else None
    resolved_repo = Path(repo_root) if repo_root else None
    return _acquire_single_instance_lock(
        app_name,
        resolved_log,
        lock_dir=resolved_lock_dir,
        repo_root=resolved_repo,
        command=command,
        tool_version=__version__,
    )
