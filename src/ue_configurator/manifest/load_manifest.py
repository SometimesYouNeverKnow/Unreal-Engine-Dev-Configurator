"""Utilities for loading and validating manifest files."""

from __future__ import annotations

import json
from dataclasses import dataclass
import hashlib
from pathlib import Path
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
            minimum_version=_normalize_version(sdk_payload.get("minimum_version")),
            notes=sdk_payload.get("notes"),
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


def _find_manifest_path(spec: Optional[str], *, ue_version: Optional[str]) -> Optional[Path]:
    if not spec and not ue_version:
        return None
    manifest_map = available_manifests()
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


def resolve_manifest(
    *,
    manifest: Optional[str],
    ue_version: Optional[str],
    ue_root: Optional[str],
) -> ManifestResolution:
    manifest_path = _find_manifest_path(manifest, ue_version=ue_version)
    detected_version = None
    if manifest_path is None and not manifest:
        detected_version = detect_ue_version(ue_root) if ue_root else None
        if detected_version:
            manifest_path = _find_manifest_path(None, ue_version=detected_version)
    if manifest_path is None:
        return ManifestResolution(manifest=None, detected_version=detected_version)
    loaded = load_manifest_from_path(manifest_path)
    return ManifestResolution(
        manifest=loaded,
        source=str(manifest_path),
        detected_version=detected_version or ue_version,
    )
