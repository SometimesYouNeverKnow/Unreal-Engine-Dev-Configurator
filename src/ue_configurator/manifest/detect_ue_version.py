"""Attempt to determine the UE version from a source tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def detect_ue_version(ue_root: Optional[str]) -> Optional[str]:
    if not ue_root:
        return None
    version_file = Path(ue_root) / "Engine" / "Build" / "Build.version"
    if not version_file.is_file():
        return None
    try:
        payload = json.loads(version_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    major = payload.get("MajorVersion")
    minor = payload.get("MinorVersion")
    patch = payload.get("PatchVersion")
    if major is None or minor is None:
        return None
    parts = [str(major), str(minor)]
    if patch not in (None, 0):
        parts.append(str(patch))
    return ".".join(parts)
