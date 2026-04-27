from dataclasses import dataclass
from pathlib import Path

from openpatch_worker.services.common import ensure_git_repository, resolve_project_path
from openpatch_worker.services.subprocess_utils import run_subprocess

MAX_README_CHARS = 4_000
MAX_DIFF_CHARS = 6_000
MAX_FILE_LIST = 20


@dataclass(frozen=True)
class MinimalRepoContext:
    repo_path_value: str
    repo_root_name: str
    branch: str
    top_level_entries: list[str]
    git_status_excerpt: str
    readme_excerpt: str
    diff_excerpt: str
    summary: str
    prompt_context: str


def build_minimal_repo_context(repo_path_value: str) -> MinimalRepoContext:
    repo_path = resolve_project_path(repo_path_value)
    ensure_git_repository(repo_path)

    branch = _safe_git_output(repo_path, ["git", "branch", "--show-current"]) or "unknown"
    status = _safe_git_output(repo_path, ["git", "status", "--short"]) or "(clean)"
    top_level_files = _list_top_level_entries(repo_path)
    readme_excerpt = _read_readme_excerpt(repo_path)
    diff_excerpt = _safe_git_output(repo_path, ["git", "diff"])[:MAX_DIFF_CHARS]

    summary = (
        f"Repo '{repo_path_value}' on branch '{branch}' with "
        f"{len(top_level_files)} top-level entries and "
        f"{'a non-empty' if diff_excerpt else 'no'} working diff."
    )

    context_parts = [
        f"Repository path: {repo_path_value}",
        f"Current branch: {branch}",
        "Top-level entries:",
        "\n".join(f"- {entry}" for entry in top_level_files) or "- (none)",
        "Git status (--short):",
        status,
    ]

    if readme_excerpt:
        context_parts.extend(
            [
                "README excerpt:",
                readme_excerpt,
            ]
        )

    if diff_excerpt:
        context_parts.extend(
            [
                "Working diff excerpt:",
                diff_excerpt,
            ]
        )

    # TODO: Replace these fixed heuristics with targeted file selection based on the task.
    # TODO: Add optional explicit file hints so the worker can gather tighter context on demand.
    return MinimalRepoContext(
        repo_path_value=repo_path_value,
        repo_root_name=repo_path.name,
        branch=branch,
        top_level_entries=top_level_files,
        git_status_excerpt=status,
        readme_excerpt=readme_excerpt,
        diff_excerpt=diff_excerpt,
        summary=summary,
        prompt_context="\n\n".join(context_parts),
    )


def _safe_git_output(repo_path: Path, command: list[str]) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _list_top_level_entries(repo_path: Path) -> list[str]:
    entries = []
    for child in sorted(repo_path.iterdir(), key=lambda item: item.name.lower()):
        if child.name == ".git":
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
        if len(entries) >= MAX_FILE_LIST:
            break
    return entries


def _read_readme_excerpt(repo_path: Path) -> str:
    candidates = ["README.md", "README", "readme.md", "readme"]
    for candidate in candidates:
        path = repo_path / candidate
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:MAX_README_CHARS]
    return ""
