"""Typed structures describing UE toolchain manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ToolRequirement:
    name: str
    required: bool
    winget_id: Optional[str] = None
    min_version: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class VisualStudioRequirement:
    required_major: int
    min_version: Optional[str] = None
    recommended_version: Optional[str] = None
    requires_components: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    source: Optional[str] = None


@dataclass
class MSVCRequirement:
    preferred_toolset_family: str
    notes: Optional[str] = None


@dataclass
class WindowsSDKRequirement:
    preferred_versions: List[str] = field(default_factory=list)
    minimum_version: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class HordeUBARequirement:
    recommended: bool = False
    notes: Optional[str] = None


@dataclass
class Manifest:
    id: str
    ue_version: str
    path: Path
    visual_studio: VisualStudioRequirement
    msvc: MSVCRequirement
    windows_sdk: WindowsSDKRequirement
    extras: Dict[str, ToolRequirement] = field(default_factory=dict)
    horde_uba: Optional[HordeUBARequirement] = None
    notes: Optional[str] = None
    fingerprint: str = ""

    def describe(self) -> str:
        return f"{self.id} (UE {self.ue_version})"
