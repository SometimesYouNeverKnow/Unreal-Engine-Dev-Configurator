from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_ENV = os.environ.copy()
BASE_ENV["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")


def _run(code: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env or BASE_ENV,
        timeout=10,
    )


def test_single_instance_blocks_second_process(tmp_path):
    # Use a test-specific lock name to avoid interfering with real runs.
    holder_code = """
import time
from ue_configurator.runtime.single_instance import acquire_single_instance_lock
with acquire_single_instance_lock('uecfg-test', None):
    print('holding', flush=True)
    time.sleep(3)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=BASE_ENV,
    )

    # Wait until the first process signals it holds the lock
    start = time.time()
    while True:
        line = holder.stdout.readline()
        if "holding" in line:
            break
        if holder.poll() is not None:
            raise AssertionError(f"Holder process exited early: {holder.stdout.read()} {holder.stderr.read()}")
        if time.time() - start > 5:
            holder.kill()
            raise AssertionError("Holder process did not start in time")

    competitor_code = """
from ue_configurator.runtime.single_instance import acquire_single_instance_lock, SingleInstanceError
import sys
try:
    with acquire_single_instance_lock('uecfg-test', None):
        pass
except SingleInstanceError as err:
    print(err.user_message)
    sys.exit(2)
print('acquired')
"""
    competitor = _run(competitor_code)

    holder.terminate()
    holder.wait(timeout=5)

    assert competitor.returncode == 2
    assert "already running" in competitor.stdout
