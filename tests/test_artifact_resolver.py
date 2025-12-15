from __future__ import annotations

from pathlib import Path

from ue_configurator.ue.artifact_resolver import ArtifactResolver
from ue_configurator.ue.build_targets import BuildTarget


def _make_resolver(tmp_path: Path) -> ArtifactResolver:
    ue_root = tmp_path / "UE"
    return ArtifactResolver(ue_root)


def test_resolver_hits_canonical(tmp_path: Path) -> None:
    resolver = _make_resolver(tmp_path)
    ue_root = resolver.ue_root
    canonical = ue_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("exe")

    target = BuildTarget("UnrealEditor", "Win64", "Development")
    result = resolver.resolve(target)

    assert result.found
    assert result.resolved == canonical
    assert result.found_via_search is False


def test_resolver_finds_non_canonical(tmp_path: Path) -> None:
    resolver = _make_resolver(tmp_path)
    ue_root = resolver.ue_root
    elsewhere = ue_root / "Engine" / "Extras" / "Tools" / "CrashReportClient.exe"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    elsewhere.write_text("exe")

    target = BuildTarget("CrashReportClient", "Win64", "Development")
    result = resolver.resolve(target)

    assert result.found
    assert result.resolved == elsewhere
    assert result.found_via_search is True


def test_resolver_reports_missing(tmp_path: Path) -> None:
    resolver = _make_resolver(tmp_path)
    target = BuildTarget("ShaderCompileWorker", "Win64", "Development")

    result = resolver.resolve(target)

    assert result.found is False
    assert result.resolved is None


def test_resolver_prefers_win64_on_tie(tmp_path: Path) -> None:
    resolver = _make_resolver(tmp_path)
    ue_root = resolver.ue_root
    canonical_dir = ue_root / "Engine" / "Binaries" / "Win64"
    tie_dir = ue_root / "Engine" / "Plugins"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    tie_dir.mkdir(parents=True, exist_ok=True)
    canonical = canonical_dir / "UnrealPak.exe"
    other = tie_dir / "UnrealPak.exe"
    canonical.write_text("exe")
    other.write_text("exe")

    target = BuildTarget("UnrealPak", "Win64", "Development")
    result = resolver.resolve(target)

    assert result.found
    assert result.resolved == canonical
