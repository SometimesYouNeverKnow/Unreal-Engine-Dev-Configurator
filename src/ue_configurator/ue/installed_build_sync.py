"""Deterministic publish/pull workflow for Unreal Installed Builds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from ue_configurator.ue.build_config import apply_build_configuration_update, plan_build_configuration_update
from ue_configurator.ue.config_paths import user_build_configuration_path


KEY_FILES: Tuple[str, ...] = (
    r"Engine\Binaries\Win64\UnrealEditor.exe",
    r"Engine\Binaries\Win64\ShaderCompileWorker.exe",
    r"Engine\Binaries\Win64\UnrealPak.exe",
    r"Engine\Binaries\Win64\CrashReportClient.exe",
    r"Engine\Build\Build.version",
)

DEFAULT_DISTRIBUTED_FLAGS: Dict[str, bool] = {
    "bAllowXGE": True,
    "bAllowRemoteBuilds": True,
    "bUseHordeAgent": True,
    "bAllowXGEShaderCompile": True,
}


@dataclass
class SyncResult:
    success: bool
    summary: str
    details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    changed_paths: List[Path] = field(default_factory=list)


def _git_commit(repo_path: Optional[Path]) -> str:
    if not repo_path:
        return ""
    if not repo_path.exists():
        return ""
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run_robocopy(source: Path, destination: Path, *, dry_run: bool, thread_count: int) -> Tuple[int, str]:
    cmd: List[str] = [
        "robocopy",
        str(source),
        str(destination),
        "/MIR",
        "/Z",
        f"/MT:{thread_count}",
        "/R:3",
        "/W:5",
        "/FFT",
        "/DCOPY:DAT",
        "/COPY:DAT",
        "/NP",
        "/NDL",
        "/NFL",
    ]
    if dry_run:
        cmd.append("/L")

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def _robocopy_ok(exit_code: int) -> bool:
    # Robocopy: codes < 8 are success / non-fatal.
    return exit_code < 8


def _write_json(path: Path, payload: Dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def publish_installed_build(
    *,
    source_installed_build_path: Path,
    publish_root_path: Path,
    build_id: str,
    unreal_source_path: Optional[Path],
    shared_ddc_path: Optional[str],
    engine_association_guid: Optional[str],
    thread_count: int,
    dry_run: bool,
) -> SyncResult:
    if not source_installed_build_path.exists():
        return SyncResult(False, f"Source path missing: {source_installed_build_path}")

    destination = publish_root_path / build_id
    info_path = destination / "BUILD_INFO.json"
    settings_path = destination / "BUILD_SETTINGS.json"
    details: List[str] = [
        f"source={source_installed_build_path}",
        f"destination={destination}",
        f"build_id={build_id}",
    ]

    publish_root_path.mkdir(parents=True, exist_ok=True) if not dry_run else None
    rc, output = _run_robocopy(source_installed_build_path, destination, dry_run=dry_run, thread_count=thread_count)
    details.append(f"robocopy_exit={rc}")
    if output.strip():
        details.append(output.strip())
    if not _robocopy_ok(rc):
        return SyncResult(False, "robocopy publish failed", details=details)

    key_hashes: Dict[str, str] = {}
    for rel in KEY_FILES:
        abs_path = source_installed_build_path / rel
        key_hashes[rel] = _sha256(abs_path) if abs_path.exists() else ""

    info_payload: Dict = {
        "build_id": build_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_installed_build_path": str(source_installed_build_path),
        "published_path": str(destination),
        "unreal_source_path": str(unreal_source_path) if unreal_source_path else "",
        "unreal_source_commit": _git_commit(unreal_source_path),
        "key_file_hashes": key_hashes,
    }
    settings_payload: Dict = {
        "build_id": build_id,
        "engine_association_guid": engine_association_guid or "",
        "shared_ddc_path": shared_ddc_path or "",
        "distributed_shader_flags": DEFAULT_DISTRIBUTED_FLAGS,
    }

    _write_json(info_path, info_payload, dry_run=dry_run)
    _write_json(settings_path, settings_payload, dry_run=dry_run)
    changed = [info_path, settings_path] if not dry_run else []
    return SyncResult(True, "Publish completed", details=details, changed_paths=changed)


def _set_user_env_var(name: str, value: str, *, dry_run: bool) -> Optional[str]:
    if dry_run:
        return f"[dry-run] Would set user env {name}={value}"
    # Persist user env var for next shells/processes.
    os.environ[name] = value
    try:
        import winreg  # type: ignore
    except ImportError:
        return "winreg unavailable; user env var persisted for current process only."

    reg_path = r"Environment"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
    return None


def _set_engine_association(guid: str, destination: Path, *, dry_run: bool) -> Optional[str]:
    if not guid:
        return None
    if dry_run:
        return f"[dry-run] Would map EngineAssociation {guid} -> {destination}"
    try:
        import winreg  # type: ignore
    except ImportError:
        return "winreg unavailable; cannot set EngineAssociation."
    reg_path = r"Software\Epic Games\Unreal Engine\Builds"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
        winreg.SetValueEx(key, guid, 0, winreg.REG_SZ, str(destination))
    return None


def pull_installed_build(
    *,
    publish_root_path: Path,
    build_id: str,
    destination_installed_build_path: Path,
    thread_count: int,
    dry_run: bool,
    install_settings: bool,
    apply_engine_association: bool,
) -> SyncResult:
    source = publish_root_path / build_id
    info_path = source / "BUILD_INFO.json"
    settings_path = source / "BUILD_SETTINGS.json"

    if not source.exists():
        return SyncResult(False, f"Published source missing: {source}")
    if not info_path.exists():
        return SyncResult(False, f"BUILD_INFO.json missing: {info_path}")
    if not settings_path.exists():
        return SyncResult(False, f"BUILD_SETTINGS.json missing: {settings_path}")

    details: List[str] = [
        f"source={source}",
        f"destination={destination_installed_build_path}",
        f"build_id={build_id}",
    ]

    destination_installed_build_path.mkdir(parents=True, exist_ok=True) if not dry_run else None
    rc, output = _run_robocopy(source, destination_installed_build_path, dry_run=dry_run, thread_count=thread_count)
    details.append(f"robocopy_exit={rc}")
    if output.strip():
        details.append(output.strip())
    if not _robocopy_ok(rc):
        return SyncResult(False, "robocopy pull failed", details=details)

    info = _load_json(info_path)
    if str(info.get("build_id", "")) != build_id:
        return SyncResult(False, f"Manifest build_id mismatch in {info_path}")

    hash_mismatches: List[str] = []
    key_hashes = info.get("key_file_hashes", {})
    if isinstance(key_hashes, dict) and not dry_run:
        for rel, expected in key_hashes.items():
            if not expected:
                continue
            candidate = destination_installed_build_path / rel
            if not candidate.exists():
                hash_mismatches.append(f"{rel}: missing")
                continue
            actual = _sha256(candidate)
            if actual != expected:
                hash_mismatches.append(f"{rel}: expected={expected} actual={actual}")
    if hash_mismatches:
        return SyncResult(False, "Hash verification failed", details=details + hash_mismatches)

    warnings: List[str] = []
    changed: List[Path] = []
    if install_settings:
        settings = _load_json(settings_path)
        user_settings_path = Path.home() / "Documents" / "uecfg" / f"{build_id}.settings.json"
        _write_json(user_settings_path, settings, dry_run=dry_run)
        if not dry_run:
            changed.append(user_settings_path)

        shared_ddc = str(settings.get("shared_ddc_path", "")).strip()
        if shared_ddc:
            warn = _set_user_env_var("UE-SharedDataCachePath", shared_ddc, dry_run=dry_run)
            if warn:
                warnings.append(warn)

        flags = settings.get("distributed_shader_flags", {})
        if isinstance(flags, dict):
            normalized = {str(k): bool(v) for k, v in flags.items()}
            plan = plan_build_configuration_update(
                user_build_configuration_path(),
                normalized,
                valid_keys=normalized.keys(),
            )
            apply_build_configuration_update(plan, dry_run=dry_run)
            if plan.path and not dry_run:
                changed.append(plan.path)
            warnings.extend(plan.warnings)

        if apply_engine_association:
            guid = str(settings.get("engine_association_guid", "")).strip()
            warn = _set_engine_association(guid, destination_installed_build_path, dry_run=dry_run)
            if warn:
                warnings.append(warn)

    return SyncResult(
        True,
        "Pull completed",
        details=details,
        warnings=warnings,
        changed_paths=changed,
    )
