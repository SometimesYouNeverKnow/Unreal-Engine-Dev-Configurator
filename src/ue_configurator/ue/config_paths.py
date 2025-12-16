"""Helpers for common Unreal configuration locations used by uecfg."""

from __future__ import annotations

import os
from pathlib import Path


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


def default_shared_ddc_suggestion() -> str:
    """Provide a friendly default UNC suggestion without hardcoding it."""

    return r"\\LULU\DDC"
