"""Phase 3 probes for Horde agent / Unreal Build Accelerator readiness."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import List

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext


def check_network_readiness(ctx: ProbeContext) -> CheckResult:
    target = ("8.8.8.8", 443)
    try:
        with socket.create_connection(target, timeout=2):
            reachable = True
    except OSError:
        reachable = False
    status = CheckStatus.PASS if reachable else CheckStatus.WARN
    details = "Outbound TCP/443 reachable" if reachable else "Could not verify outbound TCP/443 connectivity."
    return CheckResult(
        id="horde.network",
        phase=3,
        status=status,
        summary="Network ready" if reachable else "Outbound network uncertain",
        details=details,
        evidence=[str(target)],
        actions=[
            ActionRecommendation(
                id="network.test",
                description="Validate that VPN/firewall allows Horde endpoints",
                commands=["Test-NetConnection -ComputerName horde.epicgames.net -Port 443"],
            )
        ]
        if not reachable
        else [],
    )


def check_horde_agent(ctx: ProbeContext) -> CheckResult:
    result = ctx.run_command(["sc", "query", "HordeAgent"], timeout=5)
    installed = "STATE" in result.stdout
    running = "RUNNING" in result.stdout.upper()
    status = CheckStatus.PASS if running else CheckStatus.WARN
    actions = []
    if not installed:
        actions.append(
            ActionRecommendation(
                id="horde.install",
                description="Install the Horde agent from Epic's internal distribution",
                commands=["<download HordeAgentInstaller.exe>", "Start-Process -Wait .\\HordeAgentInstaller.exe"],
            )
        )
    elif not running:
        actions.append(
            ActionRecommendation(
                id="horde.start",
                description="Start the Horde agent service",
                commands=["sc start HordeAgent"],
            )
        )
    summary = "Horde agent running" if running else "Horde agent service not running"
    if not installed:
        summary = "Horde agent not found"

    return CheckResult(
        id="horde.agent",
        phase=3,
        status=status,
        summary=summary,
        details=result.stdout.strip() or result.stderr.strip() or "Service query failed.",
        evidence=[result.stdout[:200]],
        actions=actions,
    )


def _find_build_configs(ctx: ProbeContext) -> List[Path]:
    search_roots = [
        Path.home() / "Documents" / "Unreal Engine",
        Path.home() / "AppData" / "Roaming" / "Unreal Engine",
    ]
    ue_path = ctx.cache.get("ue_root_path")
    if ue_path:
        search_roots.append(ue_path / "Engine" / "Programs")
    results: List[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("BuildConfiguration.xml"):
            results.append(path)
    return results


def check_build_configuration(ctx: ProbeContext) -> CheckResult:
    configs = _find_build_configs(ctx)
    status = CheckStatus.PASS if configs else CheckStatus.WARN
    actions = []
    if not configs:
        actions.append(
            ActionRecommendation(
                id="horde.template",
                description="Generate a starter BuildConfiguration.xml via uecfg fix --phase 3 --apply",
                commands=["uecfg fix --phase 3 --apply"],
            )
        )
    return CheckResult(
        id="horde.build-config",
        phase=3,
        status=status,
        summary="BuildConfiguration.xml discovered" if configs else "No BuildConfiguration.xml found",
        details="; ".join(str(cfg) for cfg in configs) if configs else "UE build config file missing.",
        evidence=[str(cfg) for cfg in configs],
        actions=actions,
    )


PHASE3_PROBES = [
    check_network_readiness,
    check_horde_agent,
    check_build_configuration,
]
