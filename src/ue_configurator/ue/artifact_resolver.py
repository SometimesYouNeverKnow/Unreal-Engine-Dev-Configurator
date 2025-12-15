"""Locate UE engine build artifacts with flexible search semantics."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Protocol, Sequence


PATTERNS: Dict[str, Sequence[str]] = {
    "CrashReportClient": ("CrashReportClient*.exe",),
    "UnrealPak": ("UnrealPak*.exe",),
    "ShaderCompileWorker": ("ShaderCompileWorker*.exe",),
    "UnrealEditor": ("UnrealEditor*.exe",),
}


class BuildTargetLike(Protocol):
    name: str

    def binary_path(self, ue_root: Path) -> Path:
        ...


@dataclass
class ArtifactResolution:
    target: BuildTargetLike
    canonical: Path
    resolved: Path | None
    found_via_search: bool
    pattern: str
    candidates: List[Path] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.resolved is not None and self.resolved.exists()


class ArtifactResolver:
    """Resolves engine artifacts, falling back to bounded search."""

    def __init__(self, ue_root: Path, cache_path: Path | None = None) -> None:
        self.ue_root = Path(ue_root)
        self.cache_path = cache_path or Path("reports") / "uecfg_artifacts_cache.json"
        self._cache = self._load_cache()

    def resolve(self, target: BuildTargetLike) -> ArtifactResolution:
        canonical = target.binary_path(self.ue_root)
        pattern = PATTERNS.get(target.name, (f"{target.name}*.exe",))[0]
        # Canonical quick hit
        if canonical.exists():
            return ArtifactResolution(
                target=target,
                canonical=canonical,
                resolved=canonical,
                found_via_search=False,
                pattern=pattern,
            )

        cached = self._get_cached_path(target)
        if cached and cached.exists():
            return ArtifactResolution(
                target=target,
                canonical=canonical,
                resolved=cached,
                found_via_search=True,
                pattern=pattern,
            )

        engine_root = self.ue_root / "Engine"
        candidates: List[Path] = []
        if engine_root.exists():
            for glob in PATTERNS.get(target.name, (pattern,)):
                for match in engine_root.rglob(glob):
                    if match.is_file():
                        candidates.append(match)

        resolved = None
        if candidates:
            resolved = sorted(candidates, key=lambda path: self._score_candidate(path))[0]
            self._set_cache_path(target, resolved)

        return ArtifactResolution(
            target=target,
            canonical=canonical,
            resolved=resolved,
            found_via_search=resolved is not None,
            pattern=pattern,
            candidates=candidates[:5],
        )

    # Internal helpers
    def _score_candidate(self, path: Path) -> tuple:
        """Prefer shortest relative path; prefer Engine/Binaries/Win64 on ties."""
        try:
            rel = path.relative_to(self.ue_root)
        except ValueError:
            rel = path
        rel_parts = len(rel.parts)
        lowered = [part.lower() for part in rel.parts]
        in_canonical_dir = "engine" in lowered and "binaries" in lowered and "win64" in lowered
        return (rel_parts, 0 if in_canonical_dir else 1, str(rel).lower())

    def _load_cache(self) -> Dict[str, Dict[str, str]]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except OSError:
            return

    def _cache_key(self) -> str:
        return os.path.normcase(str(self.ue_root.resolve()))

    def _get_cached_path(self, target: BuildTargetLike) -> Path | None:
        root_key = self._cache_key()
        entry = self._cache.get(root_key, {}).get(target.name)
        if not entry:
            return None
        path = Path(entry)
        return path if path.exists() else None

    def _set_cache_path(self, target: BuildTargetLike, path: Path) -> None:
        root_key = self._cache_key()
        self._cache.setdefault(root_key, {})[target.name] = str(path)
        self._save_cache()
