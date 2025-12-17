from __future__ import annotations

from ue_configurator.probe.base import CommandResult
from ue_configurator.probe.horde import probe_horde_agent_status


class _Ctx:
    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr

    def run_command(self, command, timeout=5):
        return CommandResult(command, self.stdout, self.stderr, 0)


def test_horde_agent_status_not_found() -> None:
    ctx = _Ctx("FAILED 1060: The specified service does not exist as an installed service.")
    status = probe_horde_agent_status(ctx)
    assert status.installed is False
    assert status.running is False


def test_horde_agent_status_installed_not_running() -> None:
    ctx = _Ctx("SERVICE_NAME: HordeAgent\nSTATE              : 1  STOPPED")
    status = probe_horde_agent_status(ctx)
    assert status.installed is True
    assert status.running is False


def test_horde_agent_status_running() -> None:
    ctx = _Ctx("SERVICE_NAME: HordeAgent\nSTATE              : 4  RUNNING")
    status = probe_horde_agent_status(ctx)
    assert status.installed is True
    assert status.running is True
