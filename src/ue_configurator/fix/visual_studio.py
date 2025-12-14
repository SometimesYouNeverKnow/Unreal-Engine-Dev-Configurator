"""Automations for ensuring Visual Studio matches the UE manifest requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import List, Optional

from ue_configurator.manifest import Manifest
from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.toolchain import VSInstance, compare_versions, get_vs_instances, parse_vs_version


VS_INSTALLER_PATH = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "setup.exe"
GENERATED_DIR = Path("manifests") / "generated"


@dataclass
class VSModifyPlan:
    required: bool
    reason: str = ""
    instance: Optional[VSInstance] = None
    missing_components: List[str] = field(default_factory=list)


@dataclass
class VSModifyOutcome:
    success: bool
    message: str
    logs: List[str] = field(default_factory=list)
    blocked: bool = False


def find_vs_installer_setup_exe() -> Optional[Path]:
    if VS_INSTALLER_PATH.is_file():
        return VS_INSTALLER_PATH
    return None


def plan_vs_modify(ctx: ProbeContext, manifest: Optional[Manifest]) -> VSModifyPlan:
    if manifest is None:
        return VSModifyPlan(required=False, reason="No manifest selected.")
    instances = get_vs_instances(ctx)
    if not instances:
        return VSModifyPlan(required=False, reason="Visual Studio not installed.")
    vs_req = manifest.visual_studio
    candidates: List[tuple[VSInstance, tuple[int, ...], List[str]]] = []
    min_version = parse_vs_version(vs_req.min_build or "0")
    max_version = parse_vs_version(vs_req.max_build or "999.0.0.0") if vs_req.max_build else None
    for inst in instances:
        version_tuple = parse_vs_version(inst.version)
        if not version_tuple:
            continue
        if version_tuple[0] != vs_req.required_major:
            continue
        if vs_req.min_build and compare_versions(version_tuple, min_version) < 0:
            continue
        if max_version and compare_versions(version_tuple, max_version) > 0:
            continue
        missing = _missing_components(vs_req.requires_components, inst.packages)
        candidates.append((inst, version_tuple, missing))
    if not candidates:
        return VSModifyPlan(
            required=False,
            reason="No Visual Studio instance matches manifest major/build requirements.",
        )
    candidates.sort(key=lambda item: item[1], reverse=True)
    best_inst, _, missing_components = candidates[0]
    if not missing_components:
        return VSModifyPlan(required=False, reason="Visual Studio already satisfies manifest components.")
    return VSModifyPlan(
        required=True,
        reason="Missing Visual Studio workloads/components.",
        instance=best_inst,
        missing_components=missing_components,
    )


def ensure_vs_manifest_components(
    ctx: ProbeContext,
    manifest: Optional[Manifest],
    *,
    vs_passive: bool = True,
    dry_run: bool = False,
    logger: Optional[object] = None,
) -> VSModifyOutcome:
    plan = plan_vs_modify(ctx, manifest)
    if not plan.required:
        return VSModifyOutcome(success=True, message=plan.reason or "Visual Studio already compliant.")
    setup_exe = find_vs_installer_setup_exe()
    if setup_exe is None:
        message = "Visual Studio Installer (setup.exe) not found under Program Files (x86)."
        return VSModifyOutcome(success=False, blocked=True, message=message, logs=[message])
    vsconfig_path = generate_vsconfig(manifest)
    install_path = plan.instance.installation_path if plan.instance else None
    if not install_path:
        return VSModifyOutcome(success=False, blocked=True, message="Unable to identify a Visual Studio install path.")
    outcome = modify_vs_install(
        install_path=install_path,
        setup_exe=setup_exe,
        vsconfig_path=vsconfig_path,
        vs_passive=vs_passive,
        dry_run=dry_run,
        logger=logger,
    )
    if outcome.success:
        outcome.message = "Visual Studio components updated to match manifest."
    return outcome


def generate_vsconfig(manifest: Manifest) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{manifest.id}_{manifest.fingerprint}.vsconfig"
    target = GENERATED_DIR / filename
    workloads: List[str] = []
    components: List[str] = []
    for item in manifest.visual_studio.requires_components:
        slug = item.strip()
        if not slug:
            continue
        if ".Workload." in slug:
            workloads.append(slug)
        else:
            components.append(slug)
    config = {
        "version": "1.0",
        "components": sorted(set(components)),
        "workloads": sorted(set(workloads)),
    }
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return target


def modify_vs_install(
    *,
    install_path: Path,
    setup_exe: Path,
    vsconfig_path: Path,
    vs_passive: bool,
    dry_run: bool,
    logger: Optional[object] = None,
) -> VSModifyOutcome:
    cmd = [
        str(setup_exe),
        "modify",
        "--installPath",
        str(install_path),
        "--config",
        str(vsconfig_path),
        "--norestart",
        "--wait",
    ]
    if vs_passive:
        cmd.append("--passive")
    log_lines = [f"[vs-installer] {' '.join(cmd)}"]
    _emit(logger, log_lines[-1])
    if dry_run:
        return VSModifyOutcome(success=True, message="[dry-run] Visual Studio modify skipped.", logs=log_lines)
    workdir = Path(tempfile.mkdtemp(prefix="uecfg_vs_installer_"))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            log_lines.append(result.stdout.strip())
            _emit(logger, result.stdout.strip())
        if result.stderr:
            log_lines.append(result.stderr.strip())
            _emit(logger, result.stderr.strip())
        if result.returncode != 0:
            message = f"Visual Studio Installer exited with {result.returncode}."
            return VSModifyOutcome(success=False, message=message, logs=log_lines)
        return VSModifyOutcome(success=True, message="Visual Studio Installer completed.", logs=log_lines)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _missing_components(required: List[str], installed: List[str]) -> List[str]:
    installed_set = {item.lower() for item in installed}
    missing: List[str] = []
    for item in required:
        slug = item.strip()
        if not slug:
            continue
        if slug.lower() not in installed_set:
            missing.append(slug)
    return missing


def _emit(logger: Optional[object], message: str) -> None:
    if not message:
        return
    if logger and hasattr(logger, "log"):
        logger.log(message)
