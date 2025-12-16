"""Discover UBT XML config keys from the source tree."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Set


def discover_xml_config_keys(ue_root: Path | None) -> Set[str]:
    """Scan UnrealBuildTool configuration classes for [XmlConfig] properties."""

    if ue_root is None:
        return set()

    config_root = Path(ue_root) / "Engine" / "Source" / "Programs" / "UnrealBuildTool" / "Configuration"
    if not config_root.exists():
        return set()

    pattern = re.compile(r"\[XmlConfig[^\]]*\]\s*(?:public|internal)\s+[^\s]+\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
    keys: Set[str] = set()
    for path in config_root.rglob("*.cs"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            keys.add(match.group("name"))
    return keys
