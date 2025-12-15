"""Simple file-based single instance lock."""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import platform
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence


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


def _pid_exists(pid: int) -> bool:
    """Best-effort PID existence check on Windows and POSIX."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _detect_repo_root() -> Path:
    """Find the repository root by walking up to .git/pyproject, else cwd."""
    current = Path.cwd().resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return current


def _load_lock_metadata(lock_file: Path) -> Optional[Dict[str, object]]:
    try:
        text = lock_file.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _format_lock_details(metadata: Dict[str, object]) -> str:
    pid = metadata.get("pid")
    started = metadata.get("start_time")
    command = metadata.get("command")
    repo_root = metadata.get("repo_root")
    parts = []
    if pid:
        parts.append(f"PID {pid}")
    if started:
        parts.append(f"started {started}")
    if repo_root:
        parts.append(f"repo {repo_root}")
    if command:
        parts.append(f"command {command}")
    return "; ".join(parts)


def _build_metadata(
    *,
    name: str,
    repo_root: Optional[Path],
    command: Optional[Sequence[str]],
    tool_version: Optional[str],
) -> Dict[str, object]:
    return {
        "name": name,
        "pid": os.getpid(),
        "start_time": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "username": getpass.getuser(),
        "repo_root": str((repo_root or _detect_repo_root()).resolve()),
        "command": list(command) if command is not None else list(sys.argv),
        "tool_version": tool_version or "unknown",
    }


def _install_signal_cleanup(cleanup_fn):
    """Install signal handlers that ensure the lock is removed."""
    previous = {}

    def _handler(signum, frame):
        cleanup_fn()
        prior = previous.get(signum)
        if prior in (None, signal.SIG_IGN):
            return
        if prior == signal.SIG_DFL:
            signal.signal(signum, signal.SIG_DFL)
            try:
                os.kill(os.getpid(), signum)
            except Exception:
                if signum == signal.SIGINT:
                    raise KeyboardInterrupt
            return
        signal.signal(signum, prior)
        prior(signum, frame)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (OSError, RuntimeError, ValueError):
            continue
    return previous


def _restore_signal_handlers(previous):
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except Exception:
            continue


@contextlib.contextmanager
def acquire_single_instance_lock(
    name: str,
    log_path: Optional[Path] = None,
    *,
    lock_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    command: Optional[Sequence[str]] = None,
    tool_version: Optional[str] = None,
):
    """Acquire a file lock to avoid concurrent runs."""
    directory = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir())
    directory.mkdir(parents=True, exist_ok=True)
    lock_file = directory / f"{name}.lock"
    current_metadata = _build_metadata(
        name=name,
        repo_root=repo_root,
        command=command,
        tool_version=tool_version,
    )

    while True:
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(current_metadata, handle, indent=2)
            _write_conflict_log(log_path, f"Lock acquired at {lock_file} by PID {os.getpid()}")
            cleanup_done = False

            def _cleanup():
                nonlocal cleanup_done
                if cleanup_done:
                    return
                cleanup_done = True
                try:
                    lock_file.unlink()
                except FileNotFoundError:
                    return
                except OSError:
                    return

            previous_handlers = _install_signal_cleanup(_cleanup)
            try:
                yield
            finally:
                _restore_signal_handlers(previous_handlers)
                _cleanup()
            return
        except FileExistsError:
            metadata = _load_lock_metadata(lock_file) or {}
            holder_pid_value = metadata.get("pid")
            holder_pid = holder_pid_value if isinstance(holder_pid_value, int) else None
            holder_host = str(metadata.get("hostname", ""))
            holder_repo = metadata.get("repo_root")

            current_host = platform.node()
            current_repo = str((repo_root or _detect_repo_root()).resolve())

            stale_reason = None
            if isinstance(holder_pid, int) and not _pid_exists(holder_pid):
                stale_reason = f"PID {holder_pid} is not running"
            elif holder_host and holder_host != current_host:
                stale_reason = f"hostname differs (lock on {holder_host}, current {current_host})"
            elif holder_repo and holder_repo != current_repo:
                stale_reason = f"repo root differs (lock at {holder_repo}, current {current_repo})"

            if stale_reason:
                msg = f"Stale lock detected ({stale_reason}) - recovering automatically."
                print(msg)
                _write_conflict_log(log_path, msg)
                try:
                    lock_file.unlink()
                except OSError:
                    raise SingleInstanceError(
                        f"Unable to clear stale lock at {lock_file}. Please remove it manually.",
                        lock_file,
                    )
                continue

            interactive = sys.stdin.isatty()
            details = _format_lock_details(metadata)
            if not interactive:
                message = (
                    "Another instance appears to be running. "
                    f"Lock file: {lock_file}. {details or 'Existing lock metadata unavailable.'} "
                    "If this seems stale, rerun interactively or remove the lock once the other process is finished."
                )
                _write_conflict_log(log_path, message)
                raise SingleInstanceError(message, lock_file)

            print("Another instance appears to be running.")
            if details:
                print(f"Details: {details}")
            print("Options:")
            print("  1) Exit (recommended)")
            print("  2) Remove stale lock and restart")
            print("  3) Continue in read-only / scan mode")

            choice = ""
            while True:
                choice = input("Select an option [1]: ").strip()
                if choice in ("", "1", "2", "3"):
                    break
                print("Please enter 1, 2, or 3.")

            if choice in ("", "1"):
                message = "Exiting because another instance is active."
                _write_conflict_log(log_path, f"{message} {details}")
                raise SingleInstanceError(message, lock_file)

            if choice == "2":
                decision_msg = "User chose to remove existing lock and continue."
                _write_conflict_log(log_path, f"{decision_msg} {details}")
                try:
                    lock_file.unlink()
                except OSError:
                    raise SingleInstanceError(
                        f"Unable to remove existing lock at {lock_file}. Please delete it manually.",
                        lock_file,
                    )
                continue

            decision_msg = "User chose to continue without acquiring the lock (read-only/scan mode)."
            _write_conflict_log(log_path, f"{decision_msg} {details}")
            yield
            return
