"""Phase 1 probes that audit Visual Studio and related toolchains."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import List, Sequence

try:  # pragma: no cover - not available on non-Windows CI
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext


@dataclass
class VSInstance:
    display_name: str
    installation_path: Path
    version: str
    product_id: str
    packages: List[str]


def _vswhere_candidates() -> Sequence[str]:
    candidates = ["vswhere"]
    pf86 = os.environ.get("ProgramFiles(x86)")
    if pf86:
        candidates.append(str(Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"))
    pf = os.environ.get("ProgramFiles")
    if pf:
        candidates.append(str(Path(pf) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"))
    return candidates


def _discover_vs_instances(ctx: ProbeContext) -> List[VSInstance]:
    if "vs_instances" in ctx.cache:
        return ctx.cache["vs_instances"]

    instances: List[VSInstance] = []
    for candidate in _vswhere_candidates():
        cmd = [candidate, "-all", "-format", "json", "-prerelease", "-products", "*"]
        result = ctx.run_command(cmd, timeout=15)
        if result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        for inst in parsed:
            path = Path(inst.get("installationPath", ""))
            display = inst.get("displayName", path.name)
            packages = [pkg.get("id", "") for pkg in inst.get("packages", []) if pkg.get("id")]
            instances.append(
                VSInstance(
                    display_name=display,
                    installation_path=path,
                    version=inst.get("installationVersion", "unknown"),
                    product_id=inst.get("productId", "unknown"),
                    packages=packages,
                )
            )
        if instances:
            break

    ctx.cache["vs_instances"] = instances
    return instances


def check_visual_studio(ctx: ProbeContext) -> CheckResult:
    instances = _discover_vs_instances(ctx)
    if not instances:
        actions = [
            ActionRecommendation(
                id="vs.install",
                description="Install Visual Studio 2022 with the Unreal Engine recommended workloads",
                commands=[
                    "vs_installer.exe modify --installPath <path> --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                ],
            )
        ]
        return CheckResult(
            id="toolchain.vs",
            phase=1,
            status=CheckStatus.FAIL,
            summary="Visual Studio not found",
            details="vswhere could not find any installed Visual Studio instances.",
            evidence=["vswhere"],
            actions=actions,
        )

    evidence = [f"{inst.display_name} ({inst.version}) @ {inst.installation_path}" for inst in instances]
    return CheckResult(
        id="toolchain.vs",
        phase=1,
        status=CheckStatus.PASS,
        summary=f"{len(instances)} Visual Studio instance(s) detected",
        details="; ".join(evidence),
        evidence=evidence,
        actions=[],
    )


def check_msvc_toolchain(ctx: ProbeContext) -> CheckResult:
    instances = _discover_vs_instances(ctx)
    msvc_paths: List[str] = []
    for inst in instances:
        msvc_root = inst.installation_path / "VC" / "Tools" / "MSVC"
        if not msvc_root.is_dir():
            continue
        for child in sorted(msvc_root.iterdir()):
            if child.is_dir():
                bin_path = child / "bin" / "Hostx64" / "x64"
                if bin_path.exists():
                    msvc_paths.append(str(bin_path))
    status = CheckStatus.PASS if msvc_paths else CheckStatus.FAIL
    actions = []
    if not msvc_paths:
        actions.append(
            ActionRecommendation(
                id="vs.modify",
                description="Add the C++ Desktop workload to Visual Studio",
                commands=[
                    "vs_installer.exe modify --installPath <path> --add Microsoft.VisualStudio.Workload.NativeDesktop",
                ],
            )
        )
    return CheckResult(
        id="toolchain.msvc",
        phase=1,
        status=status,
        summary="MSVC toolchain located" if msvc_paths else "MSVC components missing",
        details="; ".join(msvc_paths) if msvc_paths else "No MSVC bin directories detected.",
        evidence=msvc_paths or ["missing"],
        actions=actions,
    )


def check_windows_sdks(ctx: ProbeContext) -> CheckResult:
    if winreg is None:  # pragma: no cover - non-Windows
        return CheckResult(
            id="toolchain.sdk",
            phase=1,
            status=CheckStatus.WARN,
            summary="winreg unavailable",
            details="Cannot inspect Windows SDK registry hive from this environment.",
            evidence=[],
            actions=[],
        )

    sdk_keys: List[str] = []
    for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0",
                access=winreg.KEY_READ | view,
            ) as key:
                installation_folder, _ = winreg.QueryValueEx(key, "InstallationFolder")
                product_version, _ = winreg.QueryValueEx(key, "ProductVersion")
                sdk_keys.append(f"{product_version} @ {installation_folder}")
        except FileNotFoundError:
            continue
    status = CheckStatus.PASS if sdk_keys else CheckStatus.FAIL
    actions = []
    if not sdk_keys:
        actions.append(
            ActionRecommendation(
                id="sdk.install",
                description="Install the Windows 10/11 SDK via Visual Studio Installer",
                commands=[
                    "vs_installer.exe modify --add Microsoft.VisualStudio.Component.Windows10SDK.20348",
                ],
            )
        )
    return CheckResult(
        id="toolchain.sdk",
        phase=1,
        status=status,
        summary="Windows SDK detected" if sdk_keys else "Windows SDK missing",
        details="; ".join(sdk_keys) if sdk_keys else "No SDK registry keys discovered.",
        evidence=sdk_keys or ["missing"],
        actions=actions,
    )


def check_dotnet(ctx: ProbeContext) -> CheckResult:
    sdk_result = ctx.run_command(["dotnet", "--list-sdks"], timeout=10)
    runtime_result = ctx.run_command(["dotnet", "--list-runtimes"], timeout=10)
    sdk_lines = [line.strip() for line in sdk_result.stdout.splitlines() if line.strip()]
    runtime_lines = [line.strip() for line in runtime_result.stdout.splitlines() if line.strip()]
    ok = sdk_result.returncode == 0 and bool(sdk_lines)
    status = CheckStatus.PASS if ok else CheckStatus.WARN
    actions = []
    if not ok:
        actions.append(
            ActionRecommendation(
                id="dotnet.install",
                description="Install the .NET SDK 6.0+",
                commands=["winget install --id Microsoft.DotNet.SDK.8 --source winget"],
            )
        )
    details = (
        f"SDKs: {', '.join(sdk_lines[:3])}"
        if ok
        else "dotnet command missing or returned no SDKs."
    )
    evidence = sdk_lines + runtime_lines
    return CheckResult(
        id="toolchain.dotnet",
        phase=1,
        status=status,
        summary="dotnet SDKs detected" if ok else "dotnet SDK missing",
        details=details,
        evidence=evidence,
        actions=actions,
    )


def _detect_tool(tool: str, ctx: ProbeContext) -> List[str]:
    result = ctx.run_command(["where", tool], timeout=5)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_cmake_ninja(ctx: ProbeContext) -> CheckResult:
    cmake_paths = _detect_tool("cmake.exe", ctx)
    ninja_paths = _detect_tool("ninja.exe", ctx)
    ok = bool(cmake_paths)
    status = CheckStatus.PASS if ok else CheckStatus.WARN
    actions = []
    if not cmake_paths:
        actions.append(
            ActionRecommendation(
                id="cmake.install",
                description="Install CMake to benefit from Unreal's CMake exporters",
                commands=["winget install --id Kitware.CMake --source winget"],
            )
        )
    if not ninja_paths:
        actions.append(
            ActionRecommendation(
                id="ninja.install",
                description="Install Ninja for faster C++ iteration",
                commands=["winget install --id Ninja-build.Ninja --source winget"],
            )
        )
    details = []
    if cmake_paths:
        details.append(f"CMake: {cmake_paths[0]}")
    if ninja_paths:
        details.append(f"Ninja: {ninja_paths[0]}")
    return CheckResult(
        id="toolchain.cmake",
        phase=1,
        status=status,
        summary="CMake/Ninja detected" if ok else "CMake missing",
        details="; ".join(details) if details else "Tools not found via where.exe.",
        evidence=cmake_paths + ninja_paths,
        actions=actions,
    )


PHASE1_PROBES = [
    check_visual_studio,
    check_msvc_toolchain,
    check_windows_sdks,
    check_dotnet,
    check_cmake_ninja,
]
