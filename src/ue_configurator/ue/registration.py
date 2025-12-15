"""Helpers for detecting and invoking Unreal Engine registration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

try:  # pragma: no cover - Windows only
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None


def _selector_search_roots(ue_root: Path) -> Tuple[Path, ...]:
    binaries = ue_root / "Engine" / "Binaries"
    win64 = binaries / "Win64"
    return (win64, binaries)


def find_selector(ue_root: Path) -> Optional[Path]:
    """Locate UnrealVersionSelector executable within the UE root."""

    for root in _selector_search_roots(Path(ue_root)):
        if not root.exists():
            continue
        preferred = root / "UnrealVersionSelector-Win64-Shipping.exe"
        if preferred.exists():
            return preferred
        for candidate in root.glob("UnrealVersionSelector*.exe"):
            if candidate.name.lower().startswith("unrealversionselector"):
                return candidate
    return None


def is_engine_registered(ue_root: Path) -> bool:
    """Best-effort detection of existing engine registration via HKCU."""

    if winreg is None:
        return False

    target = str(Path(ue_root).expanduser())
    try:
        target_resolved = str(Path(target).resolve())
    except Exception:
        target_resolved = target

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds") as key:
            value_count = winreg.QueryInfoKey(key)[1]
            for idx in range(value_count):
                try:
                    _, data, _ = winreg.EnumValue(key, idx)
                except OSError:
                    continue
                candidate = str(data)
                try:
                    candidate_resolved = str(Path(candidate).expanduser().resolve())
                except Exception:
                    candidate_resolved = candidate
                if candidate_resolved.lower() == target_resolved.lower():
                    return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return False
