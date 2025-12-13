"""Guarded helpers for Horde / UBA preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ue_configurator.probe.base import ProbeContext


TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
  <BuildConfiguration>
    <ParallelExecutor>UBT</ParallelExecutor>
    <MaxParallelActions>16</MaxParallelActions>
    <bAllowRemoteBuilds>true</bAllowRemoteBuilds>
    <bAllowXGE>true</bAllowXGE>
    <bUseHordeAgent>true</bUseHordeAgent>
  </BuildConfiguration>
</Configuration>
"""


def generate_build_configuration(ctx: ProbeContext, destination: Optional[str] = None) -> Path:
    """Create a BuildConfiguration.xml template if it does not exist."""

    default_path = Path.home() / "Documents" / "Unreal Engine" / "BuildConfiguration.xml"
    target = Path(destination).expanduser() if destination else default_path
    if ctx.dry_run:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE, encoding="utf-8")
    return target
