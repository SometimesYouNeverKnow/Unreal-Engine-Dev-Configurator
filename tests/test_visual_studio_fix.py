"""Tests for Visual Studio manifest automation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from ue_configurator.fix import visual_studio
from ue_configurator.manifest import MANIFEST_DIR, load_manifest_from_path
from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.toolchain import VSInstance


def test_generate_vsconfig_contains_manifest_components(tmp_path: Path) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    path = visual_studio.generate_vsconfig(manifest)
    data = json.loads(path.read_text(encoding="utf-8"))
    expected_workloads = {item for item in manifest.visual_studio.requires_components if ".Workload." in item}
    expected_components = {item for item in manifest.visual_studio.requires_components if ".Workload." not in item}
    assert set(data["workloads"]) == expected_workloads
    assert set(data["components"]) == expected_components
    assert path.is_absolute()
    assert path.exists()


def test_plan_vs_modify_detects_missing(monkeypatch) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext()
    fake_instance = VSInstance(
        display_name="VS",
        installation_path=Path("C:/VS"),
        version="17.8.5",
        product_id="visualstudio",
        packages=["Microsoft.VisualStudio.Workload.NativeDesktop"],
    )
    monkeypatch.setattr(visual_studio, "get_vs_instances", lambda ctx: [fake_instance])
    plan = visual_studio.plan_vs_modify(ctx, manifest)
    assert plan.required
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in plan.missing_components


def test_build_installer_command_passive() -> None:
    cmd = visual_studio._build_installer_command(
        Path("setup.exe"), Path("C:/VS"), Path("cfg.vsconfig"), True
    )
    assert "--passive" in cmd
    assert "--norestart" in cmd
    assert "--wait" not in cmd


def test_build_installer_command_interactive() -> None:
    cmd = visual_studio._build_installer_command(
        Path("setup.exe"), Path("C:/VS"), Path("cfg.vsconfig"), False
    )
    assert "--passive" not in cmd
    assert "--norestart" not in cmd


def test_modify_vs_install_runs_setup(monkeypatch, tmp_path: Path) -> None:
    setup_exe = tmp_path / "setup.exe"
    setup_exe.write_text("", encoding="utf-8")
    vsconfig = tmp_path / "cfg.vsconfig"
    vsconfig.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(visual_studio.tempfile, "mkdtemp", lambda prefix: str(run_dir))
    monkeypatch.setattr(visual_studio.time, "sleep", lambda *_: None)
    monkeypatch.setattr("ue_configurator.fix.visual_studio._discover_vs_log_hint", lambda since: None)

    captured = {}

    class DummyProc:
        def __init__(self):
            self.pid = 1234
            self.returncode = 0
            self._polls = 0

        def poll(self):
            if self._polls == 0:
                self._polls += 1
                return None
            return 0

        def communicate(self):
            return ("ok", "")

    def fake_popen(cmd, cwd, stdout, stderr, text):
        captured["cmd"] = cmd
        assert Path(cwd) == run_dir
        return DummyProc()

    monkeypatch.setattr(visual_studio.subprocess, "Popen", fake_popen)
    outcome = visual_studio.modify_vs_install(
        install_path=Path("C:/VS"),
        setup_exe=setup_exe,
        vsconfig_path=vsconfig,
        vs_passive=True,
        dry_run=False,
        logger=None,
    )
    assert outcome.success
    assert "--wait" not in captured["cmd"]
    assert "--passive" in captured["cmd"]
    assert "--norestart" in captured["cmd"]


def test_modify_vs_install_usage_failure(monkeypatch, tmp_path: Path) -> None:
    setup_exe = tmp_path / "setup.exe"
    setup_exe.write_text("", encoding="utf-8")
    vsconfig = tmp_path / "cfg.vsconfig"
    vsconfig.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(visual_studio.tempfile, "mkdtemp", lambda prefix: str(run_dir))
    monkeypatch.setattr("ue_configurator.fix.visual_studio._discover_vs_log_hint", lambda since: None)

    class DummyProc:
        pid = 4321
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return ("Usage: setup.exe modify [options]", "")

    monkeypatch.setattr(
        visual_studio.subprocess,
        "Popen",
        lambda *args, **kwargs: DummyProc(),
    )

    outcome = visual_studio.modify_vs_install(
        install_path=Path("C:/VS"),
        setup_exe=setup_exe,
        vsconfig_path=vsconfig,
        vs_passive=True,
        dry_run=False,
        logger=None,
    )
    assert not outcome.success
    assert outcome.blocked


def test_modify_vs_install_missing_config(tmp_path: Path) -> None:
    setup_exe = tmp_path / "setup.exe"
    setup_exe.write_text("", encoding="utf-8")
    missing_cfg = tmp_path / "missing.vsconfig"
    outcome = visual_studio.modify_vs_install(
        install_path=Path("C:/VS"),
        setup_exe=setup_exe,
        vsconfig_path=missing_cfg,
        vs_passive=True,
        dry_run=False,
        logger=None,
    )
    assert not outcome.success
    assert outcome.blocked


def test_ensure_vs_manifest_components_blocked_without_setup(monkeypatch) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext()
    monkeypatch.setattr(visual_studio, "plan_vs_modify", lambda ctx, manifest: visual_studio.VSModifyPlan(True, "missing", None, ["comp"]))
    monkeypatch.setattr(visual_studio, "find_vs_installer_setup_exe", lambda: None)
    outcome = visual_studio.ensure_vs_manifest_components(ctx, manifest)
    assert outcome.blocked
