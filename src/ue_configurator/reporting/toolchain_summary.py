"""Formatter for concise toolchain summary."""

from __future__ import annotations

from typing import List, Optional

from ue_configurator.manifest.manifest_types import WindowsSDKRequirement
from ue_configurator.probe.base import CheckResult, CheckStatus
from ue_configurator.probe.runner import ScanData


def _get(scan: ScanData, check_id: str) -> Optional[CheckResult]:
    for checks in scan.results.values():
        for check in checks:
            if check.id == check_id:
                return check
    return None


def _line(label: str, value: str) -> str:
    return f"- {label}: {value}"


def render_toolchain_summary(scan: ScanData, manifest) -> str:
    lines: List[str] = []
    notes: List[str] = []

    vs = _get(scan, "toolchain.vs")
    if vs:
        vs_verification = "UNVERIFIED" if "UNVERIFIED" in vs.summary else vs.status.value
        lines.append(_line("Visual Studio", f"{vs.details} (component verification: {vs_verification})"))
        if "UNVERIFIED" in vs.summary:
            notes.append("VS component list unavailable; validated via toolchain artifacts instead.")

    msvc = _get(scan, "toolchain.msvc")
    if msvc:
        lines.append(_line("MSVC toolsets", msvc.details))

    sdk = _get(scan, "toolchain.windows_sdk")
    if sdk:
        lines.append(_line("Windows SDK", sdk.details))
        if sdk.status == CheckStatus.WARN:
            notes.append(sdk.message)

    pdbcopy = _get(scan, "toolchain.pdbcopy")
    if pdbcopy:
        lines.append(_line("pdbcopy", pdbcopy.details))

    cmake = _get(scan, "toolchain.cmake")
    if cmake:
        lines.append(_line("CMake/Ninja", cmake.details))

    redist = _get(scan, "ue.redist")
    if redist:
        lines.append(_line("VC++ Redist", redist.details))

    engine = _get(scan, "ue.engine-build")
    if engine:
        lines.append(_line("Engine build completeness", f"{engine.summary} | {engine.details}"))

    shader = _get(scan, "ue.shader-distribution")
    if shader:
        lines.append(_line("Shader distribution", f"{shader.summary} | {shader.details}"))

    ddc = _get(scan, "ue.ddc")
    if ddc:
        lines.append(_line("DDC", f"{ddc.summary} | {ddc.details}"))

    horde_agent = _get(scan, "horde.agent")
    if horde_agent:
        lines.append(_line("Horde agent", f"{horde_agent.summary} | {horde_agent.details}"))

    if not lines:
        return ""

    out = ["", "Toolchain Summary"]
    out.extend(lines)
    if notes:
        out.append("Drift notes")
        for note in notes:
            out.append(f"- NOTE: {note}")
    return "\n".join(out)
