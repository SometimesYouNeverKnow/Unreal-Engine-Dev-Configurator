"""Phase 0 probes covering OS and baseline tooling."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
import platform
import shutil
from pathlib import Path
from typing import List

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext


DISK_WARN_BYTES = 250 * 1024**3  # 250 GB recommended for UE source builds
RAM_WARN_BYTES = 32 * 1024**3
CPU_WARN_COUNT = 8


def check_windows_version(ctx: ProbeContext) -> CheckResult:
    uname = platform.uname()
    is_windows = uname.system.lower() == "windows"
    summary = f"{uname.system} {uname.release} build {uname.version}"
    status = CheckStatus.PASS if is_windows else CheckStatus.FAIL
    details = (
        "Detected a Windows build that matches Epic's supported target."
        if is_windows
        else "Unreal Engine source builds are only supported on Windows 10/11."
    )
    return CheckResult(
        id="os.version",
        phase=0,
        status=status,
        summary=summary,
        details=details,
        evidence=[str(uname)],
        actions=[],
    )


def check_admin_rights(ctx: ProbeContext) -> CheckResult:
    try:
        shell32 = getattr(ctypes, "windll", None)
        is_admin = bool(shell32 and shell32.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    status = CheckStatus.PASS if is_admin else CheckStatus.WARN
    details = (
        "Administrator rights detected. You can install Visual Studio components."
        if is_admin
        else "Administrator elevation is recommended for installing Visual Studio workloads and SDKs."
    )
    return CheckResult(
        id="os.admin",
        phase=0,
        status=status,
        summary="Administrator rights" if is_admin else "Standard user session",
        details=details,
        evidence=[f"is_admin={is_admin}"],
        actions=[
            ActionRecommendation(
                id="admin.elevate",
                description="Open an elevated PowerShell session for installs",
                commands=["Start-Process powershell -Verb runAs"],
            )
        ]
        if not is_admin
        else [],
    )


def check_powershell_version(ctx: ProbeContext) -> CheckResult:
    cmd = ["powershell", "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]
    result = ctx.run_command(cmd, timeout=10)
    version = result.stdout.strip()
    ok = result.returncode == 0 and bool(version)
    status = CheckStatus.PASS if ok else CheckStatus.WARN
    details = (
        f"PowerShell {version} available."
        if ok
        else "PowerShell did not respond. Remote scripts may fail."
    )
    actions = []
    if not ok:
        actions.append(
            ActionRecommendation(
                id="powershell.install",
                description="Install the latest PowerShell from the Microsoft Store or winget",
                commands=["winget install --id Microsoft.PowerShell --source winget"],
            )
        )
    return CheckResult(
        id="os.powershell",
        phase=0,
        status=status,
        summary="PowerShell version",
        details=details,
        evidence=[version or result.stderr.strip()],
        actions=actions,
    )


def check_git_presence(ctx: ProbeContext) -> CheckResult:
    cmd = ["git", "--version"]
    result = ctx.run_command(cmd, timeout=10)
    ok = result.returncode == 0
    actions: List[ActionRecommendation] = []
    if not ok:
        actions.append(
            ActionRecommendation(
                id="git.install",
                description="Install Git using winget or download from git-scm.com",
                commands=["winget install --id Git.Git --source winget"],
            )
        )
    return CheckResult(
        id="os.git",
        phase=0,
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        summary=result.stdout.strip() or "Git missing",
        details="Git is required to clone Unreal Engine repositories." if ok else "Git not found in PATH.",
        evidence=[result.stdout.strip() or result.stderr.strip()],
        actions=actions,
    )


def check_disk_space(ctx: ProbeContext) -> CheckResult:
    drive = Path(ctx.workdir).anchor or os.environ.get("SystemDrive", "C:\\")
    usage = shutil.disk_usage(drive)
    free_gb = usage.free / 1024**3
    status = CheckStatus.PASS if usage.free >= DISK_WARN_BYTES else CheckStatus.WARN
    details = (
        "Sufficient disk space detected for Unreal Engine source builds."
        if status == CheckStatus.PASS
        else "Less than 250 GB free. Consider freeing space before cloning/building UE."
    )
    return CheckResult(
        id="os.disk",
        phase=0,
        status=status,
        summary=f"{free_gb:.1f} GB free on {drive}",
        details=details,
        evidence=[f"total={usage.total}", f"free={usage.free}"],
        actions=[
            ActionRecommendation(
                id="disk.cleanup",
                description="Free disk space on the build drive",
                commands=["cleanmgr"],
            )
        ]
        if status == CheckStatus.WARN
        else [],
    )


def _get_total_ram_bytes() -> int:
    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    if kernel32 is None:
        return 0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    success = kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    if not success:  # pragma: no cover - defensive
        return 0
    return int(stat.ullTotalPhys)


def check_hardware_profile(ctx: ProbeContext) -> CheckResult:
    cores = os.cpu_count() or 1
    ram_bytes = _get_total_ram_bytes()
    ram_gb = ram_bytes / 1024**3 if ram_bytes else 0
    cpu_status = cores >= CPU_WARN_COUNT
    ram_status = ram_bytes >= RAM_WARN_BYTES
    status = CheckStatus.PASS if (cpu_status and ram_status) else CheckStatus.WARN
    detail_parts = [
        f"CPU cores: {cores} (recommend >= {CPU_WARN_COUNT})",
        f"RAM: {ram_gb:.1f} GB (recommend >= {RAM_WARN_BYTES/1024**3:.0f} GB)",
    ]
    return CheckResult(
        id="os.hardware",
        phase=0,
        status=status,
        summary=f"{cores} cores / {ram_gb:.1f} GB RAM",
        details="; ".join(detail_parts),
        evidence=detail_parts,
        actions=[
            ActionRecommendation(
                id="hardware.upgrade",
                description="Consider upgrading RAM/CPU or using a beefier build machine",
                commands=[],
            )
        ]
        if status == CheckStatus.WARN
        else [],
    )


PHASE0_PROBES = [
    check_windows_version,
    check_admin_rights,
    check_powershell_version,
    check_git_presence,
    check_disk_space,
    check_hardware_profile,
]
