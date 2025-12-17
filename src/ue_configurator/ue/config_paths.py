"""Helpers for common Unreal configuration locations used by uecfg."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _appdata_roaming() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def user_build_configuration_path() -> Path:
    """Return the user-scoped BuildConfiguration.xml path."""

    return _appdata_roaming() / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"


def engine_build_configuration_path(ue_root: Path) -> Path:
    """Return the engine-scoped BuildConfiguration.xml path."""

    return Path(ue_root) / "Engine" / "Programs" / "UnrealBuildTool" / "BuildConfiguration.xml"


def user_ddc_config_path() -> Path:
    """User-scoped DDC config path."""

    return _appdata_roaming() / "Unreal Engine" / "Engine" / "DerivedDataCache.ini"


def engine_ddc_config_path(ue_root: Path) -> Path:
    """Engine-scoped DDC config path."""

    return Path(ue_root) / "Engine" / "Config" / "DerivedDataCache.ini"


def default_local_ddc_path() -> Path:
    """Default local Derived Data Cache path."""

    return _local_appdata() / "UnrealEngine" / "Common" / "DerivedDataCache"


def _extract_ddc_value(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in ("SharedDataCachePath", "SharedCachePath"):
            value = value.strip()
            if value:
                return value
    return None


def discover_existing_shared_ddc_path(ue_root: Path | None = None) -> Optional[str]:
    """Return an already-configured shared DDC path if present."""

    candidates = [user_ddc_config_path()]
    if ue_root:
        candidates.append(engine_ddc_config_path(ue_root))
        candidates.append(Path(ue_root) / "Engine" / "Config" / "BaseEngine.ini")
        candidates.append(Path(ue_root) / "Engine" / "Config" / "DefaultEngine.ini")

    for candidate in candidates:
        value = _extract_ddc_value(candidate)
        if value:
            return value
    return None


def default_shared_ddc_suggestion(ue_root: Path | None = None) -> str:
    """Prefer an existing config value; otherwise leave blank."""

    return discover_existing_shared_ddc_path(ue_root) or ""
