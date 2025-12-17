"""Phase 2 probes for Unreal Engine prerequisites."""

from __future__ import annotations

import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

try:  # pragma: no cover - Windows only
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext
from ue_configurator.probe import horde as horde_probe
from ue_configurator.ue import config_paths
from ue_configurator.ue.build_config import parse_build_configuration_flags
from ue_configurator.ue.build_targets import determine_build_plan, missing_targets, summarize_plan
from ue_configurator.ue.artifact_resolver import ArtifactResolver


def check_ue_root(ctx: ProbeContext) -> CheckResult:
    if not ctx.ue_root:
        return CheckResult(
            id="ue.root",
            phase=2,
            status=CheckStatus.WARN,
            summary="No --ue-root provided",
            details="Provide the Unreal Engine source directory via --ue-root to enable deeper checks.",
            evidence=[],
            actions=[
                ActionRecommendation(
                    id="ue.provide-root",
                    description="Re-run scan with the UE clone path",
                    commands=["uecfg scan --phase 2 --ue-root C:\\path\\to\\UnrealEngine"],
                )
            ],
        )

    ue_path = Path(ctx.ue_root).expanduser()
    if not ue_path.exists():
        return CheckResult(
            id="ue.root",
            phase=2,
            status=CheckStatus.FAIL,
            summary=f"UE root {ue_path} missing",
            details="The supplied UE directory does not exist.",
            evidence=[str(ue_path)],
            actions=[
                ActionRecommendation(
                    id="ue.clone",
                    description="Clone Unreal Engine from Epic's GitHub mirror",
                    commands=["git clone https://github.com/EpicGames/UnrealEngine.git"],
                )
            ],
        )

    ctx.cache["ue_root_path"] = ue_path
    return CheckResult(
        id="ue.root",
        phase=2,
        status=CheckStatus.PASS,
        summary=f"UE root detected at {ue_path}",
        details="UE root provided; Setup/GenerateProjectFiles checks enabled.",
        evidence=[str(ue_path)],
        actions=[],
    )


def check_setup_scripts(ctx: ProbeContext) -> CheckResult:
    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.scripts",
            phase=2,
            status=CheckStatus.SKIP,
            summary="Setup scripts skipped",
            details="Provide --ue-root to validate Setup.bat and GenerateProjectFiles.bat.",
            evidence=[],
            actions=[],
        )

    setup = ue_path / "Setup.bat"
    gen = ue_path / "GenerateProjectFiles.bat"
    missing = [path.name for path in (setup, gen) if not path.exists()]
    status = CheckStatus.PASS if not missing else CheckStatus.FAIL
    actions = []
    if missing:
        actions.append(
            ActionRecommendation(
                id="ue.sync",
                description="Sync missing batch files from the UE repository",
                commands=[f"git checkout HEAD -- {' '.join(missing)}"],
            )
        )
    details = f"Setup.bat: {'present' if setup.exists() else 'missing'}, GPF: {'present' if gen.exists() else 'missing'}"
    return CheckResult(
        id="ue.scripts",
        phase=2,
        status=status,
        summary="Setup/GenerateProjectFiles scripts",
        details=details,
        evidence=[str(setup), str(gen)],
        actions=actions,
    )


