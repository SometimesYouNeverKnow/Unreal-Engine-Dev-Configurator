from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from contextlib import contextmanager

import ue_configurator.cli as cli


def _fake_input(sequence):
    it = iter(sequence)

    def _inner(prompt: str = ""):
        return next(it, "")

    return _inner


@contextmanager
def _noop_lock(*args, **kwargs):
    yield


def test_intent_configure_only_keeps_build_disabled(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "_is_admin", lambda: True)
    monkeypatch.setattr("builtins.input", _fake_input(["1"]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup", "--phase", "2"])

    assert captured["options"].build_engine is False
    assert captured["options"].plan_only is False


def test_intent_build_only_sets_build_engine_and_requires_root(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    ue_root = tmp_path / "UE"
    ue_root.mkdir()

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "_is_admin", lambda: True)
    monkeypatch.setattr("builtins.input", _fake_input(["2", str(ue_root)]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup"])

    opts = captured["options"]
    assert opts.build_engine is True
    assert opts.ue_root == str(ue_root)
    assert opts.phases == [2]


def test_intent_both_prompts_for_build_confirmation(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    def fake_prompt_bool(prompt, default=True):
        # Consent + final build confirmation -> True
        return True

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", fake_prompt_bool)
    monkeypatch.setattr(cli, "_is_admin", lambda: True)
    monkeypatch.setattr("builtins.input", _fake_input(["3"]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup", "--phase", "2"])

    assert captured["options"].build_engine is True
    assert captured["options"].apply is True


def test_admin_fallback_plan_only(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    ue_root = tmp_path / "UE"
    ue_root.mkdir()

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "_is_admin", lambda: False)
    # Option 2 -> path -> choose plan-only (a)
    monkeypatch.setattr("builtins.input", _fake_input(["2", str(ue_root), "a"]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup"])

    opts = captured["options"]
    assert opts.plan_only is True
    assert opts.apply is False
    assert opts.build_engine is False


def test_intent_register_option(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", _fake_input(["4"]))
    assert cli._prompt_intent() == "register"


def test_intent_ddc_option(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", _fake_input(["5"]))
    assert cli._prompt_intent() == "ddc-shaders"


def test_intent_horde_helper_option(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", _fake_input(["6"]))
    assert cli._prompt_intent() == "horde-helper"


def test_intent_horde_helper_routes(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_helper(options):
        captured["options"] = options
        return SimpleNamespace(
            applied=False,
            horde_status="horde",
            shader_status="shader",
            ddc_status="ddc",
            warnings=[],
        )

    monkeypatch.setattr(cli, "run_horde_setup_helper", fake_helper)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "_is_admin", lambda: True)
    monkeypatch.setattr("builtins.input", _fake_input(["6"]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup", "--ue-root", str(tmp_path)])

    assert captured["options"].interactive is True


def test_register_only_prompts_for_root(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    ue_root = tmp_path / "UE"
    ue_root.mkdir()

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr(cli, "_prompt_profile_choice", lambda current: current)
    monkeypatch.setattr(cli, "_prompt_bool_cli", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "_is_admin", lambda: True)
    monkeypatch.setattr("builtins.input", _fake_input(["4", str(ue_root)]))
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

    cli.main(["setup"])

    opts = captured["options"]
    assert opts.register_engine is True
    assert opts.build_engine is False
    assert opts.ue_root == str(ue_root)
    assert opts.phases == [2]


def test_register_flag_noninteractive(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    ue_root = tmp_path / "UE"
    ue_root.mkdir()

    def fake_run_setup(opts):
        captured["options"] = opts
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    monkeypatch.setattr(cli, "acquire_single_instance_lock", _noop_lock)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))

    cli.main(["setup", "--register-engine", "--ue-root", str(ue_root)])

    opts = captured["options"]
    assert opts.register_engine is True
    assert opts.apply is True
    assert opts.ue_root == str(ue_root)
