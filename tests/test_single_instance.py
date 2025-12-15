from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import textwrap
from pathlib import Path

BASE_ENV = os.environ.copy()
BASE_ENV["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")


def _run(code: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env or BASE_ENV,
        timeout=15,
    )


def _write_lock(lock_file: Path, pid: int, hostname: str, repo_root: Path) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "pid": pid,
        "start_time": "2024-01-01T00:00:00Z",
        "hostname": hostname,
        "username": "tester",
        "repo_root": str(repo_root),
        "command": ["uecfg", "scan"],
        "tool_version": "0.0.0-test",
    }
    lock_file.write_text(json.dumps(metadata), encoding="utf-8")


def test_single_instance_blocks_second_process(tmp_path):
    lock_file = tmp_path / "uecfg-test.lock"
    lock_dir = tmp_path

    holder_code = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from ue_configurator.runtime.single_instance import acquire_single_instance_lock
        with acquire_single_instance_lock('uecfg-test', None, lock_dir=Path(r'{lock_dir}')):
            print('holding', flush=True)
            time.sleep(3)
        """
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=BASE_ENV,
    )

    start = time.time()
    while True:
        line = holder.stdout.readline()
        if "holding" in line:
            break
        if holder.poll() is not None:
            raise AssertionError(f"Holder exited early: {holder.stdout.read()} {holder.stderr.read()}")
        if time.time() - start > 5:
            holder.kill()
            raise AssertionError("Holder process did not start in time")

    competitor_code = textwrap.dedent(
        f"""
        from pathlib import Path
        from ue_configurator.runtime.single_instance import acquire_single_instance_lock, SingleInstanceError
        import sys
        from types import SimpleNamespace
        sys.stdin = SimpleNamespace(isatty=lambda: False)
        try:
            with acquire_single_instance_lock('uecfg-test', None, lock_dir=Path(r'{lock_dir}')):
                pass
        except SingleInstanceError as err:
            print(err.user_message)
            sys.exit(2)
        print('acquired')
        """
    )
    competitor = _run(competitor_code)

    holder.terminate()
    holder.wait(timeout=5)

    assert competitor.returncode == 2
    assert "Another instance appears to be running" in competitor.stdout
    assert lock_file.exists()


def test_stale_pid_auto_recovers(tmp_path):
    lock_file = tmp_path / "uecfg-test.lock"
    repo_root = Path.cwd()
    _write_lock(lock_file, pid=999999, hostname=platform.node(), repo_root=repo_root)

    code = f"""
from pathlib import Path
from ue_configurator.runtime.single_instance import acquire_single_instance_lock
with acquire_single_instance_lock('uecfg-test', None, lock_dir=Path(r'{tmp_path}')):
    print('acquired')
"""
    result = _run(code)

    assert result.returncode == 0
    assert "Stale lock detected" in result.stdout
    assert "acquired" in result.stdout
    assert lock_file.exists() is False


def test_interactive_prompt_allows_manual_override(tmp_path):
    lock_file = tmp_path / "uecfg-test.lock"
    repo_root = Path.cwd()
    _write_lock(lock_file, pid=os.getpid(), hostname=platform.node(), repo_root=repo_root)

    code = f"""
from pathlib import Path
import builtins
import sys
from types import SimpleNamespace
from ue_configurator.runtime.single_instance import acquire_single_instance_lock
sys.stdin = SimpleNamespace(isatty=lambda: True)
builtins.input = lambda prompt='': '2'
with acquire_single_instance_lock('uecfg-test', None, lock_dir=Path(r'{tmp_path}')):
    print('acquired')
"""
    result = _run(code)

    assert result.returncode == 0
    assert "Another instance appears to be running" in result.stdout
    assert "acquired" in result.stdout
    assert lock_file.exists() is False


def test_non_interactive_conflict_fails_fast(tmp_path):
    lock_file = tmp_path / "uecfg-test.lock"
    repo_root = Path.cwd()
    _write_lock(lock_file, pid=os.getpid(), hostname=platform.node(), repo_root=repo_root)

    code = f"""
from pathlib import Path
import sys
from types import SimpleNamespace
from ue_configurator.runtime.single_instance import acquire_single_instance_lock, SingleInstanceError
sys.stdin = SimpleNamespace(isatty=lambda: False)
try:
    with acquire_single_instance_lock('uecfg-test', None, lock_dir=Path(r'{tmp_path}')):
        print('should-not-happen')
except SingleInstanceError as err:
    print(err.user_message)
    sys.exit(2)
"""
    result = _run(code)

    assert result.returncode == 2
    assert "Another instance appears to be running" in result.stdout
    assert lock_file.exists()


def test_lock_cleanup_on_exit(tmp_path):
    lock_file = tmp_path / "uecfg-test.lock"
    code = f"""
from pathlib import Path
from ue_configurator.runtime.single_instance import acquire_single_instance_lock
lock_path = Path(r'{lock_file}')
with acquire_single_instance_lock('uecfg-test', None, lock_dir=lock_path.parent):
    assert lock_path.exists()
print('done')
"""
    result = _run(code)

    assert result.returncode == 0
    assert "done" in result.stdout
    assert lock_file.exists() is False