def check_redist_installer(ctx: ProbeContext) -> CheckResult:
    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.redist",
            phase=2,
            status=CheckStatus.SKIP,
            summary="UE prerequisites skipped",
            details="Provide --ue-root to verify Engine/Extras/Redist installers.",
            evidence=[],
            actions=[],
        )

    installer = None
    redist_root = ue_path / "Engine" / "Extras" / "Redist"
    found_type = None
    if redist_root.exists():
        for exe in redist_root.rglob("UEPrereqSetup_x64.exe"):
            installer = exe
            found_type = "UEPrereqSetup_x64.exe"
            break
        if installer is None:
            for exe in redist_root.rglob("vc_redist.x64.exe"):
                installer = exe
                found_type = "vc_redist.x64.exe"
                break
        if installer is None:
            for exe in redist_root.rglob("vc_redist.arm64.exe"):
                installer = exe
                found_type = "vc_redist.arm64.exe"
                break

    installed_versions = _detect_installed_redist()
    exists = installer is not None and installer.exists()
    status = CheckStatus.PASS if exists else CheckStatus.WARN
    actions = []
    if not exists:
        actions.append(
            ActionRecommendation(
                id="ue.run-setup",
                description="Run Setup.bat to download UE prerequisites",
                commands=[f'"{ue_path / "Setup.bat"}"'],
            )
        )
    elif exists and not installed_versions:
        actions.append(
            ActionRecommendation(
                id="ue.run-prereqs",
                description="Run UEPrereqSetup_x64.exe or vc_redist.x64.exe silently via --run-prereqs.",
                commands=["uecfg setup --run-prereqs --apply"],
            )
        )
    details = ""
    if installer:
        details = str(installer)
        if found_type == "vc_redist.x64.exe":
            details += " (UEPrereqSetup_x64.exe absent; fallback redistributable found)"
        elif found_type == "vc_redist.arm64.exe":
            details += " (arm64 redistributable only)"
    else:
        details = f"No prerequisites found under {redist_root}"
    if installed_versions:
        details += f" | Installed VC++ redist: {', '.join(installed_versions)}"
        if exists:
            status = CheckStatus.PASS
    elif exists and not installed_versions:
        status = CheckStatus.WARN

    return CheckResult(
        id="ue.redist",
        phase=2,
        status=status,
        summary="UE prerequisites installer located" if exists else "UE prerequisites missing",
        details=details,
        evidence=[str(installer)] if installer else [str(redist_root)],
        actions=actions,
    )


def _detect_installed_redist() -> List[str]:
    """Detect installed VC++ 2015-2022 redistributables via registry."""
    versions: List[str] = []
    if winreg is None:
        return versions

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    target_names = (
        "Microsoft Visual C++ 2015-2022 Redistributable (x64)",
        "Microsoft Visual C++ 2015-2022 Redistributable (Arm64)",
    )

    for hive, key_path in hives:
        try:
            with winreg.OpenKey(hive, key_path) as root:
                for i in range(0, winreg.QueryInfoKey(root)[0]):
                    try:
                        subkey_name = winreg.EnumKey(root, i)
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            if display_name not in target_names:
                                continue
                            display_version, _ = winreg.QueryValueEx(subkey, "DisplayVersion")
                            versions.append(str(display_version))
                    except FileNotFoundError:
                        continue
                    except OSError:
                        continue
        except FileNotFoundError:
            continue
    return versions


def check_build_commands(ctx: ProbeContext) -> CheckResult:
    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.commands",
            phase=2,
            status=CheckStatus.SKIP,
            summary="Build command guidance skipped",
            details="Provide --ue-root to receive tailored Build.bat / editor commands.",
            evidence=[],
            actions=[],
        )

    build_bat = ue_path / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    uat = ue_path / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    commands = [
        f'"{build_bat}" UE5Editor Win64 Development -TargetType=Editor',
        f'"{uat}" BuildGraph -Target="Make Installed Build Win64" -Script="{ue_path / "Engine" / "Build" / "InstalledEngineBuild.xml"}"',
    ]
    return CheckResult(
        id="ue.commands",
        phase=2,
        status=CheckStatus.PASS,
        summary="Recommended UE build commands prepared",
        details="; ".join(commands),
        evidence=commands,
        actions=[
            ActionRecommendation(
                id="ue.build",
                description="Build the UE editor (Development, Win64)",
                commands=[commands[0]],
            )
        ],
        )


def check_engine_build(ctx: ProbeContext) -> CheckResult:
    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.engine-build",
            phase=2,
            status=CheckStatus.SKIP,
            summary="Engine Build Completeness: SKIP",
            details="Provide --ue-root to verify UnrealEditor/ShaderCompileWorker/UnrealPak/CrashReportClient binaries.",
            evidence=[],
            actions=[],
        )

    targets_override = ctx.cache.get("engine_build_targets")
    resolver = ArtifactResolver(ue_path)
    plan = determine_build_plan(ue_path, targets_override, resolver=resolver)
    missing = missing_targets(plan)
    status = CheckStatus.PASS if not missing else CheckStatus.WARN
    summary = f"Engine Build Completeness: {status.value}"
    details = summarize_plan(plan)
    actions: list[ActionRecommendation] = []
    if missing:
        missing_list = ", ".join(item.target.name for item in missing)
        details = f"Missing: {missing_list} | {details}"
        actions.append(
            ActionRecommendation(
                id="ue.build-engine",
                description="Build missing engine binaries via Build.bat",
                commands=[f'uecfg setup --apply --build-engine --ue-root "{ue_path}"'],
            )
        )

    evidence = [str(item.resolved or item.canonical) for item in plan]
    return CheckResult(
        id="ue.engine-build",
        phase=2,
        status=status,
        summary=summary,
        details=details,
        evidence=evidence,
        actions=actions,
    )


