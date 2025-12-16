"""Helpers for reading and writing BuildConfiguration.xml in a safe, idempotent way."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def _parse_bool(text: str) -> bool:
    return text.strip().lower() in ("true", "1", "yes")


def parse_build_configuration_flags(xml_text: str) -> Dict[str, bool]:
    """Extract distributed build flags from BuildConfiguration.xml."""

    flags: Dict[str, bool] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return flags
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if elem.text:
            flags[tag] = _parse_bool(elem.text)
    return flags


def _indent(elem: ET.Element, level: int = 0) -> None:
    """Apply pretty indentation to an ElementTree tree in-place."""

    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():  # type: ignore[name-defined]
            child.tail = i  # type: ignore[name-defined]
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def _ensure_section(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    ns = ""
    if root.tag.startswith("{") and "}" in root.tag:
        ns = root.tag.split("}", 1)[0] + "}"
    config = root.find(f"{ns}BuildConfiguration")
    if config is None:
        config = ET.SubElement(root, f"{ns}BuildConfiguration")
    return config


def _create_default_tree() -> ET.ElementTree:
    root = ET.Element("Configuration", {"xmlns": "https://www.unrealengine.com/BuildConfiguration"})
    ET.SubElement(root, "BuildConfiguration")
    return ET.ElementTree(root)


def _set_flags(section: ET.Element, updates: Dict[str, bool]) -> List[str]:
    changed: List[str] = []
    for key, value in updates.items():
        existing = None
        for elem in section.iter():
            tag = elem.tag
            if "}" in tag:
                tag = tag.split("}", 1)[1]
            if tag == key:
                existing = elem
                break
        if existing is None:
            existing = ET.SubElement(section, key)
        text_value = "true" if value else "false"
        if (existing.text or "").strip().lower() != text_value:
            existing.text = text_value
            changed.append(key)
    return changed


def _timestamped_backup_path(path: Path) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_suffix(path.suffix + f".{stamp}.bak")


def _render_xml(tree: ET.ElementTree) -> str:
    root = tree.getroot()
    _indent(root)
    return ET.tostring(root, encoding="unicode")


@dataclass
class BuildConfigUpdate:
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


def plan_build_configuration_update(
    path: Path,
    updates: Dict[str, bool],
    valid_keys: Iterable[str],
) -> BuildConfigUpdate:
    """Prepare a deterministic BuildConfiguration.xml update without touching disk."""

    filtered_updates = {k: v for k, v in updates.items() if k in set(valid_keys)}
    missing = sorted(set(updates) - set(filtered_updates))
    warnings: List[str] = []
    if missing:
        warnings.append(f"Skipped unsupported keys: {', '.join(missing)}")

    before_text = None
    if path.exists():
        try:
            before_text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            warnings.append(f"Unable to read {path}: {exc}")
            before_text = ""

    if before_text:
        existing_flags = parse_build_configuration_flags(before_text)
        if all(existing_flags.get(key) == value for key, value in filtered_updates.items()):
            return BuildConfigUpdate(
                path=path,
                before=before_text,
                after=before_text,
                changed_keys=[],
                warnings=warnings,
            )

    if not filtered_updates and before_text is None:
        warnings.append("No supported BuildConfiguration keys to write.")
        return BuildConfigUpdate(path=path, before=None, after=None, changed_keys=[], warnings=warnings)

    if not filtered_updates and before_text is not None:
        return BuildConfigUpdate(
            path=path,
            before=before_text,
            after=before_text,
            changed_keys=[],
            warnings=warnings,
        )

    tree = None
    if before_text:
        try:
            tree = ET.ElementTree(ET.fromstring(before_text))
        except ET.ParseError:
            warnings.append(f"Existing BuildConfiguration.xml at {path} is not valid XML; replacing content.")

    if tree is None:
        tree = _create_default_tree()

    section = _ensure_section(tree)
    changed_keys = _set_flags(section, filtered_updates)
    after_text = _render_xml(tree)

    return BuildConfigUpdate(
        path=path,
        before=before_text,
        after=after_text,
        changed_keys=changed_keys,
        warnings=warnings,
    )


def apply_build_configuration_update(update: BuildConfigUpdate, *, dry_run: bool, backup: bool = True) -> BuildConfigUpdate:
    """Apply a planned BuildConfiguration.xml update with optional backup."""

    if not update.after:
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
