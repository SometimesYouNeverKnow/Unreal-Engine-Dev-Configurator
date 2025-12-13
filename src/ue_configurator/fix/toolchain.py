"""Safe helpers for installing optional toolchain components."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import List, Sequence

from ue_configurator.probe.base import ProbeContext


TOOLS = [
    ("CMake", "cmake.exe", "Kitware.CMake"),
    ("Ninja", "ninja.exe", "Ninja-build.Ninja"),
]


@dataclass
class WingetOutcome:
    success: bool
    message: str
    logs: List[str]


def _is_admin() -> bool:
    try:
        shell32 = getattr(ctypes, "windll", None)
        return bool(shell32 and shell32.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _check_tool(executable: str, ctx: ProbeContext) -> bool:
    result = ctx.run_command(["where", executable], timeout=5)
    return result.returncode == 0


def winget_available(ctx: ProbeContext) -> bool:
    cached = ctx.cache.get("winget_available")
    if cached is not None:
        return bool(cached)
    result = ctx.run_command(["where", "winget"], timeout=5)
    available = result.returncode == 0
    ctx.cache["winget_available"] = available
    return available


def ensure_toolchain_extras(ctx: ProbeContext) -> WingetOutcome:
    logs: List[str] = []
    missing = [(name, pkg_id) for name, exe, pkg_id in TOOLS if not _check_tool(exe, ctx)]
    if not missing:
        message = "All optional toolchain components (CMake/Ninja) are installed."
        logs.append("[uecfg] " + message)
        return WingetOutcome(True, message, logs)

    if not winget_available(ctx):
        message = "winget command not found; unable to auto-install missing tools."
        logs.append("[uecfg] " + message)
        for name, pkg_id in missing:
            logs.append(
                f"[uecfg] Install {name} manually or run 'winget install --id {pkg_id}' after winget is installed."
            )
        return WingetOutcome(False, message, logs)

    if not _is_admin() and not ctx.dry_run:
        message = "Administrator privileges are required to install packages via winget."
        logs.append("[uecfg] " + message)
        logs.append("[uecfg] Re-run from an elevated terminal (Start-Process powershell -Verb runAs) or install manually.")
        return WingetOutcome(False, message, logs)

    overall_success = True
    for name, pkg_id in missing:
        outcome = install_package_via_winget(ctx, pkg_id, name)
        logs.extend(outcome.logs)
        overall_success = overall_success and outcome.success

    message = "Toolchain extras processed."
    return WingetOutcome(overall_success, message, logs)


def install_package_via_winget(ctx: ProbeContext, package_id: str, name: str) -> WingetOutcome:
    logs: List[str] = []
    if not winget_available(ctx):
        message = f"winget not available; {name} must be installed manually."
        logs.append("[uecfg] " + message)
        return WingetOutcome(False, message, logs)

    if ctx.dry_run:
        cmd = f"winget install --id {package_id} -e --source winget"
        logs.append(f"[dry-run] Would run: {cmd}")
        return WingetOutcome(True, f"Dry-run complete for {name}.", logs)

    if not _is_admin():
        message = f"Administrator privileges required to install {name}."
        logs.append("[uecfg] " + message)
        return WingetOutcome(False, message, logs)

    command: Sequence[str] = [
        "winget",
        "install",
        "--id",
        package_id,
        "-e",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    logs.append(f"[uecfg] Installing {name} via winget...")
    result = ctx.run_command(command, timeout=600)
    if result.returncode == 0:
        logs.append(f"[uecfg] {name} installed successfully.")
        return WingetOutcome(True, f"{name} installed.", logs)
    logs.append(f"[uecfg] Failed to install {name} (exit {result.returncode}).")
    logs.append(result.stdout.strip() or result.stderr.strip())
    return WingetOutcome(False, f"{name} installation failed.", logs)
