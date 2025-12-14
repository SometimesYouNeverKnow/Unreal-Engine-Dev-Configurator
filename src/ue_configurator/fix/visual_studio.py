"""Automations for ensuring Visual Studio matches the UE manifest requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional, Tuple

try:  # pragma: no cover - optional on non-Windows
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None

from ue_configurator.manifest import Manifest
from ue_configurator.manifest.manifest_types import WindowsSDKRequirement
from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.toolchain import (
    VSInstance,
    compare_versions,
    get_vs_instances,
    parse_vs_version,
)

VS_INSTALLER_PATH = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft Visual Studio"
    / "Installer"
    / "setup.exe"
)
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


@dataclass
class SDKResolution:
    satisfied: bool
    component_id: Optional[str]
    message: str
    candidates: List[str] = field(default_factory=list)


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
    min_version = parse_vs_version(vs_req.min_version or "0")
    for inst in instances:
        version_tuple = parse_vs_version(inst.version)
        if not version_tuple:
            continue
        if version_tuple[0] != vs_req.required_major:
            continue
        if vs_req.min_version and compare_versions(version_tuple, min_version) < 0:
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
    sdk_resolution = resolve_windows_sdk_component(manifest)
    if logger and sdk_resolution.message:
        logger.log(f"[setup] Windows SDK: {sdk_resolution.message}")
        if sdk_resolution.candidates:
            logger.log(f"[setup] SDK candidates: {', '.join(sdk_resolution.candidates)}")
    if not sdk_resolution.satisfied and sdk_resolution.component_id is None:
        message = (
            "Unable to satisfy Windows SDK requirement. "
            "Install the required Windows SDK via Visual Studio Installer or the standalone SDK package."
        )
        return VSModifyOutcome(success=False, message=message, logs=[message], blocked=True)
    extra_components: List[str] = []
    if sdk_resolution.component_id:
        extra_components.append(sdk_resolution.component_id)
    vsconfig_path = generate_vsconfig(manifest, extra_components=extra_components)
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


def generate_vsconfig(manifest: Manifest, extra_components: Optional[List[str]] = None) -> Path:
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
    if extra_components:
        components.extend(extra_components)
    config = {
        "version": "1.0",
        "components": sorted(set(components)),
        "workloads": sorted(set(workloads)),
    }
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    resolved = target.resolve()
    return resolved


def resolve_windows_sdk_component(
    manifest: Optional[Manifest], available_components: Optional[List[str]] = None
) -> SDKResolution:
    if manifest is None or manifest.windows_sdk is None:
        return SDKResolution(True, None, "No Windows SDK requirement specified.", [])

    requirement = manifest.windows_sdk
    min_version = requirement.minimum_version or requirement.preferred_version
    if not min_version:
        return SDKResolution(True, None, "Windows SDK minimum version not defined; skipping.", [])

    installed_versions = _list_installed_sdks()
    for installed in installed_versions:
        if _compare_sdk_versions(installed, min_version) >= 0:
            return SDKResolution(
                True,
                None,
                f"Installed Windows SDK {installed} satisfies >= {min_version}.",
                [],
            )

    candidates = _candidate_sdk_ids(requirement, min_version)
    if not candidates:
        message = (
            f"Unable to resolve Windows SDK component ID for minimum version {min_version}. "
            "Install the SDK manually via Visual Studio Individual Components."
        )
        return SDKResolution(False, None, message, [])
    component_id = None
    if available_components:
        for candidate in candidates:
            if candidate in available_components:
                component_id = candidate
                break
    if component_id is None:
        component_id = candidates[0]
    message = f"Will install Windows SDK (>= {min_version}) via {component_id}."
    return SDKResolution(False, component_id, message, candidates)


def modify_vs_install(
    *,
    install_path: Path,
    setup_exe: Path,
    vsconfig_path: Path,
    vs_passive: bool,
    dry_run: bool,
    logger: Optional[object] = None,
) -> VSModifyOutcome:
    vsconfig_path = vsconfig_path.resolve()
    if not vsconfig_path.exists():
        message = f"Visual Studio config file missing: {vsconfig_path}"
        return VSModifyOutcome(success=False, message=message, logs=[message], blocked=True)
    cmd = _build_installer_command(setup_exe, install_path, vsconfig_path, vs_passive)
    log_lines = [f"[vs-installer] Using config file: {vsconfig_path}"]
    log_lines.append(f"[vs-installer] {' '.join(cmd)}")
    _emit(logger, log_lines[-1])
    if dry_run:
        return VSModifyOutcome(success=True, message="[dry-run] Visual Studio modify skipped.", logs=log_lines)
    workdir = Path(tempfile.mkdtemp(prefix="uecfg_vs_installer_"))
    try:
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            message = f"Failed to launch Visual Studio Installer: {exc}"
            log_lines.append(message)
            _emit(logger, message)
            return VSModifyOutcome(success=False, message=message, logs=log_lines)

        log_lines.append(f"[vs-installer] PID {process.pid} started.")
        _emit(logger, log_lines[-1])
        start_monotonic = time.monotonic()
        start_wall = time.time()
        heartbeat_interval = 15.0
        next_heartbeat = start_monotonic + heartbeat_interval
        log_hint_reported = False

        while True:
            ret = process.poll()
            if ret is not None:
                break
            now = time.monotonic()
            if now >= next_heartbeat:
                elapsed = _format_duration(now - start_monotonic)
                msg = f"[vs-installer] running... elapsed {elapsed}"
                log_lines.append(msg)
                _emit(logger, msg)
                if not log_hint_reported:
                    hint = _discover_vs_log_hint(start_wall)
                    if hint:
                        hint_msg = f"[vs-installer] Installer logs: {hint}"
                        log_lines.append(hint_msg)
                        _emit(logger, hint_msg)
                        log_hint_reported = True
                next_heartbeat = now + heartbeat_interval
            time.sleep(5)

        stdout, stderr = process.communicate()
        usage_detected = False
        if stdout:
            stdout = stdout.strip()
            log_lines.append(stdout)
            _emit(logger, stdout)
            usage_detected = usage_detected or _detect_usage(stdout)
        if stderr:
            stderr = stderr.strip()
            log_lines.append(stderr)
            _emit(logger, stderr)
            usage_detected = usage_detected or _detect_usage(stderr)
        if usage_detected:
            message = "Visual Studio Installer returned usage/help output. Verify arguments or rerun with --vs-interactive."
            return VSModifyOutcome(success=False, message=message, logs=log_lines, blocked=True)
        if process.returncode != 0:
            message = f"Visual Studio Installer exited with {process.returncode}."
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


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _discover_vs_log_hint(since_epoch: float) -> Optional[str]:
    temp_dir = Path(tempfile.gettempdir())
    candidates = []
    for pattern in ("dd_setup_*.log", "dd_setup_*.log*"):
        candidates.extend(temp_dir.glob(pattern))
    latest_path: Optional[Path] = None
    latest_mtime = since_epoch
    for candidate in candidates:
        try:
            stat = candidate.stat()
        except OSError:
            continue
        if stat.st_mtime >= latest_mtime:
            latest_mtime = stat.st_mtime
            latest_path = candidate
    return str(latest_path) if latest_path else None


def _build_installer_command(
    setup_exe: Path, install_path: Path, vsconfig_path: Path, vs_passive: bool
) -> List[str]:
    cmd = [
        str(setup_exe),
        "modify",
        "--installPath",
        str(install_path),
        "--config",
        str(vsconfig_path),
    ]
    if vs_passive:
        cmd.extend(["--passive", "--norestart"])
    return cmd


def _detect_usage(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    tokens = [
        "usage: setup.exe",
        "--norestart requires either --quiet or --passive",
        "usage:",
    ]
    return any(token in lower for token in tokens)


def _list_installed_sdks() -> List[str]:
    versions: List[str] = []
    if winreg is None:
        return versions
    views = [0]
    if hasattr(winreg, "KEY_WOW64_32KEY"):
        views.append(getattr(winreg, "KEY_WOW64_32KEY"))
    for view in views:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0",
                access=winreg.KEY_READ | view,
            ) as key:
                product_version, _ = winreg.QueryValueEx(key, "ProductVersion")
                if product_version:
                    versions.append(str(product_version))
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return versions


def _candidate_sdk_ids(requirement: WindowsSDKRequirement, min_version: str) -> List[str]:
    builds: List[str] = []

    def add_version(text: Optional[str]) -> None:
        if not text:
            return
        build = _extract_sdk_build(text)
        if build and build not in builds:
            builds.append(build)

    add_version(requirement.preferred_version)
    for version in requirement.preferred_versions:
        add_version(version)
    add_version(min_version)

    fallback_builds = ["26100", "25398", "22621", "22000", "20348", "19041"]
    for build in fallback_builds:
        if build not in builds:
            builds.append(build)

    candidate_ids: List[str] = []
    for build in builds:
        candidate_ids.append(f"Microsoft.VisualStudio.Component.Windows11SDK.{build}")
        candidate_ids.append(f"Microsoft.VisualStudio.Component.Windows10SDK.{build}")
    return candidate_ids


def _extract_sdk_build(version: str) -> Optional[str]:
    parts = [part for part in version.split(".") if part]
    if len(parts) >= 3:
        return parts[2]
    if parts:
        return parts[-1]
    return None


def _parse_sdk_version(version: str) -> Tuple[int, ...]:
    parts = []
    for token in version.split("."):
        if not token:
            continue
        try:
            parts.append(int(token))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def _compare_sdk_versions(left: str, right: str) -> int:
    left_tuple = _parse_sdk_version(left)
    right_tuple = _parse_sdk_version(right)
    if left_tuple < right_tuple:
        return -1
    if left_tuple > right_tuple:
        return 1
    return 0
