"""Single-instance guard to prevent concurrent uecfg runs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ue_configurator.locks.single_instance_lock import (
    SingleInstanceError,
    acquire_single_instance_lock as _acquire_single_instance_lock,
)


def acquire_single_instance_lock(app_name: str, log_path: Optional[str] = None):
    """Acquire a single-instance lock. Raises SingleInstanceError on contention."""
    resolved_log = Path(log_path) if log_path else None
    return _acquire_single_instance_lock(app_name, resolved_log)
