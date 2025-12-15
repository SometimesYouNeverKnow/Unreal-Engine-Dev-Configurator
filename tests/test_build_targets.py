from __future__ import annotations

from pathlib import Path
from typing import List

from ue_configurator.ue.build_targets import (
    build_missing_targets,
    determine_build_plan,
    summarize_plan,
)
from ue_configurator.ue.ubt_runner import UBTRunner


def test_determine_build_plan_marks_existing_binaries(tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    binary_dir = ue_root / "Engine" / "Binaries" / "Win64"
    binary_dir.mkdir(parents=True)
    existing = binary_dir / "UnrealEditor.exe"
    existing.write_text("stub")

    plan = determine_build_plan(ue_root)
    built_map = {item.target.name: item.built for item in plan}

    assert built_map["UnrealEditor"]
    assert built_map["ShaderCompileWorker"] is False
    assert [item.target.name for item in plan] == [
        "UnrealEditor",
        "ShaderCompileWorker",
        "UnrealPak",
        "CrashReportClient",
    ]


def test_build_plan_summarizes_skip_and_build(tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
    # Mark ShaderCompileWorker as already present
    (ue_root / "Engine" / "Binaries" / "Win64" / "ShaderCompileWorker.exe").write_text("stub")

    plan = determine_build_plan(ue_root)
    summary = summarize_plan(plan)

    assert "SKIP: ShaderCompileWorker" in summary
    assert "BUILD: UnrealEditor" in summary


def test_build_missing_targets_uses_runner(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    fake_build = ue_root / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    fake_build.write_text("@echo off\n")
    binaries = ue_root / "Engine" / "Binaries" / "Win64"
    binaries.mkdir(parents=True, exist_ok=True)

    calls: List[tuple] = []

    def fake_run(args, cwd=None, capture_output=True, text=True):
        calls.append((args, cwd))
        (binaries / "UnrealEditor.exe").write_text("built")

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return Proc()

    monkeypatch.setattr("subprocess.run", fake_run)

    runner = UBTRunner(ue_root)
    plan = determine_build_plan(ue_root, targets=["UnrealEditor"])
    execution = build_missing_targets(ue_root, plan, runner=runner, logger=lambda msg: None)

    assert calls
    args, cwd = calls[0]
    assert args[0] == str(fake_build)
    assert args[1:] == ["UnrealEditor", "Win64", "Development", "-WaitMutex"]
    assert cwd == ue_root
    assert execution.failed is False
    assert plan[0].result is not None
    assert "UnrealEditor Win64 Development -WaitMutex" in plan[0].result.command


def test_build_success_without_artifact_marks_failure(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    fake_build = ue_root / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    fake_build.write_text("@echo off\n")

    def fake_run(args, cwd=None, capture_output=True, text=True):
        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return Proc()

    monkeypatch.setattr("subprocess.run", fake_run)

    runner = UBTRunner(ue_root)
    plan = determine_build_plan(ue_root, targets=["UnrealEditor"])
    execution = build_missing_targets(ue_root, plan, runner=runner, logger=lambda msg: None)

    assert execution.failed is True
    assert plan[0].built is False
    assert "missing" in (plan[0].error or "").lower()
