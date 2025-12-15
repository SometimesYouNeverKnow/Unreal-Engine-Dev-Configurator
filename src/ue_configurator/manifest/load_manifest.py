"""Utilities for loading and validating manifest files."""

from __future__ import annotations

import json
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Dict, Iterable, Optional, Tuple

from .detect_ue_version import detect_ue_version
from .manifest_types import (
    HordeUBARequirement,
    MSVCRequirement,
    Manifest,
    ToolRequirement,
    VisualStudioRequirement,
    WindowsSDKRequirement,
)


MANIFEST_DIR = Path(__file__).resolve().parents[3] / "manifests"


@dataclass
class ManifestResolution:
    manifest: Optional[Manifest]
    source: str = ""
    detected_version: Optional[str] = None
    note: Optional[str] = None
    requested_version: Optional[str] = None
    resolved_version: Optional[str] = None
    failure_reason: Optional[str] = None


def available_manifests() -> Dict[str, Path]:
    manifest_map: Dict[str, Path] = {}
    if not MANIFEST_DIR.exists():
        return manifest_map
    for entry in MANIFEST_DIR.glob("ue_*.json"):
        manifest_map[entry.stem] = entry
    return manifest_map


def _normalize_version(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text.strip()


def _normalize_version_input(text: Optional[str]) -> Tuple[Optional[str], Optional[Tuple[str, str, Optional[str]]]]:
    if not text:
        return None, None
    digits = re.findall(r"\d+", text)
    if len(digits) < 2:
        return None, None
    major, minor = digits[0], digits[1]
    patch = digits[2] if len(digits) > 2 else None
    normalized = f"{major}.{minor}"
    if patch is not None:
        normalized = f"{normalized}.{patch}"
    return normalized, (major, minor, patch)


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Manifest {path} must be a JSON object.")
    return data


def _fingerprint(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def load_manifest_from_path(path: Path) -> Manifest:
    payload = _load_json(path)
    manifest_id = payload.get("id") or path.stem
    vs_payload = payload.get("visual_studio") or {}
    extras_payload = payload.get("extras") or {}

    min_version = _normalize_version(vs_payload.get("min_version") or vs_payload.get("min_build"))
    recommended_version = _normalize_version(vs_payload.get("recommended_version") or vs_payload.get("max_build"))
    msvc_payload = payload.get("msvc", {})
    sdk_payload = payload.get("windows_sdk", {})
    manifest = Manifest(
        id=str(manifest_id),
        ue_version=str(payload.get("ue_version", "")),
        path=path,
        visual_studio=VisualStudioRequirement(
            required_major=int(vs_payload.get("required_major", 0)),
            min_version=min_version,
            recommended_version=recommended_version,
            requires_components=[str(comp) for comp in vs_payload.get("requires_components", [])],
            notes=vs_payload.get("notes"),
            source=vs_payload.get("source"),
        ),
        msvc=MSVCRequirement(
            preferred_toolset_family=str(
                msvc_payload.get("preferred_toolset_family") or msvc_payload.get("toolset_family", "")
            ),
            notes=msvc_payload.get("notes"),
        ),
        windows_sdk=WindowsSDKRequirement(
            preferred_versions=[str(ver) for ver in sdk_payload.get("preferred_versions", [])],
            preferred_version=_normalize_version(sdk_payload.get("preferred_version")),
            minimum_version=_normalize_version(sdk_payload.get("minimum_version")),
            notes=sdk_payload.get("notes"),
            source=sdk_payload.get("source"),
        ),
        extras={
            name: ToolRequirement(
                name=name,
                required=bool(spec.get("required", False)),
                winget_id=spec.get("winget_id"),
                min_version=_normalize_version(spec.get("min_version")),
                notes=spec.get("notes"),
            )
            for name, spec in extras_payload.items()
        },
        horde_uba=(
            HordeUBARequirement(
                recommended=bool(payload.get("horde_uba", {}).get("recommended", False)),
                notes=payload.get("horde_uba", {}).get("notes"),
            )
            if payload.get("horde_uba")
            else None
        ),
        notes=payload.get("notes"),
    )
    manifest.fingerprint = _fingerprint(payload)
    return manifest


def _find_manifest_path(
    spec: Optional[str],
    *,
    ue_version: Optional[str],
    manifest_map: Optional[Dict[str, Path]] = None,
) -> Optional[Path]:
    if not spec and not ue_version:
        return None
    manifest_map = manifest_map or available_manifests()
    candidates: Iterable[str]
    if spec:
        candidates = [spec, spec.replace(".json", "")]
    elif ue_version:
        candidates = [f"ue_{ue_version}"]
    else:
        candidates = []
    for candidate in candidates:
        candidate = candidate.lower()
        if Path(candidate).exists():
            return Path(candidate)
        if candidate in manifest_map:
            return manifest_map[candidate]
        path = MANIFEST_DIR / f"{candidate}.json"
        if path.exists():
            return path
    return None


def _resolve_version_manifest(
    ue_version: Optional[str], manifest_map: Dict[str, Path]
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    normalized, parts = _normalize_version_input(ue_version)
    if not normalized or not parts:
        return None, None, None
    major, minor, patch = parts
    canonical_version = normalized
    path = _find_manifest_path(None, ue_version=canonical_version, manifest_map=manifest_map)
    if path:
        return path, canonical_version, None
    if patch is not None:
        minor_version = f"{major}.{minor}"
        path = _find_manifest_path(None, ue_version=minor_version, manifest_map=manifest_map)
        if path:
            note = f"Requested UE {canonical_version}; using manifest ue_{minor_version} (UE {minor_version})."
            return path, minor_version, note
    return None, None, None


def resolve_manifest(
    *,
    manifest: Optional[str],
    ue_version: Optional[str],
    ue_root: Optional[str],
) -> ManifestResolution:
    manifest_map = available_manifests()
    note = None
    resolved_version = None
    manifest_path = _find_manifest_path(manifest, ue_version=ue_version, manifest_map=manifest_map)
    detected_version = None
    if manifest_path is None and not manifest:
        detected_version = detect_ue_version(ue_root) if ue_root else None
        if detected_version:
            manifest_path, resolved_version, note = _resolve_version_manifest(detected_version, manifest_map)
    if manifest_path is None and not manifest:
        manifest_path, resolved_version, note = _resolve_version_manifest(ue_version, manifest_map)
    failure_reason = None
    requested_norm, _ = _normalize_version_input(ue_version)
    if manifest_path is None and requested_norm:
        available = ", ".join(sorted(manifest_map)) if manifest_map else "none"
        failure_reason = f"Requested UE {requested_norm} but no manifest file was resolved. Available: {available}."
    if manifest_path is None:
        return ManifestResolution(
            manifest=None,
            detected_version=detected_version,
            requested_version=requested_norm or ue_version,
            resolved_version=resolved_version,
            note=note,
            failure_reason=failure_reason,
        )
    loaded = load_manifest_from_path(manifest_path)
    return ManifestResolution(
        manifest=loaded,
        source=str(manifest_path),
        detected_version=detected_version or ue_version,
        note=note,
        requested_version=requested_norm or ue_version,
        resolved_version=resolved_version or ue_version,
    )
