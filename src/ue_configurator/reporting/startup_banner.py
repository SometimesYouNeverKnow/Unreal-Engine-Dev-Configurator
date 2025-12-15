from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from ue_configurator import __version__
from ue_configurator.manifest import Manifest
from ue_configurator.profile import Profile
from ue_configurator.probe.base import ProbeContext
from ue_configurator.setup.pipeline import SetupRuntime


def _manifest_summary(manifest: Optional[Manifest], manifest_source: Optional[str]) -> str:
    if not manifest:
        return "None"
    path = Path(manifest_source) if manifest_source else None
    return f"{manifest.id} (UE {manifest.ue_version}) fingerprint {manifest.fingerprint[:12]} @ {path or 'resolved'}"


def format_startup_banner(
    context: ProbeContext,
    *,
    command: str,
    phases: List[int],
    apply: bool,
    json_path: Optional[str],
    log_path: Optional[str],
    manifest: Optional[Manifest],
    manifest_source: Optional[str],
    ue_root: Optional[str],
    profile: Profile,
    requires_admin: bool = False,
    plan_steps: Optional[int] = None,
    build_engine: bool = False,
    build_targets: Optional[Sequence[str]] = None,
) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    host = socket.gethostname()
    lines = []
    lines.append("=" * 60)
    lines.append(f"UE Dev Configurator {__version__} — {command.upper()}  [{host} @ {now}]")
    lines.append(f"Profile: {profile.value} | Phases: {', '.join(str(p) for p in phases) or 'n/a'} | Mode: {'apply' if apply else 'dry-run/plan'}")
    if requires_admin:
        lines.append("NOTE: Some steps may require administrator rights.")
    lines.append(f"Manifest: {_manifest_summary(manifest, manifest_source)}")
    if ue_root:
        lines.append(f"UE root: {ue_root}")
    if plan_steps is not None:
        lines.append(f"Plan: {plan_steps} steps (overview below)")
    if log_path:
        lines.append(f"Log: {Path(log_path).resolve()}")
    if json_path:
        lines.append(f"JSON report: {Path(json_path).resolve()}")
    if build_engine:
        targets = ", ".join(build_targets) if build_targets else "UnrealEditor, ShaderCompileWorker, UnrealPak, CrashReportClient"
        lines.append(f"Engine build: enabled (--build-engine); targets: {targets}")
    lines.append("What happens: readiness checks, manifest compliance, and guidance. Cancel anytime; rerun is safe.")
    lines.append("Tips: use --help for options; add --verbose for more detail; --run-prereqs to execute redistributables.")
    lines.append("=" * 60)
    return "\n".join(lines)


def format_minimal_banner(
    command: str,
    json_path: Optional[str],
    log_path: Optional[str],
    ue_root: Optional[str],
) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    host = socket.gethostname()
    lines = []
    lines.append("=" * 60)
    lines.append(f"UE Dev Configurator {__version__} — {command.upper()}  [{host} @ {now}]")
    if ue_root:
        lines.append(f"UE root: {ue_root}")
    if log_path:
        lines.append(f"Log: {Path(log_path).resolve()}")
    if json_path:
        lines.append(f"JSON report: {Path(json_path).resolve()}")
    lines.append("Preparing to resolve manifest/profile... You can cancel anytime.")
    lines.append("=" * 60)
    return "\n".join(lines)


def print_startup_banner_for_runtime(runtime: SetupRuntime, command: str, plan_steps: Optional[int] = None) -> None:
    banner = format_startup_banner(
        runtime.context,
        command=command,
        phases=runtime.options.phases,
        apply=runtime.options.apply,
        json_path=runtime.options.json_path,
        log_path=str(runtime.options.log_path) if runtime.options.log_path else None,
        manifest=runtime.options.manifest,
        manifest_source=runtime.options.manifest_source,
        ue_root=runtime.options.ue_root,
        profile=runtime.options.profile,
        requires_admin=False,
        plan_steps=plan_steps,
        build_engine=runtime.options.build_engine,
        build_targets=runtime.options.build_targets,
    )
    print(banner)
