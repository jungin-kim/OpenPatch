from __future__ import annotations

from pathlib import Path
from typing import Any

from repooperator_worker.config import get_settings
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.common import resolve_project_path

# Built-in skills are always loaded; user/repo skills with the same name override them.
BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "name": "Git Workflow",
        "source_path": "__builtin__",
        "source_type": "builtin",
        "scope": "builtin",
        "enabled": True,
        "description": "Standard Git workflow: branch, commit, push, and PR/MR creation.",
        "body": """\
## Git Workflow

When the user asks to commit, push, or open a pull request, follow this sequence:

1. **Check status** — `git status` and `git diff --stat` to understand what changed.
2. **Stage changes** — `git add <specific files>` (avoid `git add .` unless all changes are intentional).
3. **Commit** — `git commit -m "<type>: <short description>"` where type is feat/fix/refactor/docs/chore.
4. **Push** — `git push origin <branch>` (or `git push -u origin <branch>` for a new branch).
5. **Open PR/MR** — use `gh pr create` (GitHub) or `glab mr create` (GitLab) with a descriptive title and body.

Rules:
- Never force-push to main/master without explicit user confirmation.
- Always check that tests pass before committing if a test command is known.
- If the branch does not exist on remote, push with `-u` to set upstream.
- Include a co-authored-by line when appropriate.
- Prefer small, focused commits over large omnibus commits.
""",
    },
    {
        "name": "GitLab Workflow",
        "source_path": "__builtin__",
        "source_type": "builtin",
        "scope": "builtin",
        "enabled": True,
        "description": "GitLab-specific workflow: MR creation, CI/CD, issue linking.",
        "body": """\
## GitLab Workflow

For GitLab projects, follow this workflow:

1. **Create a branch** from the default branch (usually `main` or `master`):
   `git checkout -b <type>/<short-description>`
2. **Make changes**, commit with `git commit -m "<type>: <description>"`.
3. **Push** with `git push -u origin <branch>`.
4. **Open an MR** using `glab mr create --title "<title>" --description "<body>" --target-branch main`.
   - Add `--draft` if the MR is not ready for review.
   - Add `--label "label1,label2"` as appropriate.
   - Add `--assignee @me` to self-assign.
5. **Link to an issue**: include `Closes #<issue_number>` in the MR description to auto-close the issue on merge.
6. **CI/CD**: after pushing, monitor pipeline status with `glab ci view` or check the MR page.

Rules:
- MR titles follow Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Keep MR scope focused; avoid mixing unrelated changes.
- Do not merge without at least one approval unless the project policy allows.
- Use `--squash` when merging to keep history clean, unless project convention differs.
""",
    },
]


def discover_skills() -> dict[str, Any]:
    # Start with built-ins; user/repo skills override by name (case-insensitive).
    layered: dict[str, dict[str, Any]] = {}
    for skill in BUILTIN_SKILLS:
        layered[skill["name"].lower()] = skill

    paths = _skill_paths()
    for scope, path, source_type in paths:
        if path.exists() and path.is_file():
            for skill in _parse_skills_file(path, scope, source_type):
                layered[skill["name"].lower()] = skill

    return {"skills": list(layered.values())}


def enabled_skill_context(max_chars: int = 4_000) -> tuple[str, list[str]]:
    discovered = discover_skills()["skills"]
    enabled = [skill for skill in discovered if skill.get("enabled")]
    if not enabled:
        return "", []
    blocks: list[str] = []
    used: list[str] = []
    remaining = max_chars
    for skill in enabled:
        # Prefer full body for richer planner context; fall back to description.
        body = skill.get("body") or skill.get("description") or ""
        header = f"### Skill: {skill.get('name')} ({skill.get('scope')})\n"
        block = header + body.strip()
        if len(block) > remaining:
            # Try a truncated version using just description.
            desc = skill.get("description") or ""
            block = (header + desc[:400]).strip()
            if len(block) > remaining:
                break
        blocks.append(block)
        used.append(str(skill.get("name")))
        remaining -= len(block)
    if not blocks:
        return "", []
    return "Enabled repository skills:\n\n" + "\n\n---\n\n".join(blocks), used


def _skill_paths() -> list[tuple[str, Path, str]]:
    settings = get_settings()
    paths: list[tuple[str, Path, str]] = []
    active = get_active_repository()
    if active:
        try:
            repo_root = resolve_project_path(active.project_path)
            paths.append(("repo", repo_root / "skills.md", "repo"))
            paths.append(("repo", repo_root / ".repooperator" / "skills.md", "repo"))
        except Exception:
            pass

    home = settings.repooperator_home_dir
    paths.append(("user", home / "skills.md", "user"))
    skills_dir = home / "skills"
    if skills_dir.exists():
        paths.extend(("user", path, "user") for path in sorted(skills_dir.glob("*.md")))
    return paths


def _parse_skills_file(path: Path, scope: str, source_type: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    skills: list[dict[str, Any]] = []
    current_name: str | None = None
    current_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_name:
                skills.append(_skill_payload(path, scope, source_type, current_name, current_lines))
            current_name = stripped.lstrip("#").strip() or path.stem
            current_lines = []
        elif current_name:
            current_lines.append(line)
    if current_name:
        skills.append(_skill_payload(path, scope, source_type, current_name, current_lines))
    elif lines:
        skills.append(_skill_payload(path, scope, source_type, path.stem, lines[:6]))
    return skills


def _skill_payload(
    path: Path, scope: str, source_type: str, name: str, body_lines: list[str]
) -> dict[str, Any]:
    body = "\n".join(body_lines).strip()
    # First non-empty line is used as the short description.
    description = next((l.strip() for l in body_lines if l.strip()), "")[:700]
    return {
        "name": name,
        "source_path": str(path),
        "source_type": source_type,
        "scope": scope,
        "description": description,
        "body": body[:3000],
        "enabled": True,
    }
