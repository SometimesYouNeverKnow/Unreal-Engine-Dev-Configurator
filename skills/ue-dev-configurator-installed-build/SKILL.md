---
name: ue-dev-configurator-installed-build
description: Use this skill when preparing or maintaining deterministic Unreal Engine source-to-installed-build workflows on Windows with the Unreal Engine Dev Configurator repo. Apply it when Codex must pin a specific UE commit/tag, verify machine prerequisites (including pdbcopy.exe), run uecfg scans/setup guidance, prefer Horde-distributed builds with local fallback, generate an Installed Build to a fixed output path, and document repeatable commands for CI or additional machines like Omen.
---

# UE Dev Configurator Installed Build

Follow this workflow to avoid engine state drift across developer machines and CI.

## 1. Establish context and pin

1. Confirm you are in `Unreal-Engine-Dev-Configurator` and collect machine evidence.
- `git status --short --branch`
- `python -m ue_configurator.cli scan --phase 0 --phase 1 --ue-version 5.7 --no-color`
2. Resolve the target Unreal Engine tag/commit first, then pin explicitly in the UE source clone.
- Use a detached commit or a dedicated branch named for the tag, for example `pin/5.7.2-release`.
3. Never rely on floating refs like `origin/release` in CI.

## 2. Run deterministic preflight with uecfg only

1. Run `python -m ue_configurator.cli scan --phase 0 --phase 1 --ue-version 5.7 --no-color` before any full engine build.
2. If prerequisites fail, use `python -m ue_configurator.cli setup --plan --phase 1 --ue-version 5.7 --no-color` and then apply in an elevated shell.
3. Do not add ad hoc prerequisite scripts inside this skill to compensate for missing checks.
4. If this skill requires a check that `uecfg` does not implement, raise a gap flag in repo tracking and update `uecfg` probes first, then update this skill to point to the new built-in check.

## 3. Build and install engine output

1. Use the pinned UE source clone only for building.
2. Produce the Installed Build to a versioned path outside the source tree, for example `H:\UE_Installed\UE_5.7.2`.
3. Prefer Horde-distributed execution first, then local build fallback when Horde server/agents are unavailable.
4. Use `uecfg installed-build publish` and `uecfg installed-build pull` for cross-machine transfer so copy, manifest, hash checks, and settings install are standardized.
5. Use BuildGraph Installed Build workflow over ad hoc editor-only build commands.
6. Use explicit command lines and explicit output directories in logs and docs.

Reference command templates live in `references/installed-build-playbook.md`.

## 4. Validate downstream project

1. Build at least one downstream UE project against the Installed Build path.
2. Verify project engine association and CI environment variables reference the same Installed Build path.
3. Record the pinned commit SHA, output path, and validation result in issue/PR notes.

## 5. Cross-machine replication

1. Re-run preflight and `uecfg` scans on each machine.
2. Reuse the same pinned commit SHA and Installed Build output naming convention.
3. Fail fast if machine prerequisites differ from manifest expectations.
4. Keep Horde endpoint and pool configuration consistent across machines.

## Resources

- `references/installed-build-playbook.md`: command templates for pin, clean, BuildGraph Installed Build, and downstream validation.
