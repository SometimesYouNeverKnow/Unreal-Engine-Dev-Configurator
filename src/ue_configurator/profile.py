"""Profile definitions controlling setup behavior."""

from __future__ import annotations

import os
from enum import Enum
from typing import Dict, List


class Profile(str, Enum):
    WORKSTATION = "workstation"
    AGENT = "agent"
    MINIMAL = "minimal"


DEFAULT_PROFILE = Profile.WORKSTATION

DEFAULT_PHASES: Dict[Profile, List[int]] = {
    Profile.WORKSTATION: [0, 1, 2],
    Profile.AGENT: [0, 1, 2, 3],
    Profile.MINIMAL: [0, 1, 2, 3],
}


def resolve_profile(value: str | None) -> Profile:
    env_value = os.environ.get("UECFG_PROFILE")
    raw = (value or env_value or DEFAULT_PROFILE.value).lower()
    for profile in Profile:
        if profile.value == raw:
            return profile
    return DEFAULT_PROFILE


def phase_mode(profile: Profile, phase: int, has_ue_root: bool) -> str:
    if profile == Profile.MINIMAL:
        if phase == 0:
            return "required"
        if phase == 1:
            return "optional"
        return "na"
    if profile == Profile.AGENT:
        if phase == 0 or phase == 1:
            return "required"
        if phase == 2:
            return "required" if has_ue_root else "na"
        if phase == 3:
            return "recommended"
    if phase in (0, 1):
        return "required"
    if phase == 2:
        return "required"
    if phase == 3:
        return "optional"
    return "required"
