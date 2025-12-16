"""Interactive workflow for configuring shared DDC and distributed shader builds."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ue_configurator.ue.build_config import (
    BuildConfigUpdate,
    apply_build_configuration_update,
    parse_build_configuration_flags,
    plan_build_configuration_update,
)
from ue_configurator.ue.config_paths import (
    default_local_ddc_path,
    default_shared_ddc_suggestion,
    engine_build_configuration_path,
    engine_ddc_config_path,
    user_build_configuration_path,
    user_ddc_config_path,
)
from ue_configurator.ue.ddc_config import (
    DDCUpdate,
    scan_ddc_schema,
    validate_ddc_path,
    apply_ddc_update,
    plan_ddc_update,
    summarize_ddc_status,
)
from ue_configurator.ue.ubt_config_schema import discover_xml_config_keys


InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


@dataclass
class WorkflowOptions:
    ue_root: Optional[Path]
    dry_run: bool
    apply: bool
    verbose: bool
    interactive: bool
    input: InputFunc = input
    output: PrintFunc = print
    default_shared: Optional[str] = None
    default_local: Optional[Path] = None


@dataclass
class ConfigurationOutcome:
    applied: bool
    ddc_status: str
    shader_status: str
    warnings: List[str] = field(default_factory=list)
    changes: List[str] = field(default_factory=list)


def _prompt_scope(options: WorkflowOptions) -> str:
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


def _prompt_path(prompt: str, default: Optional[str], options: WorkflowOptions) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        resp = options.input(f"{prompt}{suffix}: ").strip().strip('"')
        if not resp and default:
            return default
        if resp:
            return resp
        options.output("A path is required.")


def _prompt_allow_create(path: Path, options: WorkflowOptions) -> bool:
    if not options.interactive:
        return False
    resp = options.input(f"{path} does not exist. Create it? [y/N] ").strip().lower()
    return resp in ("y", "yes")


def _prompt_local_fallback(default: Path, options: WorkflowOptions) -> Optional[str]:
    suffix = f" [{default}]" if default else ""
    resp = options.input(f"Local DDC fallback (blank to skip){suffix}: ").strip().strip('"')
    if not resp:
        return str(default)
    if resp.lower() in ("skip", "none"):
        return None
    return resp


def _prompt_flag_overrides(
    recommended: Dict[str, bool],
    *,
    options: WorkflowOptions,
    valid_keys: Sequence[str],
) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for key, value in recommended.items():
        if key not in valid_keys:
            options.output(f"[warn] {key} not present in UBT schema; skipping.")
            continue
        if not options.interactive:
            result[key] = value
            continue
        resp = options.input(f"{key} (enter to accept {value}, 'skip' to omit): ").strip().lower()
        if not resp:
            result[key] = value
            continue
        if resp in ("skip", "s"):
            continue
        result[key] = resp in ("1", "true", "yes", "y")
    return result


def _describe_flags(flags: Dict[str, bool]) -> str:
    if not flags:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(flags.items()))


def _summarize_existing_flags(paths: List[Path]) -> List[str]:
    lines: List[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        flags = parse_build_configuration_flags(text)
        if not flags:
            continue
        lines.append(f"{path}: {_describe_flags(flags)}")
    return lines


def _prepare_build_config_plans(
    *,
    paths: List[Path],
    desired_flags: Dict[str, bool],
    valid_keys: Sequence[str],
) -> List[BuildConfigUpdate]:
    plans: List[BuildConfigUpdate] = []
    for path in paths:
        plans.append(plan_build_configuration_update(path, desired_flags, valid_keys))
    return plans


def _prepare_ddc_plans(
    *,
    paths: List[Path],
    shared_path: str,
    local_path: Optional[str],
    schema,
) -> List[DDCUpdate]:
    plans: List[DDCUpdate] = []
    for path in paths:
        plans.append(plan_ddc_update(path, shared_path=shared_path, local_path=local_path, schema=schema))
    return plans


def _print_preview(updates: List[BuildConfigUpdate], ddc_updates: List[DDCUpdate], options: WorkflowOptions) -> None:
    any_changes = False
    for update in updates:
        if update.after is None:
            continue
        options.output(f"\n--- Proposed change: {update.path}")
        diff = update.diff()
        if diff.strip():
            options.output(diff)
            any_changes = True
        else:
            options.output("No changes needed (already configured).")
    for update in ddc_updates:
        if update.after is None:
            continue
        options.output(f"\n--- Proposed change: {update.path}")
        diff = update.diff()
        if diff.strip():
            options.output(diff)
            any_changes = True
        else:
            options.output("No changes needed (already configured).")
    if not any_changes:
        options.output("\nNothing to change; configuration already matches the requested settings.")


def configure_ddc_and_shaders(options: WorkflowOptions) -> ConfigurationOutcome:
    default_shared = options.default_shared or default_shared_ddc_suggestion()
    default_local = options.default_local or default_local_ddc_path()
    scope = _prompt_scope(options) if options.interactive else "user"

    ue_root = options.ue_root
    if scope in ("engine", "both") and ue_root is None and options.interactive:
        entered = options.input("UE root path is required for engine-global scope: ").strip().strip('"')
        ue_root = Path(entered) if entered else None
    if scope in ("engine", "both") and ue_root is None:
        return ConfigurationOutcome(
            applied=False,
            ddc_status="DDC: skipped (no UE root)",
            shader_status="Shaders: skipped (no UE root)",
            warnings=["Engine-global scope requested but UE root missing."],
        )

    shared_path_text = _prompt_path("Shared DDC path", default_shared, options) if options.interactive else (
        default_shared or ""
    )
    local_path_text = _prompt_local_fallback(default_local, options) if options.interactive else str(default_local)

    allow_create = True if (shared_path_text and Path(shared_path_text).exists()) else _prompt_allow_create(
        Path(shared_path_text), options
    )
    validation = validate_ddc_path(Path(shared_path_text), allow_create=allow_create, dry_run=options.dry_run)
    warnings: List[str] = []
    if validation.message and not validation.ok:
        warnings.append(validation.message)
    if not validation.ok:
        return ConfigurationOutcome(
            applied=False,
            ddc_status=f"DDC: {validation.message}",
            shader_status="Shaders: skipped",
            warnings=warnings if isinstance(warnings, list) else [validation.message],
        )

    valid_keys = discover_xml_config_keys(ue_root)
    recommended_flags = {
        "bAllowXGE": True,
        "bAllowRemoteBuilds": True,
        "bAllowXGEShaderCompile": True,
        "bUseHordeAgent": True,
    }
    desired_flags = _prompt_flag_overrides(recommended_flags, options=options, valid_keys=sorted(valid_keys))
    if not valid_keys:
        warnings.append("Unable to locate UBT XML config schema; distributed shader settings may be skipped.")

    build_config_paths: List[Path] = []
    ddc_paths: List[Path] = []
    if scope in ("user", "both"):
        build_config_paths.append(user_build_configuration_path())
        ddc_paths.append(user_ddc_config_path())
    if scope in ("engine", "both") and ue_root:
        build_config_paths.append(engine_build_configuration_path(ue_root))
        ddc_paths.append(engine_ddc_config_path(ue_root))

    ddc_schema = scan_ddc_schema(ue_root)
    warnings.extend(ddc_schema.warnings)
    build_updates = _prepare_build_config_plans(
        paths=build_config_paths,
        desired_flags=desired_flags,
        valid_keys=sorted(valid_keys),
    )
    ddc_updates = _prepare_ddc_plans(
        paths=ddc_paths,
        shared_path=shared_path_text,
        local_path=local_path_text,
        schema=ddc_schema,
    )
    for update in build_updates:
        warnings.extend(update.warnings)
    for update in ddc_updates:
        warnings.extend(update.warnings)

    if options.verbose:
        existing = _summarize_existing_flags(build_config_paths)
        if existing:
            options.output("Existing distributed shader flags:")
            for line in existing:
                options.output(f"  {line}")

    _print_preview(build_updates, ddc_updates, options)
    if options.interactive:
        proceed = options.input("\nApply these changes? [y/N] ").strip().lower() in ("y", "yes")
    else:
        proceed = options.apply
    if not proceed or options.dry_run:
        return ConfigurationOutcome(
            applied=False,
            ddc_status=summarize_ddc_status(shared_path_text, local_path_text, validation)
            if ddc_schema.usable
            else f"DDC: prepared (shared={shared_path_text})",
            shader_status=f"Shaders: prepared ({_describe_flags(desired_flags)})",
            warnings=warnings,
            changes=[u.diff() for u in build_updates + ddc_updates if u.after],
        )

    for update in build_updates:
        apply_build_configuration_update(update, dry_run=options.dry_run)
    for update in ddc_updates:
        apply_ddc_update(update, dry_run=options.dry_run)

    shader_status = f"Shaders: configured ({_describe_flags(desired_flags)})" if desired_flags else "Shaders: configured"
    if not desired_flags:
        shader_status = "Shaders: skipped (no supported keys found)"
    if not valid_keys:
        shader_status = "Shaders: skipped (UBT schema unavailable)"
    if ddc_schema.usable:
        ddc_status = summarize_ddc_status(shared_path_text, local_path_text, validation)
    else:
        ddc_status = "DDC: skipped (unknown keys)"
    return ConfigurationOutcome(
        applied=True,
        ddc_status=ddc_status,
        shader_status=shader_status,
        warnings=warnings,
        changes=[u.path.as_posix() for u in build_updates + ddc_updates if u.after],
    )
