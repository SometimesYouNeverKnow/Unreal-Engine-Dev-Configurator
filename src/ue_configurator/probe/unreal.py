"""Phase 2 probes for Unreal Engine prerequisites."""

from __future__ import annotations

from pathlib import Path
from typing import List

try:  # pragma: no cover - Windows only
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext
from ue_configurator.ue.build_targets import determine_build_plan, missing_targets, summarize_plan


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
    plan = determine_build_plan(ue_path, targets_override)
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

    evidence = [str(item.binary) for item in plan]
    return CheckResult(
        id="ue.engine-build",
        phase=2,
        status=status,
        summary=summary,
        details=details,
        evidence=evidence,
        actions=actions,
    )


PHASE2_PROBES = [
    check_ue_root,
    check_setup_scripts,
    check_redist_installer,
    check_engine_build,
    check_build_commands,
]