def _parse_build_configuration_flags(xml_text: str) -> Dict[str, bool]:
    """Backward-compatible wrapper that retains the probe contract."""

    all_flags = parse_build_configuration_flags(xml_text)
    filtered: Dict[str, bool] = {}
    for key in ("bAllowXGE", "bAllowRemoteBuilds", "bUseHordeAgent", "bAllowXGEShaderCompile"):
        if key in all_flags:
            filtered[key] = all_flags[key]
    return filtered


@dataclass
class BuildConfigurationInspection:
    path: Optional[Path]
    flags: Dict[str, bool]
    status: str
    details: str


def inspect_build_configuration(ue_root: Path | None) -> BuildConfigurationInspection:
    paths: List[Path] = [config_paths.user_build_configuration_path()]
    if ue_root:
        paths.append(config_paths.engine_build_configuration_path(ue_root))
    for path in paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return BuildConfigurationInspection(path=path, flags={}, status="unreadable", details="Unreadable file.")
        flags = _parse_build_configuration_flags(text)
        if not flags:
            return BuildConfigurationInspection(
                path=path,
                flags=flags,
                status="no-flags",
                details=f"{path}: no relevant flags",
            )
        enabled = any(flags.values())
        status = "enabled" if enabled else "disabled"
        detail_flags = ", ".join(f"{k}={v}" for k, v in sorted(flags.items()))
        return BuildConfigurationInspection(
            path=path,
            flags=flags,
            status=status,
            details=f"{path}: {detail_flags}",
        )
    return BuildConfigurationInspection(path=None, flags={}, status="missing", details="No BuildConfiguration.xml found.")


def check_shader_distribution(ctx: ProbeContext) -> CheckResult:
    """Report whether distributed shader compilation is configured."""

    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.shader-distribution",
            phase=2,
            status=CheckStatus.SKIP,
            summary="Shader distribution detection skipped",
            details="Provide --ue-root to inspect BuildConfiguration.xml for XGE/Horde flags.",
            evidence=[],
            actions=[],
        )

    inspection = inspect_build_configuration(ue_path)
    if inspection.status == "missing":
        return CheckResult(
            id="ue.shader-distribution",
            phase=2,
            status=CheckStatus.WARN,
            summary="Distributed shader compile not detected",
            details="No BuildConfiguration.xml found under common locations. ShaderCompileWorker likely runs locally.",
            evidence=[str(ue_path)],
            actions=[
                ActionRecommendation(
                    id="horde.template",
                    description="Generate a starter BuildConfiguration.xml that enables Horde/UBT distribution",
                    commands=["uecfg fix --phase 3 --apply"],
                )
            ],
        )
    if inspection.status == "unreadable":
        return CheckResult(
            id="ue.shader-distribution",
            phase=2,
            status=CheckStatus.WARN,
            summary="Distributed shader compile: unreadable config",
            details=inspection.details,
            evidence=[inspection.details],
            actions=[],
        )

    distributed = inspection.status == "enabled"
    status = CheckStatus.PASS if distributed else CheckStatus.WARN
    if inspection.status == "no-flags":
        summary = "Distributed shader compile: no relevant flags"
    elif inspection.status == "disabled":
        summary = "Distributed shader compile: present but disabled"
    else:
        summary = "Distributed shader compile: enabled"
    details = inspection.details
    return CheckResult(
        id="ue.shader-distribution",
        phase=2,
        status=status,
        summary=summary,
        details=details,
        evidence=[details],
        actions=[],
    )


def _extract_paths_from_text(text: str) -> List[str]:
    paths: List[str] = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not any(token in key for token in ("DerivedData", "Cache")) and not any(
            token in raw_value for token in ("DerivedData", "Cache")
        ):
            continue
        # Pull out Path= tokens inside structured config blobs
        candidates: List[str] = []
        for token in raw_value.split(","):
            token = token.strip()
            if "DerivedData" not in token and "Cache" not in token and not token.startswith("Path="):
                continue
            if token.startswith("Path="):
                value = token.split("=", 1)[1]
            else:
                value = token
            value = value.strip().strip('"').strip("'")
            if value:
                candidates.append(value)
        if not candidates and raw_value.strip():
            candidates.append(raw_value.strip().strip('"').strip("'"))
        paths.extend(candidates)
    return paths


