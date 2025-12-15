"""Phase 1 probes that audit Visual Studio and related toolchains."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:  # pragma: no cover - not available on non-Windows CI
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext
from ue_configurator.manifest import Manifest
from ue_configurator.manifest.manifest_types import ToolRequirement


@dataclass
class SectionEvaluation:
    status: CheckStatus
    message: str
    evidence: List[str]
    actions: List[ActionRecommendation]


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


def get_vs_instances(ctx: ProbeContext) -> List[VSInstance]:
    """Public helper for other modules to reuse vswhere discovery."""
    return _discover_vs_instances(ctx)


def parse_vs_version(raw: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for token in raw.split("."):
        token = token.strip()
        if not token:
            continue
        try:
            parts.append(int(token))
        except ValueError:
            break
    return tuple(parts)


def compare_versions(left: Tuple[int, ...], right: Tuple[int, ...]) -> int:
    max_len = max(len(left), len(right))
    padded_left = left + (0,) * (max_len - len(left))
    padded_right = right + (0,) * (max_len - len(right))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def _collect_windows_sdks(ctx: ProbeContext) -> List[Tuple[str, str]]:
    cached = ctx.cache.get("windows_sdk_entries")
    if cached is not None:
        return cached
    entries: List[Tuple[str, str]] = []
    if winreg is None:
        ctx.cache["windows_sdk_entries"] = entries
        return entries
    for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0",
                access=winreg.KEY_READ | view,
            ) as key:
                installation_folder, _ = winreg.QueryValueEx(key, "InstallationFolder")
                product_version, _ = winreg.QueryValueEx(key, "ProductVersion")
                entries.append((str(product_version), str(installation_folder)))
        except FileNotFoundError:
            continue
    ctx.cache["windows_sdk_entries"] = entries
    return entries


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

    entries = _collect_windows_sdks(ctx)
    sdk_keys = [f"{version} @ {path}" for version, path in entries]
    status = CheckStatus.PASS if entries else CheckStatus.FAIL
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
    ctx.cache["dotnet.sdks"] = sdk_lines
    ctx.cache["dotnet.runtimes"] = runtime_lines
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
    """Find tool via PATH and common winget install locations."""
    cache_key = f"where::{tool.lower()}"
    cached = ctx.cache.get(cache_key)
    if cached is not None:
        return cached

    paths: List[str] = []

    # Primary: PATH lookup
    result = ctx.run_command(["where", tool], timeout=5)
    if result.returncode == 0:
        paths.extend([line.strip() for line in result.stdout.splitlines() if line.strip()])

    # Secondary: common install roots (winget/choco), in case PATH is stale
    winget_roots = [
        "C:\\Program Files\\CMake\\bin",
        "C:\\Program Files (x86)\\CMake\\bin",
        "C:\\ProgramData\\chocolatey\\bin",
    ]
    for root in winget_roots:
        candidate = Path(root) / tool
        if candidate.exists():
            paths.append(str(candidate))

    # Deduplicate preserving order
    seen: set[str] = set()
    unique_paths: List[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)

    ctx.cache[cache_key] = unique_paths
    return unique_paths


def check_cmake_ninja(ctx: ProbeContext) -> CheckResult:
    cmake_paths = _detect_tool("cmake.exe", ctx)
    ninja_paths = _detect_tool("ninja.exe", ctx)
    missing = []
    if not cmake_paths:
        missing.append("CMake (not on PATH; checked where.exe and common install locations)")
    if not ninja_paths:
        missing.append("Ninja (not on PATH; checked where.exe and common install locations)")
    status = CheckStatus.PASS if not missing else CheckStatus.WARN
    actions = []
    if missing and _winget_available(ctx):
        actions.append(
            ActionRecommendation(
                id="toolchain.autofix",
                description="Auto-install missing build tools via uecfg fix --phase 1 (requires winget + admin).",
                commands=[
                    "uecfg fix --phase 1 --dry-run",
                    "uecfg fix --phase 1 --apply",
                ],
            )
        )
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
    if missing:
        details.append(f"Missing: {', '.join(missing)}")
    return CheckResult(
        id="toolchain.cmake",
        phase=1,
        status=status,
        summary="CMake/Ninja detected" if status == CheckStatus.PASS else "CMake/Ninja missing",
        details="; ".join(details) if details else "Tools not found via PATH or common install locations.",
        evidence=cmake_paths + ninja_paths,
        actions=actions,
    )


def _vs_component_action(required_components: List[str]) -> ActionRecommendation:
    command_parts = ["vs_installer.exe", "modify", "--installPath", "<path>"]
    for comp in required_components:
        command_parts.extend(["--add", comp])
    return ActionRecommendation(
        id="manifest.vs.components",
        description="Add missing Visual Studio workloads/components for the current manifest.",
        commands=[" ".join(command_parts)],
    )


def _evaluate_visual_studio(manifest: "Manifest", ctx: ProbeContext) -> SectionEvaluation:
    instances = _discover_vs_instances(ctx)
    vs_req = manifest.visual_studio
    if not instances:
        return SectionEvaluation(
            status=CheckStatus.FAIL,
            message="Visual Studio not detected.",
            evidence=["vswhere returned zero instances"],
            actions=[_vs_component_action(vs_req.requires_components)] if vs_req.requires_components else [],
        )
    min_tuple = parse_vs_version(vs_req.min_version or "0")
    candidates: List[Tuple[VSInstance, Tuple[int, ...], List[str]]] = []
    for inst in instances:
        version_tuple = parse_vs_version(inst.version)
        if not version_tuple or version_tuple[0] != vs_req.required_major:
            continue
        if vs_req.min_version and compare_versions(version_tuple, min_tuple) < 0:
            continue
        missing = [comp for comp in vs_req.requires_components if comp and comp not in inst.packages]
        candidates.append((inst, version_tuple, missing))
    if not candidates:
        min_label = vs_req.min_version or "n/a"
        return SectionEvaluation(
            status=CheckStatus.FAIL,
            message=f"No Visual Studio {vs_req.required_major}.x instance meets the manifest build requirements.",
            evidence=[f"found={len(instances)}; min_version={min_label}"],
            actions=[_vs_component_action(vs_req.requires_components)] if vs_req.requires_components else [],
        )
    best_inst, best_version, missing = candidates[0]
    if not best_inst.packages:
        return SectionEvaluation(
            status=CheckStatus.WARN,
            message="Unable to verify Visual Studio components (vswhere returned no package list).",
            evidence=[f"{best_inst.display_name} {best_inst.version}"],
            actions=[_vs_component_action(vs_req.requires_components)],
        )
    for inst, version, missing_components in candidates[1:]:
        if len(missing_components) < len(missing):
            best_inst, best_version, missing = inst, version, missing_components
            continue
        if len(missing_components) == len(missing) and compare_versions(version, best_version) > 0:
            best_inst, best_version, missing = inst, version, missing_components
    evidence = [f"{best_inst.display_name} {best_inst.version} @ {best_inst.installation_path}"]
    if not missing:
        return SectionEvaluation(
            status=CheckStatus.PASS,
            message=f"Visual Studio {vs_req.required_major}.x build meets manifest requirements.",
            evidence=evidence,
            actions=[],
        )
    action = _vs_component_action(missing)
    return SectionEvaluation(
        status=CheckStatus.WARN,
        message=f"Missing manifest components: {', '.join(missing)}",
        evidence=evidence,
        actions=[action],
    )


def _evaluate_msvc(manifest: "Manifest", ctx: ProbeContext) -> SectionEvaluation:
    instances = _discover_vs_instances(ctx)
    toolsets: List[Tuple[str, str]] = []
    for inst in instances:
        msvc_root = inst.installation_path / "VC" / "Tools" / "MSVC"
        if not msvc_root.is_dir():
            continue
        for child in msvc_root.iterdir():
            if child.is_dir():
                toolsets.append((inst.display_name, child.name))
    required_family = manifest.msvc.preferred_toolset_family
    match = next((entry for entry in toolsets if entry[1].startswith(required_family)), None)
    if match:
        return SectionEvaluation(
            status=CheckStatus.PASS,
            message=f"MSVC toolset {required_family} detected.",
            evidence=[f"{match[0]} -> {match[1]}"],
            actions=[],
        )
    evidence = [f"{name} -> {version}" for name, version in toolsets] or ["no toolsets found"]
    action = _vs_component_action([f"MSVC.{required_family}"])
    return SectionEvaluation(
        status=CheckStatus.FAIL,
        message=f"MSVC toolset {required_family} not installed.",
        evidence=evidence,
        actions=[action],
    )


def _evaluate_windows_sdk(manifest: "Manifest", ctx: ProbeContext) -> SectionEvaluation:
    entries = _collect_windows_sdks(ctx)
    if not entries:
        if winreg is None:
            return SectionEvaluation(
                status=CheckStatus.WARN,
                message="Unable to inspect Windows SDK registry hive on this platform.",
                evidence=[],
                actions=[],
            )
        return SectionEvaluation(
            status=CheckStatus.FAIL,
            message="Required Windows SDK not detected.",
            evidence=["no registry entries"],
            actions=[
                ActionRecommendation(
                    id="manifest.sdk.install",
                    description="Install Windows 10/11 SDK via Visual Studio Installer.",
                    commands=["vs_installer.exe modify --add Microsoft.VisualStudio.Component.Windows10SDK.22621"],
                )
            ],
        )
    versions = [version for version, _ in entries]
    preferred_list = list(manifest.windows_sdk.preferred_versions)
    preferred_single = manifest.windows_sdk.preferred_version
    if preferred_single and preferred_single not in preferred_list:
        preferred_list.append(preferred_single)
    minimum = manifest.windows_sdk.minimum_version
    evidence = [f"{version} @ {path}" for version, path in entries]
    if preferred_list and any(version in preferred_list for version in versions):
        return SectionEvaluation(
            status=CheckStatus.PASS,
            message=f"Windows SDK matches preferred versions ({preferred_list}).",
            evidence=evidence,
            actions=[],
        )
    if minimum:
        min_tuple = parse_vs_version(minimum)
        meets_min = any(compare_versions(parse_vs_version(ver), min_tuple) >= 0 for ver in versions)
        if not meets_min:
            return SectionEvaluation(
                status=CheckStatus.FAIL,
                message=f"Windows SDK below minimum version {minimum}.",
                evidence=evidence,
                actions=[
                    ActionRecommendation(
                        id="manifest.sdk.upgrade",
                        description="Upgrade Windows SDK to the version required by this UE release.",
                        commands=["vs_installer.exe modify --add Microsoft.VisualStudio.Component.Windows10SDK.22621"],
                    )
                ],
            )
    return SectionEvaluation(
        status=CheckStatus.WARN,
        message="Windows SDK installed but not in preferred manifest list.",
        evidence=evidence,
        actions=[],
    )


def _check_single_tool(ctx: ProbeContext, requirement: ToolRequirement) -> SectionEvaluation:
    name = requirement.name.lower()
    evidence: List[str] = []
    actions: List[ActionRecommendation] = []
    status = CheckStatus.PASS
    message = f"{requirement.name} detected."

    def _winget_action() -> List[ActionRecommendation]:
        if not requirement.winget_id:
            return []
        return [
            ActionRecommendation(
                id=f"manifest.install.{name}",
                description=f"Install {requirement.name} via winget.",
                commands=[f"winget install --id {requirement.winget_id} --source winget"],
            )
        ]

    if name == "cmake":
        paths = _detect_tool("cmake.exe", ctx)
        if not paths:
            status = CheckStatus.FAIL
            message = "CMake missing."
            actions = _winget_action()
        else:
            evidence.extend(paths)
    elif name == "ninja":
        paths = _detect_tool("ninja.exe", ctx)
        if not paths:
            status = CheckStatus.FAIL
            message = "Ninja missing."
            actions = _winget_action()
        else:
            evidence.extend(paths)
    elif name == "dotnet":
        sdks = ctx.cache.get("dotnet.sdks")
        if sdks is None:
            check_dotnet(ctx)
            sdks = ctx.cache.get("dotnet.sdks", [])
        if not sdks:
            status = CheckStatus.FAIL
            message = ".NET SDK not detected."
            actions = _winget_action()
        else:
            first = sdks[0].split()
            version = first[0] if first else sdks[0]
            evidence.append(version)
            if requirement.min_version:
                if compare_versions(parse_vs_version(version), parse_vs_version(requirement.min_version)) < 0:
                    status = CheckStatus.FAIL
                    message = f".NET SDK {version} below required {requirement.min_version}."
                    actions = _winget_action()
    elif name == "git":
        result = ctx.run_command(["git", "--version"], timeout=10)
        if result.returncode != 0:
            status = CheckStatus.FAIL
            message = "Git command missing."
            actions = _winget_action()
        else:
            evidence.append(result.stdout.strip())
    else:
        paths = _detect_tool(f"{requirement.name}.exe", ctx)
        if not paths:
            status = CheckStatus.FAIL
            message = f"{requirement.name} not detected."
            actions = _winget_action()
        else:
            evidence.extend(paths)

    return SectionEvaluation(
        status=status,
        message=message,
        evidence=evidence,
        actions=actions,
    )


def _evaluate_extras(manifest: "Manifest", ctx: ProbeContext) -> SectionEvaluation:
    required = [req for req in manifest.extras.values() if req.required]
    if not required:
        return SectionEvaluation(
            status=CheckStatus.NA,
            message="No supplemental tool requirements in manifest.",
            evidence=[],
            actions=[],
        )
    overall_status = CheckStatus.PASS
    messages: List[str] = []
    evidence: List[str] = []
    actions: List[ActionRecommendation] = []
    for requirement in required:
        section = _check_single_tool(ctx, requirement)
        if section.status == CheckStatus.FAIL:
            overall_status = CheckStatus.FAIL
        elif section.status == CheckStatus.WARN and overall_status != CheckStatus.FAIL:
            overall_status = CheckStatus.WARN
        if section.status != CheckStatus.PASS:
            messages.append(section.message)
        evidence.extend(section.evidence)
        actions.extend(section.actions)
    if overall_status == CheckStatus.PASS:
        message = "All manifest supplemental tools detected."
    else:
        message = "; ".join(messages)
    return SectionEvaluation(
        status=overall_status,
        message=message,
        evidence=evidence,
        actions=actions,
    )


def check_manifest_compliance(ctx: ProbeContext) -> CheckResult:
    manifest: Optional["Manifest"] = getattr(ctx, "manifest", None)
    if manifest is None:
        return CheckResult(
            id="toolchain.manifest",
            phase=1,
            status=CheckStatus.NA,
            summary="No toolchain manifest selected",
            details="Run with --ue-version (e.g., 5.7) or --manifest to enforce a specific toolchain.",
            evidence=[],
            actions=[
                ActionRecommendation(
                    id="manifest.select",
                    description="Audit against UE 5.7 requirements",
                    commands=["uecfg scan --phase 1 --ue-version 5.7"],
                )
            ],
        )

    sections = [
        _evaluate_visual_studio(manifest, ctx),
        _evaluate_msvc(manifest, ctx),
        _evaluate_windows_sdk(manifest, ctx),
        _evaluate_extras(manifest, ctx),
    ]
    status = CheckStatus.PASS
    details: List[str] = []
    evidence = [f"Manifest {manifest.id} fingerprint {manifest.fingerprint[:12]}"]
    actions: List[ActionRecommendation] = []
    for section in sections:
        if section.status == CheckStatus.FAIL:
            status = CheckStatus.FAIL
        elif section.status == CheckStatus.WARN and status != CheckStatus.FAIL:
            status = CheckStatus.WARN
        if section.status != CheckStatus.NA:
            details.append(section.message)
        evidence.extend(section.evidence)
        actions.extend(section.actions)
    if status == CheckStatus.PASS:
        summary = f"{manifest.describe()} manifest compliance verified."
    elif status == CheckStatus.WARN:
        summary = f"{manifest.describe()} manifest compliance warnings."
    else:
        summary = f"{manifest.describe()} manifest compliance failed."
    if status != CheckStatus.PASS:
        actions.append(
            ActionRecommendation(
                id="manifest.autofix",
                description="Apply manifest-aligned fixes",
                commands=[
                    f"uecfg fix --phase 1 --dry-run --ue-version {manifest.ue_version}",
                    f"uecfg fix --phase 1 --apply --ue-version {manifest.ue_version}",
                ],
            )
        )
    return CheckResult(
        id="toolchain.manifest",
        phase=1,
        status=status,
        summary=summary,
        details="; ".join(details) if details else "No additional details.",
        evidence=[entry for entry in evidence if entry],
        actions=actions,
    )
PHASE1_PROBES = [
    check_visual_studio,
    check_msvc_toolchain,
    check_windows_sdks,
    check_dotnet,
    check_cmake_ninja,
    check_manifest_compliance,
]


def _winget_available(ctx: ProbeContext) -> bool:
    cached = ctx.cache.get("winget_available")
    if cached is not None:
        return bool(cached)
    result = ctx.run_command(["where", "winget"], timeout=5)
    available = result.returncode == 0
    ctx.cache["winget_available"] = available
    return available
