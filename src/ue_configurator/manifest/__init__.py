"""Manifest helpers that describe UE version-specific toolchain requirements."""

from .manifest_types import Manifest, ToolRequirement, VisualStudioRequirement
from .load_manifest import (
    MANIFEST_DIR,
    ManifestResolution,
    available_manifests,
    load_manifest_from_path,
    resolve_manifest,
)
from .detect_ue_version import detect_ue_version

__all__ = [
    "Manifest",
    "ToolRequirement",
    "VisualStudioRequirement",
    "MANIFEST_DIR",
    "ManifestResolution",
    "available_manifests",
    "load_manifest_from_path",
    "resolve_manifest",
    "detect_ue_version",
]
