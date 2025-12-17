"""Helpers for discovering and updating Horde Agent configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field
import configparser
import difflib
import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


EndpointPool = Tuple[Optional[str], Optional[str]]


_ENDPOINT_KEYS = {
    "server",
    "serverurl",
    "serveruri",
    "serveraddress",
    "hordeserver",
    "endpoint",
}
_POOL_KEYS = {
    "pool",
    "agentpool",
    "agentpoolname",
}


def _normalize_key(key: str) -> str:
    return key.replace("-", "").replace("_", "").lower()


def _extract_from_mapping(data: Any) -> EndpointPool:
    endpoint: Optional[str] = None
    pool: Optional[str] = None

    def walk(obj: Any) -> None:
        nonlocal endpoint, pool
        if isinstance(obj, dict):
            for key, value in obj.items():
                norm = _normalize_key(str(key))
                if endpoint is None and norm in _ENDPOINT_KEYS and isinstance(value, str):
                    endpoint = value.strip()
                if pool is None and norm in _POOL_KEYS and isinstance(value, str):
                    pool = value.strip()
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return endpoint, pool


def _parse_ini(text: str) -> Optional[Dict[str, Any]]:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.MissingSectionHeaderError:
        try:
            parser.read_string("[root]\n" + text)
        except configparser.Error:
            return None
    except configparser.Error:
        return None

    data: Dict[str, Dict[str, str]] = {}
    for section in parser.sections():
        data[section] = dict(parser.items(section))
    if not data and parser.defaults():
        data["root"] = dict(parser.defaults())
    return data


def _parse_yaml(text: str) -> Optional[Dict[str, Any]]:
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        data[key] = value
    return data or None


@dataclass
class HordeAgentConfig:
    path: Path
    endpoint: Optional[str]
    pool: Optional[str]
    parsed: bool
    format: str
    warnings: List[str] = field(default_factory=list)


def discover_horde_agent_configs() -> List[Path]:
    """Locate Horde Agent config files in common locations."""

    candidates: List[Path] = []
    program_data = os.environ.get("ProgramData")
    appdata = os.environ.get("APPDATA")
    local_appdata = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")

    roots = [
        Path(program_data) / "Horde" / "Agent" if program_data else None,
        Path(program_data) / "Epic" / "Horde" / "Agent" if program_data else None,
        Path(appdata) / "Horde" / "Agent" if appdata else None,
        Path(local_appdata) / "Horde" / "Agent" if local_appdata else None,
        Path(program_files) / "Horde" / "Agent" if program_files else None,
        Path(program_files) / "Epic Games" / "Horde" / "Agent" if program_files else None,
        Path(program_files_x86) / "Horde" / "Agent" if program_files_x86 else None,
        Path(program_files_x86) / "Epic Games" / "Horde" / "Agent" if program_files_x86 else None,
    ]

    names = [
        "appsettings.json",
        "agent.json",
        "HordeAgent.json",
        "HordeAgent.ini",
        "agent.ini",
        "HordeAgent.yaml",
        "HordeAgent.yml",
    ]

    for root in roots:
        if root is None:
            continue
        for name in names:
            path = root / name
            if path.exists():
                candidates.append(path)

    return candidates


def load_horde_agent_config(path: Path) -> HordeAgentConfig:
    """Parse a Horde agent config file, if possible."""

    warnings: List[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return HordeAgentConfig(path=path, endpoint=None, pool=None, parsed=False, format="unknown", warnings=[str(exc)])

    text = text.strip()
    if not text:
        return HordeAgentConfig(path=path, endpoint=None, pool=None, parsed=False, format="unknown")

    try:
        data = json.loads(text)
        endpoint, pool = _extract_from_mapping(data)
        return HordeAgentConfig(path=path, endpoint=endpoint, pool=pool, parsed=True, format="json")
    except json.JSONDecodeError:
        pass

    ini_data = _parse_ini(text)
    if ini_data is not None:
        endpoint, pool = _extract_from_mapping(ini_data)
        return HordeAgentConfig(path=path, endpoint=endpoint, pool=pool, parsed=True, format="ini")

    yaml_data = _parse_yaml(text)
    if yaml_data is not None:
        endpoint, pool = _extract_from_mapping(yaml_data)
        return HordeAgentConfig(path=path, endpoint=endpoint, pool=pool, parsed=True, format="yaml")

    warnings.append("Unrecognized config format.")
    return HordeAgentConfig(path=path, endpoint=None, pool=None, parsed=False, format="unknown", warnings=warnings)


def _timestamped_backup_path(path: Path) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_suffix(path.suffix + f".{stamp}.bak")


@dataclass
class HordeAgentConfigUpdate:
    path: Path
    before: Optional[str]
    after: Optional[str]
    changed_keys: List[str] = field(default_factory=list)
    backup: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.after is not None and self.after != (self.before or ""))

    def diff(self) -> str:
        before_lines = (self.before or "").splitlines(keepends=True)
        after_lines = (self.after or "").splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=str(self.path),
                tofile=f"{self.path} (proposed)",
                lineterm="",
            )
        )


def _update_json_data(data: Any, endpoint: Optional[str], pool: Optional[str]) -> Tuple[Any, List[str]]:
    changed: List[str] = []
    endpoint_keys = _ENDPOINT_KEYS
    pool_keys = _POOL_KEYS
    updated_endpoint = False
    updated_pool = False

    def walk(obj: Any) -> None:
        nonlocal updated_endpoint, updated_pool
        if isinstance(obj, dict):
            for key, value in obj.items():
                norm = _normalize_key(str(key))
                if endpoint is not None and not updated_endpoint and norm in endpoint_keys:
                    if value != endpoint:
                        obj[key] = endpoint
                        changed.append("endpoint")
                    updated_endpoint = True
                if pool is not None and not updated_pool and norm in pool_keys:
                    if value != pool:
                        obj[key] = pool
                        changed.append("pool")
                    updated_pool = True
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    if isinstance(data, dict):
        horde_section = None
        for key in ("Horde", "HordeAgent"):
            if key in data and isinstance(data[key], dict):
                horde_section = data[key]
                break
        if horde_section is not None:
            if endpoint is not None and not updated_endpoint:
                current = horde_section.get("Server")
                if current != endpoint:
                    horde_section["Server"] = endpoint
                    changed.append("endpoint")
            if pool is not None and not updated_pool:
                current = horde_section.get("Pool")
                if current != pool:
                    horde_section["Pool"] = pool
                    changed.append("pool")

    return data, list(dict.fromkeys(changed))


def _update_ini_data(parser: configparser.ConfigParser, endpoint: Optional[str], pool: Optional[str]) -> List[str]:
    changed: List[str] = []
    target_sections = parser.sections() or ["root"]
    if not parser.sections() and "root" not in parser:
        parser.add_section("root")
    for section in target_sections:
        if endpoint is not None:
            for key in list(parser[section].keys()):
                if _normalize_key(key) in _ENDPOINT_KEYS:
                    if parser[section].get(key) != endpoint:
                        parser[section][key] = endpoint
                        changed.append("endpoint")
                    endpoint = None
                    break
        if pool is not None:
            for key in list(parser[section].keys()):
                if _normalize_key(key) in _POOL_KEYS:
                    if parser[section].get(key) != pool:
                        parser[section][key] = pool
                        changed.append("pool")
                    pool = None
                    break

    if endpoint is not None or pool is not None:
        section = "Horde" if "Horde" in parser else target_sections[0]
        if endpoint is not None:
            parser[section]["Server"] = endpoint
            changed.append("endpoint")
        if pool is not None:
            parser[section]["Pool"] = pool
            changed.append("pool")

    return list(dict.fromkeys(changed))


def _update_yaml_text(text: str, endpoint: Optional[str], pool: Optional[str]) -> Tuple[str, List[str]]:
    changed: List[str] = []
    lines = text.splitlines()

    def replace_or_add(key: str, value: str) -> None:
        nonlocal lines
        for idx, line in enumerate(lines):
            if line.lstrip().startswith(f"{key}:"):
                current = line.split(":", 1)[1].strip().strip('"').strip("'")
                if current != value:
                    lines[idx] = f"{key}: {value}"
                    changed.append("endpoint" if key == "Server" else "pool")
                return
        lines.append(f"{key}: {value}")
        changed.append("endpoint" if key == "Server" else "pool")

    if endpoint is not None:
        replace_or_add("Server", endpoint)
    if pool is not None:
        replace_or_add("Pool", pool)

    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), list(dict.fromkeys(changed))


def plan_horde_agent_config_update(
    path: Path,
    *,
    endpoint: Optional[str],
    pool: Optional[str],
) -> HordeAgentConfigUpdate:
    if not endpoint and not pool:
        return HordeAgentConfigUpdate(path=path, before=None, after=None)

    before_text = None
    try:
        before_text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else None
    except OSError as exc:
        return HordeAgentConfigUpdate(path=path, before=None, after=None, warnings=[f"Unable to read {path}: {exc}"])

    if before_text is None:
        return HordeAgentConfigUpdate(
            path=path,
            before=None,
            after=None,
            warnings=[f"No existing Horde agent config found at {path}."],
        )

    try:
        data = json.loads(before_text)
        updated_data, changed_keys = _update_json_data(data, endpoint, pool)
        if not changed_keys:
            return HordeAgentConfigUpdate(path=path, before=before_text, after=before_text, changed_keys=[])
        after_text = json.dumps(updated_data, indent=2, ensure_ascii=True)
        return HordeAgentConfigUpdate(path=path, before=before_text, after=after_text, changed_keys=changed_keys)
    except json.JSONDecodeError:
        pass

    ini_data = _parse_ini(before_text)
    if ini_data is not None:
        parser = configparser.ConfigParser()
        try:
            parser.read_string(before_text)
        except configparser.MissingSectionHeaderError:
            parser.read_string("[root]\n" + before_text)
        changed_keys = _update_ini_data(parser, endpoint, pool)
        if not changed_keys:
            return HordeAgentConfigUpdate(path=path, before=before_text, after=before_text, changed_keys=[])
        output_lines: List[str] = []
        with _StringWriter(output_lines) as handle:
            parser.write(handle)
        after_text = "".join(output_lines)
        return HordeAgentConfigUpdate(path=path, before=before_text, after=after_text, changed_keys=changed_keys)

    yaml_data = _parse_yaml(before_text)
    if yaml_data is not None:
        after_text, changed_keys = _update_yaml_text(before_text, endpoint, pool)
        if not changed_keys:
            return HordeAgentConfigUpdate(path=path, before=before_text, after=before_text, changed_keys=[])
        return HordeAgentConfigUpdate(path=path, before=before_text, after=after_text, changed_keys=changed_keys)

    return HordeAgentConfigUpdate(
        path=path,
        before=before_text,
        after=None,
        warnings=[f"Unsupported config format at {path}; skipping update."],
    )


def apply_horde_agent_config_update(
    update: HordeAgentConfigUpdate,
    *,
    dry_run: bool,
    backup: bool = True,
) -> HordeAgentConfigUpdate:
    if not update.after:
        return update
    if not update.changed:
        return update

    path = update.path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not dry_run and path.exists() and backup:
        update.backup = _timestamped_backup_path(path)
        try:
            update.backup.write_text(update.before or "", encoding="utf-8")
        except OSError as exc:
            update.warnings.append(f"Failed to back up {path}: {exc}")
            update.backup = None

    if dry_run:
        return update

    try:
        path.write_text(update.after, encoding="utf-8")
    except OSError as exc:
        update.warnings.append(f"Failed to write {path}: {exc}")
    return update


class _StringWriter:
    def __init__(self, buffer: List[str]) -> None:
        self.buffer = buffer

    def write(self, text: str) -> int:
        self.buffer.append(text)
        return len(text)

    def __enter__(self) -> "_StringWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
