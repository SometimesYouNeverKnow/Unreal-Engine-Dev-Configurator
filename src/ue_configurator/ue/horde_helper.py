"""Interactive helper for auditing/configuring Horde, shaders, and shared DDC."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import socket
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.horde import probe_horde_agent_status, discover_agent_config
from ue_configurator.probe.unreal import BuildConfigurationInspection, inspect_build_configuration
from ue_configurator.ue.build_config import (
    BuildConfigUpdate,
    apply_build_configuration_update,
    plan_build_configuration_update,
)
from ue_configurator.ue.config_paths import (
    engine_build_configuration_path,
    engine_ddc_config_path,
    user_build_configuration_path,
    user_ddc_config_path,
)
from ue_configurator.ue.ddc_config import (
    DDCUpdate,
    DDCValidationResult,
    apply_ddc_update,
    plan_ddc_update,
    scan_ddc_schema,
    summarize_ddc_status,
    validate_ddc_path,
)
from ue_configurator.ue.ddc_verify import is_unc_path, verify_shared_ddc_path
from ue_configurator.ue.horde_agent_config import (
    HordeAgentConfig,
    HordeAgentConfigUpdate,
    apply_horde_agent_config_update,
    plan_horde_agent_config_update,
)
from ue_configurator.ue.ubt_config_schema import discover_xml_config_keys


InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


@dataclass
class HordeHelperOptions:
    ue_root: Optional[Path]
    dry_run: bool
    apply: bool
    verbose: bool
    interactive: bool
    input: InputFunc = input
    output: PrintFunc = print
    verify_horde: bool = False
    verify_ddc: bool = False
    verify_ddc_write_test: bool = False
    prompt_for_mode: bool = True


@dataclass
class HordeHelperOutcome:
    applied: bool
    horde_status: str
    shader_status: str
    ddc_status: str
    warnings: List[str] = field(default_factory=list)
    changes: List[str] = field(default_factory=list)


@dataclass
class DDCDetection:
    shared_path: Optional[str]
    local_path: Optional[str]
    classification: str
    sources: List[str] = field(default_factory=list)
    shared_is_unc: bool = False


def _prompt_mode(options: HordeHelperOptions) -> bool:
    options.output("Mode:")
    options.output("  1) Audit-only (recommended)")
    options.output("  2) Apply changes (writes config)")
    while True:
        resp = options.input("Select [1]: ").strip()
        if not resp or resp == "1":
            return False
        if resp == "2":
            return True
        options.output("Please choose 1 or 2.")


def _prompt_ue_root(options: HordeHelperOptions) -> Optional[Path]:
    default = options.ue_root
    suffix = f" [{default}]" if default else ""
    resp = options.input(f"UE root path (blank to skip){suffix}: ").strip().strip('"')
    if not resp:
        return default
    return Path(resp)


def _prompt_scope(options: HordeHelperOptions) -> str:
    options.output("Select configuration scope:")
    options.output("  1) User-global (recommended)")
    options.output("  2) Engine-global (this UE root)")
    options.output("  3) Both")
    while True:
        resp = options.input("Scope [1]: ").strip()
        if not resp or resp == "1":
            return "user"
        if resp == "2":
            return "engine"
        if resp == "3":
            return "both"
        options.output("Please choose 1, 2, or 3.")


def _prompt_optional_value(label: str, detected: Optional[str], options: HordeHelperOptions) -> Optional[str]:
    suffix = f" (detected: {detected})" if detected else ""
    resp = options.input(f"{label}{suffix} (blank to skip): ").strip().strip('"')
    if not resp:
        return None
    if resp.lower() in ("skip", "none"):
        return None
    return resp


def _prompt_yes_no(options: HordeHelperOptions, prompt: str, default: bool = False) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        resp = options.input(f"{prompt} [{default_str}] ").strip().lower()
        if not resp:
            return default
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False


def _collect_ddc_detection(ue_root: Optional[Path]) -> DDCDetection:
    sources: List[str] = []
    shared_path: Optional[str] = None
    local_path: Optional[str] = None
    env_shared = os.environ.get("UE-SharedDataCachePathOverride") or os.environ.get("UE-SharedDataCachePath")
    env_local = os.environ.get("UE-LocalDataCachePath")
    if env_shared:
        shared_path = env_shared
        sources.append(f"Env UE-SharedDataCachePath={env_shared}")
    if env_local:
        local_path = env_local
        sources.append(f"Env UE-LocalDataCachePath={env_local}")

    candidates = [user_ddc_config_path()]
    if ue_root:
        candidates.append(engine_ddc_config_path(ue_root))
        candidates.append(ue_root / "Engine" / "Config" / "BaseEngine.ini")
        candidates.append(ue_root / "Engine" / "Config" / "DefaultEngine.ini")
        candidates.append(ue_root / "Engine" / "Saved" / "Config" / "Windows" / "Engine.ini")

    for cfg in candidates:
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not value:
                continue
            if key in ("SharedDataCachePath", "SharedCachePath") and shared_path is None:
                shared_path = value
                sources.append(f"{cfg}: {key}={value}")
            if key in ("LocalDataCachePath", "LocalCachePath") and local_path is None:
                local_path = value
                sources.append(f"{cfg}: {key}={value}")

    classification = _classify_ddc_path(shared_path, ue_root)
    if shared_path is None and local_path:
        classification = "local"
    shared_is_unc = bool(shared_path and is_unc_path(shared_path))
    return DDCDetection(
        shared_path=shared_path,
        local_path=local_path,
        classification=classification,
        sources=sources,
        shared_is_unc=shared_is_unc,
    )


def _classify_ddc_path(path_text: Optional[str], ue_root: Optional[Path]) -> str:
    if not path_text:
        return "unknown"
    lower = path_text.lower()
    if is_unc_path(path_text) or "://" in lower:
        return "shared"
    if ue_root and str(ue_root).lower() in lower:
        return "local"
    home = str(Path.home()).lower()
    if home and home in lower:
        return "local"
    return "unknown"


def _summarize_horde_status(status) -> str:
    if status.running:
        return "Horde agent running"
    if status.installed:
        return "Horde agent installed but not running"
    return "Horde agent not found"


def _summarize_build_config(inspection: BuildConfigurationInspection) -> str:
    if inspection.status == "missing":
        return "BuildConfiguration.xml not found"
    if inspection.status == "no-flags":
        return f"{inspection.path}: no relevant flags"
    if inspection.status == "disabled":
        return f"{inspection.path}: flags present but disabled"
    if inspection.status == "unreadable":
        return f"{inspection.path}: unreadable"
    return f"{inspection.path}: distributed shaders enabled"


def _summarize_ddc_detection(ddc: DDCDetection) -> str:
    if ddc.shared_path:
        note = "UNC path (not verified)" if ddc.shared_is_unc else ddc.classification
        return f"Shared DDC: {ddc.shared_path} [{note}]"
    if ddc.local_path:
        return f"Shared DDC: not set (local path detected: {ddc.local_path})"
    return "Shared DDC: not configured"


def _print_audit_report(
    options: HordeHelperOptions,
    *,
    horde_status,
    agent_config: Optional[HordeAgentConfig],
    build_config: BuildConfigurationInspection,
    ddc: DDCDetection,
) -> None:
    options.output("Audit report:")
    options.output(f"  - Horde agent: {_summarize_horde_status(horde_status)}")
    if agent_config is None:
        options.output("  - Agent config: not found")
    elif agent_config.parsed:
        endpoint = agent_config.endpoint or "unknown"
        pool = agent_config.pool or "unknown"
        options.output(f"  - Agent config: {agent_config.path} (endpoint={endpoint}, pool={pool})")
    else:
        options.output(f"  - Agent config: {agent_config.path} (found but unparsed)")
    options.output(f"  - Distributed shaders: {_summarize_build_config(build_config)}")
    options.output(f"  - Shared DDC: {_summarize_ddc_detection(ddc)}")


def _print_next_actions(options: HordeHelperOptions) -> None:
    options.output("")
    options.output("Next actions:")
    options.output("  - uecfg setup  (choose option 6, then select Apply to write config)")
    options.output("  - uecfg setup --verify-horde --verify-ddc  (audit with connectivity checks)")


def _prompt_shader_preset(options: HordeHelperOptions) -> Dict[str, bool]:
    options.output("Distributed shader compile preset:")
    options.output("  1) Horde agent only")
    options.output("  2) XGE only")
    options.output("  3) Horde + XGE (recommended)")
    options.output("  4) Custom")
    options.output("  5) Skip")
    while True:
        resp = options.input("Preset [5]: ").strip()
        if not resp or resp == "5":
            return {}
        if resp == "3":
            return {
                "bAllowRemoteBuilds": True,
                "bUseHordeAgent": True,
                "bAllowXGE": True,
                "bAllowXGEShaderCompile": True,
            }
        if resp == "1":
            return {"bAllowRemoteBuilds": True, "bUseHordeAgent": True}
        if resp == "2":
            return {"bAllowXGE": True, "bAllowXGEShaderCompile": True}
        if resp == "4":
            return _prompt_custom_flags(options)
        options.output("Please choose 1, 2, 3, 4, or 5.")


def _prompt_custom_flags(options: HordeHelperOptions) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    keys = ["bAllowXGE", "bAllowRemoteBuilds", "bAllowXGEShaderCompile", "bUseHordeAgent"]
    for key in keys:
        prompt = f"{key} (y/n, blank to skip): "
        resp = options.input(prompt).strip().lower()
        if not resp:
            continue
        result[key] = resp in ("y", "yes", "true", "1")
    return result


def _prepare_build_updates(
    paths: Sequence[Path],
    desired_flags: Dict[str, bool],
    valid_keys: Sequence[str],
) -> List[BuildConfigUpdate]:
    return [plan_build_configuration_update(path, desired_flags, valid_keys) for path in paths]


def _prepare_ddc_updates(
    paths: Sequence[Path],
    *,
    shared_path: str,
    local_path: Optional[str],
    schema,
) -> List[DDCUpdate]:
    return [plan_ddc_update(path, shared_path=shared_path, local_path=local_path, schema=schema) for path in paths]


def _print_preview(
    options: HordeHelperOptions,
    *,
    build_updates: List[BuildConfigUpdate],
    ddc_updates: List[DDCUpdate],
    agent_update: Optional[HordeAgentConfigUpdate],
) -> None:
    any_changes = False
    for update in build_updates + ddc_updates:
        if update.after is None:
            continue
        options.output(f"\n--- Proposed change: {update.path}")
        diff = update.diff()
        if diff.strip():
            options.output(diff)
            any_changes = True
        else:
            options.output("No changes needed (already configured).")

    if agent_update and agent_update.after is not None:
        options.output(f"\n--- Proposed change: {agent_update.path}")
        diff = agent_update.diff()
        if diff.strip():
            options.output(diff)
            any_changes = True
        else:
            options.output("No changes needed (already configured).")

    if not any_changes:
        options.output("\nNothing to change; configuration already matches the requested settings.")


def _verify_horde_endpoint(endpoint: Optional[str]) -> Tuple[bool, str]:
    if not endpoint:
        return False, "No Horde endpoint configured."
    parsed = urlparse(endpoint)
    host = parsed.hostname
    port = parsed.port
    if not host and "://" not in endpoint:
        host, _, port_text = endpoint.partition(":")
        if port_text.isdigit():
            port = int(port_text)
    if not host:
        return False, "Unable to parse Horde endpoint."
    port = port or (443 if parsed.scheme in ("https", "") else 80)
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, f"Horde endpoint reachable: {host}:{port}"
    except OSError as exc:
        return False, f"Horde endpoint unreachable: {exc}"


def run_horde_setup_helper(options: HordeHelperOptions) -> HordeHelperOutcome:
    warnings: List[str] = []
    ue_root = options.ue_root
    if options.interactive:
        ue_root = _prompt_ue_root(options)

    apply_mode = options.apply
    if options.interactive and options.prompt_for_mode:
        apply_mode = _prompt_mode(options)

    horde_status = probe_horde_agent_status(ProbeContext(dry_run=True))
    agent_config = discover_agent_config()
    build_config = inspect_build_configuration(ue_root)
    ddc_detection = _collect_ddc_detection(ue_root)

    _print_audit_report(
        options,
        horde_status=horde_status,
        agent_config=agent_config,
        build_config=build_config,
        ddc=ddc_detection,
    )

    verify_horde = options.verify_horde
    verify_ddc = options.verify_ddc or options.verify_ddc_write_test
    if options.interactive and not verify_horde:
        verify_horde = _prompt_yes_no(options, "Verify Horde endpoint connectivity?", default=False)
    if options.interactive and not verify_ddc and ddc_detection.shared_path:
        verify_ddc = _prompt_yes_no(options, "Verify shared DDC access now?", default=False)
    if verify_horde:
        endpoint = agent_config.endpoint if agent_config else None
        ok, detail = _verify_horde_endpoint(endpoint)
        warnings.append(detail if ok else f"Verify Horde: {detail}")
    if verify_ddc and ddc_detection.shared_path:
        ok, detail, hints = verify_shared_ddc_path(
            ddc_detection.shared_path, write_test=options.verify_ddc_write_test
        )
        message = detail if ok else f"DDC verification failed: {detail}"
        warnings.append(message)
        for hint in hints:
            warnings.append(f"Hint: {hint}")

    if not apply_mode:
        _print_next_actions(options)
        return HordeHelperOutcome(
            applied=False,
            horde_status=_summarize_horde_status(horde_status),
            shader_status=_summarize_build_config(build_config),
            ddc_status=_summarize_ddc_detection(ddc_detection),
            warnings=warnings,
        )

    scope = _prompt_scope(options) if options.interactive else "user"
    if scope in ("engine", "both") and ue_root is None:
        warnings.append("Engine scope requested but UE root not provided.")
        scope = "user"

    endpoint_value = _prompt_optional_value("Horde endpoint", agent_config.endpoint if agent_config else None, options)
    pool_value = _prompt_optional_value("Horde pool", agent_config.pool if agent_config else None, options)
    shared_path = _prompt_optional_value("Shared DDC path", ddc_detection.shared_path, options)
    local_path = _prompt_optional_value("Local DDC path", ddc_detection.local_path, options)

    valid_keys = discover_xml_config_keys(ue_root)
    desired_flags: Dict[str, bool] = {}
    if valid_keys:
        desired_flags = _prompt_shader_preset(options)
    else:
        warnings.append("Unable to locate UBT XML config schema; skipping shader flag updates.")

    build_config_paths: List[Path] = []
    ddc_paths: List[Path] = []
    if scope in ("user", "both"):
        build_config_paths.append(user_build_configuration_path())
        ddc_paths.append(user_ddc_config_path())
    if scope in ("engine", "both") and ue_root:
        build_config_paths.append(engine_build_configuration_path(ue_root))
        ddc_paths.append(engine_ddc_config_path(ue_root))

    build_updates: List[BuildConfigUpdate] = []
    if desired_flags:
        build_updates = _prepare_build_updates(build_config_paths, desired_flags, sorted(valid_keys))
        for update in build_updates:
            warnings.extend(update.warnings)

    ddc_updates: List[DDCUpdate] = []
    ddc_schema = scan_ddc_schema(ue_root)
    warnings.extend(ddc_schema.warnings)
    validation: Optional[DDCValidationResult] = None
    if shared_path:
        if is_unc_path(shared_path):
            validation = DDCValidationResult(
                path=Path(shared_path),
                ok=True,
                created=False,
                latency_ms=None,
                message="UNC path not verified (skipped pre-check)",
            )
        else:
            allow_create = False
            if options.interactive and not Path(shared_path).exists():
                allow_create = _prompt_yes_no(options, f"{shared_path} does not exist. Create it?", default=False)
            validation = validate_ddc_path(Path(shared_path), allow_create=allow_create, dry_run=options.dry_run)
        if validation.message and not validation.ok:
            warnings.append(validation.message)
        if validation.ok and ddc_schema.usable:
            ddc_updates = _prepare_ddc_updates(
                ddc_paths, shared_path=shared_path, local_path=local_path, schema=ddc_schema
            )
            for update in ddc_updates:
                warnings.extend(update.warnings)
        elif not ddc_schema.usable:
            warnings.append("DDC schema unavailable; skipping DDC writes.")

    agent_update: Optional[HordeAgentConfigUpdate] = None
    if endpoint_value or pool_value:
        if agent_config:
            agent_update = plan_horde_agent_config_update(
                agent_config.path, endpoint=endpoint_value, pool=pool_value
            )
            warnings.extend(agent_update.warnings)
        else:
            warnings.append("No Horde agent config file found; skipping endpoint/pool update.")

    _print_preview(options, build_updates=build_updates, ddc_updates=ddc_updates, agent_update=agent_update)

    if options.interactive:
        proceed = _prompt_yes_no(options, "Apply these changes?", default=False)
    else:
        proceed = options.apply

    if not proceed or options.dry_run:
        return HordeHelperOutcome(
            applied=False,
            horde_status=_summarize_horde_status(horde_status),
            shader_status=_summarize_build_config(build_config),
            ddc_status=_summarize_ddc_detection(ddc_detection),
            warnings=warnings,
            changes=[u.path.as_posix() for u in build_updates + ddc_updates if u.after],
        )

    for update in build_updates:
        if update.changed:
            apply_build_configuration_update(update, dry_run=options.dry_run)
    for update in ddc_updates:
        if update.changed:
            apply_ddc_update(update, dry_run=options.dry_run)
    if agent_update and agent_update.changed:
        apply_horde_agent_config_update(agent_update, dry_run=options.dry_run)

    if shared_path and validation and ddc_schema.usable:
        ddc_status = summarize_ddc_status(shared_path, local_path, validation)
    elif shared_path:
        ddc_status = f"DDC prepared: shared={shared_path}"
    else:
        ddc_status = "DDC skipped"

    if verify_horde:
        ok, detail = _verify_horde_endpoint(endpoint_value or (agent_config.endpoint if agent_config else None))
        warnings.append(detail if ok else f"Verify Horde: {detail}")

    if verify_ddc and shared_path:
        ok, detail, hints = verify_shared_ddc_path(shared_path, write_test=options.verify_ddc_write_test)
        message = detail if ok else f"DDC verification failed: {detail}"
        warnings.append(message)
        for hint in hints:
            warnings.append(f"Hint: {hint}")
    elif shared_path and is_unc_path(shared_path):
        warnings.append("UNC path not verified; rerun with --verify-ddc to test access.")

    return HordeHelperOutcome(
        applied=True,
        horde_status=_summarize_horde_status(horde_status),
        shader_status=_summarize_build_config(build_config),
        ddc_status=ddc_status,
        warnings=warnings,
        changes=[u.path.as_posix() for u in build_updates + ddc_updates if u.changed],
    )
