"""Phase 2 probes for Unreal Engine prerequisites."""

from __future__ import annotations

from pathlib import Path
from typing import List

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext


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
    if redist_root.exists():
        for exe in redist_root.rglob("UEPrereqSetup_x64.exe"):
            installer = exe
            break

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
    return CheckResult(
        id="ue.redist",
        phase=2,
        status=status,
        summary="UE prerequisites installer located" if exists else "UE prerequisites missing",
        details=str(installer) if installer else str(redist_root / "UEPrereqSetup_x64.exe"),
        evidence=[str(installer)] if installer else [str(redist_root)],
        actions=actions,
    )


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


PHASE2_PROBES = [
    check_ue_root,
    check_setup_scripts,
    check_redist_installer,
    check_build_commands,
]