def _classify_ddc_path(path_text: str, ue_path: Path | None, default_local: Path | None) -> str:
    lower = path_text.lower()
    if not path_text:
        return "unknown"
    if lower.startswith("\\\\") or "://" in lower:
        return "shared"
    path_obj = Path(path_text)
    try:
        resolved = path_obj.expanduser()
    except Exception:
        resolved = path_obj
    if default_local:
        try:
            if resolved.resolve().is_relative_to(default_local):
                return "local"
        except Exception:
            if str(default_local).lower() in lower:
                return "local"
    if ue_path:
        try:
            if resolved.resolve().is_relative_to(ue_path):
                return "local"
        except Exception:
            if str(ue_path).lower() in lower:
                return "local"
    if str(Path.home()).lower() in lower:
        return "local"
    if resolved.is_absolute():
        return "shared"
    return "unknown"


def check_ddc_configuration(ctx: ProbeContext) -> CheckResult:
    """Detect shared vs local Derived Data Cache usage."""

    ue_path: Path | None = ctx.cache.get("ue_root_path")
    if ue_path is None:
        return CheckResult(
            id="ue.ddc",
            phase=2,
            status=CheckStatus.SKIP,
            summary="DDC detection skipped",
            details="Provide --ue-root to inspect Derived Data Cache configuration.",
            evidence=[],
            actions=[],
        )

    local_default = None
    if os.environ.get("LOCALAPPDATA"):
        local_default = Path(os.environ["LOCALAPPDATA"]) / "UnrealEngine" / "Common" / "DerivedDataCache"

    env_local = os.environ.get("UE-LocalDataCachePath")
    env_shared = os.environ.get("UE-SharedDataCachePathOverride") or os.environ.get("UE-SharedDataCachePath")

    configs = [
        ue_path / "Engine" / "Config" / "DefaultEngine.ini",
        ue_path / "Engine" / "Config" / "BaseEngine.ini",
        ue_path / "Engine" / "Saved" / "Config" / "Windows" / "Engine.ini",
        ue_path / "Engine" / "Programs" / "UnrealBuildTool" / "Config" / "UnrealBuildTool.ini",
        ue_path / "Engine" / "Config" / "DerivedDataCache.ini",
        config_paths.user_ddc_config_path(),
    ]

    discovered_paths: List[str] = []
    for cfg in configs:
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        discovered_paths.extend(_extract_paths_from_text(text))

    if env_local:
        discovered_paths.append(env_local)
    if env_shared:
        discovered_paths.append(env_shared)

    local_paths: List[str] = []
    shared_paths: List[str] = []
    unknown_paths: List[str] = []
    for path_text in discovered_paths:
        classification = _classify_ddc_path(path_text, ue_path, local_default)
        if classification == "local":
            local_paths.append(path_text)
        elif classification == "shared":
            shared_paths.append(path_text)
        else:
            unknown_paths.append(path_text)

    evidence = []
    if local_default:
        evidence.append(f"Local default: {local_default}")
    if env_local:
        evidence.append(f"Env UE-LocalDataCachePath={env_local}")
    if env_shared:
        evidence.append(f"Env UE-SharedDataCachePath={env_shared}")
    evidence.extend(discovered_paths)

    if shared_paths:
        status = CheckStatus.PASS
        summary = "DDC: shared cache configured"
        details = f"Shared: {', '.join(dict.fromkeys(shared_paths))}"
        if local_paths:
            details += f" | Local fallback: {', '.join(dict.fromkeys(local_paths))}"
    elif unknown_paths:
        status = CheckStatus.WARN
        summary = "DDC: unable to confirm shared cache"
        details = f"Paths found but classification uncertain: {', '.join(dict.fromkeys(unknown_paths))}"
    elif local_paths:
        status = CheckStatus.WARN
        summary = "DDC: local-only"
        details = f"Local cache in use: {', '.join(dict.fromkeys(local_paths))}"
    else:
        status = CheckStatus.WARN
        summary = "DDC: configuration not found"
        details = "No Derived Data Cache paths detected in engine configs or environment."

    return CheckResult(
        id="ue.ddc",
        phase=2,
        status=status,
        summary=summary,
        details=details,
        evidence=evidence,
        actions=[],
    )


PHASE2_PROBES = [
    check_ue_root,
    check_setup_scripts,
    check_redist_installer,
    check_engine_build,
    check_build_commands,
    check_shader_distribution,
    check_ddc_configuration,
]
