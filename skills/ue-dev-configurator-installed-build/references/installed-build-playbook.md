# Installed Build Playbook

Use these commands when you need deterministic Unreal Engine Installed Build outputs.

## A) Verify and pin UE source commit/tag

```powershell
cd H:\UEGit\UnrealEngine
git fetch --tags --prune origin
git tag -l "5.7.*-release"
git rev-parse 5.7.2-release
git switch --detach 5.7.2-release
git rev-parse HEAD
```

Optional branch for local clarity:

```powershell
git switch -c pin/5.7.2-release
```

## B) Clean only what matters before rebuild

```powershell
cd H:\UEGit\UnrealEngine
# Keep downloaded dependencies; remove generated build artifacts.
Remove-Item -Recurse -Force Engine\Intermediate,Engine\Saved -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force LocalBuilds\Engine -ErrorAction SilentlyContinue
```

Run setup/generation:

```powershell
.\Setup.bat
.\GenerateProjectFiles.bat
```

## C) Build Installed Engine to explicit path

Horde-first policy:
- Keep machine-specific endpoint, pool, and launcher paths in a local non-repo file.
- Preferred behavior: use Horde when reachable; if unreachable, start local Horde agent and retry once; if still unavailable, continue with local build.
- Example local profile path (not committed): `%USERPROFILE%\Desktop\horde-profile.local.ps1`

Optional pre-step using local profile values:

```powershell
. "$env:USERPROFILE\Desktop\horde-profile.local.ps1"
cd "$env:HORDE_AGENT_DIR"
dotnet HordeAgent.dll SetServer -Name=main -Url=$env:HORDE_SERVER_URL -Default
```

If the service/agent is not running, start it from your local launcher path:

```powershell
. "$env:USERPROFILE\Desktop\horde-profile.local.ps1"
Start-Process $env:HORDE_AGENT_LAUNCHER
```

Run Horde readiness check:

```powershell
cd H:\UEGit\Truthweaver\Unreal-Engine-Dev-Configurator
python -m ue_configurator.cli scan --phase 3 --ue-root H:\UEGit\UnrealEngine --no-color
```

Then run Installed Build:

```powershell
cd H:\UEGit\UnrealEngine
$InstalledDir = 'H:\UE_Installed\UE_5.7.2'
.\Engine\Build\BatchFiles\RunUAT.bat BuildGraph `
  -Target="Make Installed Build Win64" `
  -Script="Engine\Build\InstalledEngineBuild.xml" `
  -set:WithWin64=true `
  -set:WithLinux=false `
  -set:WithServer=false `
  -set:WithClient=false `
  -set:WithDDC=false `
  -set:SignExecutables=false `
  -set:EmbedSrcSrvInfo=false `
  -set:InstalledDir="$InstalledDir"
```

## D) Publish/pull installed build with built-in tooling

Publish from source machine:

```powershell
cd H:\UEGit\Truthweaver\Unreal-Engine-Dev-Configurator
python -m ue_configurator.cli installed-build publish `
  --publish-root-path "\\BUILD-SERVER\UEInstalled" `
  --build-id "UE_5.7.2" `
  --source-installed-build-path "H:\UE_Installed\UE_5.7.2\Windows" `
  --unreal-source-path "H:\UEGit\UnrealEngine" `
  --shared-ddc-path "\\DDC-SERVER\UnrealDDC" `
  --engine-association-guid "{005B8658-4955-59D7-26D9-9CA0B081B6AA}"
```

Pull on target machine and install settings:

```powershell
cd H:\UEGit\Truthweaver\Unreal-Engine-Dev-Configurator
python -m ue_configurator.cli installed-build pull `
  --publish-root-path "\\BUILD-SERVER\UEInstalled" `
  --build-id "UE_5.7.2" `
  --destination-installed-build-path "H:\UE_Installed\UE_5.7.2\Windows" `
  --apply-engine-association
```

## E) Validate project against installed build

```powershell
$env:UE_ROOT = 'H:\UE_Installed\UE_5.7.2'
cd H:\UEGit\EpochRift_Codex
# If needed: regenerate project files using the installed engine's UnrealVersionSelector/UBT flow.
# Build example (adjust target names):
& "$env:UE_ROOT\Engine\Build\BatchFiles\Build.bat" EpochRiftEditor Win64 Development "H:\UEGit\EpochRift_Codex\EpochRift.uproject" -WaitMutex -NoHotReload
```

## F) Evidence to record in issue/PR

- UE tag: `5.7.2-release`
- UE commit SHA: output of `git rev-parse HEAD`
- Installed build output path: `H:\UE_Installed\UE_5.7.2`
- Preflight result: output of `python -m ue_configurator.cli scan --phase 0 --phase 1 --ue-version 5.7 --no-color`
- Horde readiness result: output of `python -m ue_configurator.cli scan --phase 3 --ue-root H:\UEGit\UnrealEngine --no-color`
- Validation build command and exit status
