from __future__ import annotations

from pathlib import Path
from typing import Any

from repooperator_worker.config import get_settings
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.common import resolve_project_path


def discover_skills() -> dict[str, Any]:
    paths = _skill_paths()
    skills: list[dict[str, Any]] = []
    for scope, path in paths:
        if path.exists() and path.is_file():
            skills.extend(_parse_skills_file(path, scope))

    layered: dict[str, dict[str, Any]] = {}
    for skill in skills:
        layered[f"{skill['source_path']}::{skill['name']}"] = skill
    return {"skills": list(layered.values())}


def enabled_skill_context(max_chars: int = 2_000) -> tuple[str, list[str]]:
    discovered = discover_skills()["skills"]
    enabled = [skill for skill in discovered if skill.get("enabled")]
    if not enabled:
        return "", []
    blocks: list[str] = []
    used: list[str] = []
    remaining = max_chars
    for skill in enabled:
        description = skill.get("description") or ""
        block = (
            f"- {skill.get('name')} ({skill.get('scope')}): "
            f"{description[:500]}"
        ).strip()
        if len(block) > remaining:
            break
        blocks.append(block)
        used.append(str(skill.get("name")))
        remaining -= len(block)
    if not blocks:
        return "", []
    return "Enabled repository skills:\n" + "\n".join(blocks), used


def _skill_paths() -> list[tuple[str, Path]]:
    settings = get_settings()
    paths: list[tuple[str, Path]] = []
    active = get_active_repository()
    if active:
        try:
            repo_root = resolve_project_path(active.project_path)
            paths.append(("repo", repo_root / "skills.md"))
            paths.append(("repo", repo_root / ".repooperator" / "skills.md"))
        except Exception:
            pass

    home = settings.repooperator_home_dir
    paths.append(("user", home / "skills.md"))
    skills_dir = home / "skills"
    if skills_dir.exists():
        paths.extend(("user", path) for path in sorted(skills_dir.glob("*.md")))
    return paths


def _parse_skills_file(path: Path, scope: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    skills: list[dict[str, Any]] = []
    current_name: str | None = None
    current_desc: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_name:
                skills.append(_skill_payload(path, scope, current_name, current_desc))
            current_name = stripped.lstrip("#").strip() or path.stem
            current_desc = []
        elif current_name and stripped:
            current_desc.append(stripped)
    if current_name:
        skills.append(_skill_payload(path, scope, current_name, current_desc))
    elif lines:
        skills.append(_skill_payload(path, scope, path.stem, lines[:6]))
    return skills


def _skill_payload(path: Path, scope: str, name: str, description_lines: list[str]) -> dict[str, Any]:
    description = " ".join(line.strip() for line in description_lines if line.strip())
    return {
        "name": name,
        "source_path": str(path),
        "scope": scope,
        "description": description[:700],
        "enabled": True,
    }
