"""Verification helpers for shared DDC paths."""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path
from typing import List, Tuple


def is_unc_path(path: str) -> bool:
    """Detect UNC paths without touching the filesystem."""

    normalized = path.replace("/", "\\")
    return normalized.startswith("\\\\")


def _unc_host(path: str) -> str:
    normalized = path.replace("/", "\\")
    if not normalized.startswith("\\\\"):
        return ""
    parts = normalized.lstrip("\\").split("\\")
    return parts[0] if parts else ""


def _error_detail(exc: OSError, host: str) -> Tuple[str, List[str]]:
    win_code = getattr(exc, "winerror", None)
    err_no = exc.errno
    hints: List[str] = []
    if win_code == 5 or err_no == 5:
        return "Access denied. You may need to authenticate to the host or adjust share permissions.", hints
    if win_code == 1326 or err_no == 1326:
        cmd_host = host or "HOST"
        hints.append(f"net use \\\\{cmd_host} /user:{cmd_host}\\username *")
        return "Credentials rejected. Try: net use \\\\HOST /user:HOST\\username *", hints
    if win_code in (53, 3) or err_no in (errno.ENOENT, errno.ENOTDIR):
        return "Share name/path likely wrong; verify the share on the host.", hints
    return str(exc), hints


def verify_shared_ddc_path(shared_path: str, *, write_test: bool = False) -> Tuple[bool, str, List[str]]:
    """Perform a non-destructive verification of a shared DDC path."""

    hints: List[str] = []
    path_text = shared_path.strip()
    if not path_text:
        return False, "No path provided.", hints

    unc = is_unc_path(path_text)
    host = _unc_host(path_text) if unc else ""
    path_obj = Path(path_text)

    try:
        if unc:
            os.listdir(path_text)
            detail = "UNC reachable."
        else:
            if not path_obj.exists():
                return False, "Path not found.", hints
            detail = "Path exists."
    except OSError as exc:
        detail, hints = _error_detail(exc, host)
        return False, detail, hints

    if write_test:
        marker = path_obj / f"uecfg_write_test_{int(time.time() * 1000)}.tmp"
        try:
            marker.write_text("uecfg write test", encoding="utf-8")
        except OSError as exc:
            detail, hints = _error_detail(exc, host)
            return False, f"Write test failed: {detail}", hints
        finally:
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass
        detail = f"{detail} Write test succeeded."

    return True, detail, hints
