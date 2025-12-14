"""Tests covering manifest loading and compliance."""

from __future__ import annotations

from pathlib import Path
import json

from ue_configurator.manifest import MANIFEST_DIR, load_manifest_from_path, resolve_manifest
from ue_configurator.probe.base import CheckStatus, CommandResult, ProbeContext
from ue_configurator.probe.runner import run_scan
from ue_configurator.profile import Profile
from ue_configurator.probe import toolchain
from ue_configurator.report.json_report import write_json


def test_load_manifest_sets_fingerprint() -> None:
    manifest_path = MANIFEST_DIR / "ue_5.7.json"
    manifest = load_manifest_from_path(manifest_path)
    assert manifest.fingerprint
    assert manifest.visual_studio.required_major == 17


def test_resolve_manifest_by_version() -> None:
    resolution = resolve_manifest(manifest=None, ue_version="5.7", ue_root=None)
    assert resolution.manifest is not None
    assert resolution.manifest.id == "ue_5.7"


def test_manifest_compliance_pass(monkeypatch, tmp_path: Path) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext(manifest=manifest, dry_run=True)
    ctx.cache["dotnet.sdks"] = ["8.0.100 [C:\\Program Files\\dotnet\\sdk]"]
    vs_root = tmp_path / "VS"
    toolset_dir = vs_root / "VC" / "Tools" / "MSVC" / "14.44.34567"
    toolset_dir.mkdir(parents=True)

    fake_instances = [
        toolchain.VSInstance(
            display_name="VS 2022",
            installation_path=vs_root,
            version="17.8.5",
            product_id="",
            packages=[
                "Microsoft.VisualStudio.Workload.NativeDesktop",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "Microsoft.VisualStudio.Component.VC.CMake.Project",
            ],
        )
    ]

    monkeypatch.setattr(toolchain, "_discover_vs_instances", lambda ctx: fake_instances)
    monkeypatch.setattr(toolchain, "_collect_windows_sdks", lambda ctx: [("10.0.22621.0", "C:/SDK")])
    monkeypatch.setattr(toolchain, "_detect_tool", lambda tool, ctx: [f"C:/Tools/{tool}"])

    def fake_run(self, command, **kwargs):
        if isinstance(command, list) and command[:2] == ["git", "--version"]:
            return CommandResult(command, "git version 2.44.0", "", 0)
        return CommandResult(command, "", "", 1)

    monkeypatch.setattr(ProbeContext, "run_command", fake_run, raising=False)

    result = toolchain.check_manifest_compliance(ctx)
    assert result.status == CheckStatus.PASS


def test_manifest_compliance_fail_without_vs(monkeypatch) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext(manifest=manifest, dry_run=True)
    monkeypatch.setattr(toolchain, "_discover_vs_instances", lambda ctx: [])
    result = toolchain.check_manifest_compliance(ctx)
    assert result.status == CheckStatus.FAIL


def test_manifest_ue57_contains_expected_vs_components() -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    components = set(manifest.visual_studio.requires_components)
    expected = {
        "Microsoft.VisualStudio.Workload.NativeDesktop",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "Microsoft.VisualStudio.Component.VC.CMake.Project",
    }
    assert expected.issubset(components)
    assert manifest.visual_studio.min_version == "17.8"
    assert manifest.visual_studio.recommended_version == "17.14"


def test_scan_metadata_includes_manifest() -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext(manifest=manifest, dry_run=True)
    scan = run_scan([], ctx, Profile.WORKSTATION)
    assert scan.metadata["manifestId"] == manifest.id
    assert scan.metadata["ueVersion"] == manifest.ue_version


def test_json_report_contains_manifest_metadata(tmp_path: Path) -> None:
    manifest = load_manifest_from_path(MANIFEST_DIR / "ue_5.7.json")
    ctx = ProbeContext(manifest=manifest, dry_run=True)
    scan = run_scan([], ctx, Profile.WORKSTATION)
    target = tmp_path / "report.json"
    write_json(scan, str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["metadata"]["manifestId"] == manifest.id
    assert payload["metadata"]["ueVersion"] == manifest.ue_version
