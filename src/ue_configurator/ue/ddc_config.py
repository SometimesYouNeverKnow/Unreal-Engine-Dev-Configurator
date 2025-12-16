"""Shared Derived Data Cache configuration helpers."""

from __future__ import annotations

import datetime
import difflib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from ue_configurator.ue.config_paths import default_local_ddc_path


WriteProbe = Callable[[Path], float]


@dataclass
class DDCValidationResult:
    path: Path
    ok: bool
    created: bool
    latency_ms: Optional[float]
    message: str


def _timestamped_backup_path(path: Path) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_suffix(path.suffix + f".{stamp}.bak")


def _default_probe_write(path: Path) -> float:
    start = time.time()
    marker = path / f".uecfg_ddc_probe_{int(start * 1000)}"
    marker.write_text("ddc-probe", encoding="utf-8")
    marker.unlink(missing_ok=True)
    return (time.time() - start) * 1000


def validate_ddc_path(
    path: Path,
    *,
    allow_create: bool,
    dry_run: bool,
    write_probe: WriteProbe | None = None,
) -> DDCValidationResult:
    """Ensure the shared cache path exists and is writable."""

    path = path.expanduser()
    probe = write_probe or _default_probe_write
    created = False
    latency_ms: Optional[float] = None
    if not path.exists():
        if not allow_create:
            return DDCValidationResult(path, False, False, None, "Path does not exist.")
        if dry_run:
            return DDCValidationResult(path, True, True, None, "Would create directory (dry-run).")
        try:
            path.mkdir(parents=True, exist_ok=True)
            created = True
        except OSError as exc:
            return DDCValidationResult(path, False, False, None, f"Unable to create path: {exc}")
    try:
        if not dry_run:
            latency_ms = probe(path)
    except OSError as exc:
        return DDCValidationResult(path, False, created, None, f"Path is not writable: {exc}")
    return DDCValidationResult(path, True, created, latency_ms, "Ready")


@dataclass
class DDCSchema:
    shared_key: Optional[str]
    local_key: Optional[str]
    evidence: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.shared_key)


def scan_ddc_schema(ue_root: Path | None) -> DDCSchema:
    """Inspect UE config files to avoid guessing DDC keys."""

    candidates = ("SharedDataCachePath", "SharedCachePath")
    local_candidates = ("LocalDataCachePath", "LocalCachePath")
    evidence: List[Path] = []
    warnings: List[str] = []
    shared_key = None
    local_key = None
    search_files: List[Path] = []
    if ue_root:
        search_files.append(ue_root / "Engine" / "Config" / "BaseEngine.ini")
        search_files.append(ue_root / "Engine" / "Config" / "DefaultEngine.ini")
    search_files.append(Path.home() / "AppData" / "Roaming" / "Unreal Engine" / "Engine" / "DerivedDataCache.ini")

    for file in search_files:
        if not file.exists():
            continue
        evidence.append(file)
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key in candidates and shared_key is None:
                shared_key = key
            if key in local_candidates and local_key is None:
                local_key = key
    if shared_key is None:
        warnings.append("No known DDC keys found in UE config; skipping config writes.")
    return DDCSchema(shared_key=shared_key, local_key=local_key, evidence=evidence, warnings=warnings)


@dataclass
class DDCUpdate:
    path: Path
    before: Optional[str]
    after: Optional[str]
    backup: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.after is not None and self.after != (self.before or ""))

    def diff(self) -> str:
        before_lines = (self.before or "").splitlines(keepends=True)
        after_lines = (self.after or "").splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=str(self.path),
                tofile=f"{self.path} (proposed)",
                lineterm="",
            )
        )


def _render_ddc_ini(shared_path: str, local_path: Optional[str], schema: DDCSchema) -> str:
    lines = ["[DerivedDataCache]"]
    if schema.shared_key:
        lines.append(f"{schema.shared_key}={shared_path}")
    if schema.local_key and local_path:
        lines.append(f"{schema.local_key}={local_path}")
    return "\n".join(lines) + "\n"


def plan_ddc_update(
    path: Path,
    *,
    shared_path: str,
    local_path: Optional[str],
    schema: DDCSchema,
) -> DDCUpdate:
    """Build the proposed DerivedDataCache.ini content without writing."""

    before = None
    if path.exists():
        try:
            before = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return DDCUpdate(path=path, before=None, after=None, warnings=[f"Unable to read {path}: {exc}"])

    if not schema.shared_key:
        return DDCUpdate(path=path, before=before, after=None, warnings=list(schema.warnings))

    after = _render_ddc_ini(shared_path, local_path, schema)
    return DDCUpdate(path=path, before=before, after=after, warnings=list(schema.warnings))


def apply_ddc_update(update: DDCUpdate, *, dry_run: bool, backup: bool = True) -> DDCUpdate:
    if not update.after:
        return update

    path = update.path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not dry_run and path.exists() and backup:
        update.backup = _timestamped_backup_path(path)
        try:
            update.backup.write_text(update.before or "", encoding="utf-8")
        except OSError as exc:
            update.warnings.append(f"Failed to back up {path}: {exc}")
            update.backup = None

    if dry_run:
        return update

    try:
        path.write_text(update.after, encoding="utf-8")
    except OSError as exc:
        update.warnings.append(f"Failed to write {path}: {exc}")
    return update


def summarize_ddc_status(shared_path: str, local_override: Optional[str], validation: DDCValidationResult) -> str:
    fallback = local_override or str(default_local_ddc_path())
    return (
        f"DDC configured: shared={shared_path} (latency {validation.latency_ms:.1f} ms)"
        if validation.latency_ms is not None
        else f"DDC configured: shared={shared_path}"
    ) + f" | local fallback={fallback}"
