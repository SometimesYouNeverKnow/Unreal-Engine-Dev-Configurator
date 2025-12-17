"""Phase 3 probes for Horde agent / Unreal Build Accelerator readiness."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext
from ue_configurator.ue.horde_agent_config import discover_horde_agent_configs, load_horde_agent_config, HordeAgentConfig


@dataclass
class HordeAgentStatus:
    installed: bool
    running: bool
    service_state: str
    details: str


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


def probe_horde_agent_status(ctx: ProbeContext) -> HordeAgentStatus:
    result = ctx.run_command(["sc", "query", "HordeAgent"], timeout=5)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    output_upper = output.upper()
    installed = "SERVICE_NAME" in output_upper or "STATE" in output_upper
    running = "RUNNING" in output_upper
    if "1060" in output_upper or "DOES NOT EXIST" in output_upper:
        installed = False
        running = False
    state = "unknown"
    for line in output.splitlines():
        if "STATE" in line.upper():
            state = line.split(":", 1)[-1].strip()
            break
    details = output or "Service query failed."
    return HordeAgentStatus(installed=installed, running=running, service_state=state, details=details)


def check_horde_agent(ctx: ProbeContext) -> CheckResult:
    status_info = probe_horde_agent_status(ctx)
    installed = status_info.installed
    running = status_info.running
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
    if running:
        summary = "Horde agent running"
    elif installed:
        summary = "Horde agent installed but not running"
    else:
        summary = "Horde agent not found"

    return CheckResult(
        id="horde.agent",
        phase=3,
        status=status,
        summary=summary,
        details=status_info.details,
        evidence=[status_info.details[:200]],
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


def discover_agent_config() -> Optional[HordeAgentConfig]:
    configs = discover_horde_agent_configs()
    parsed: List[HordeAgentConfig] = []
    for path in configs:
        config = load_horde_agent_config(path)
        parsed.append(config)
        if config.parsed and (config.endpoint or config.pool):
            return config
    return parsed[0] if parsed else None


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
