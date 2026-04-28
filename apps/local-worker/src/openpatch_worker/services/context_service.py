from dataclasses import dataclass
from pathlib import Path

from openpatch_worker.services.common import is_git_repository, resolve_project_path
from openpatch_worker.services.retrieval_service import RetrievalResult, retrieve_context
from openpatch_worker.services.subprocess_utils import run_subprocess

MAX_README_CHARS = 4_000
MAX_DIFF_CHARS = 6_000
MAX_FILE_LIST = 20


@dataclass(frozen=True)
class MinimalRepoContext:
    repo_path_value: str
    repo_root_name: str
    branch: str | None
    is_git_repository: bool
    top_level_entries: list[str]
    git_status_excerpt: str
    readme_excerpt: str
    diff_excerpt: str
    summary: str
    prompt_context: str


def build_minimal_repo_context(repo_path_value: str) -> MinimalRepoContext:
    repo_path = resolve_project_path(repo_path_value)
    git_repo = is_git_repository(repo_path)

    branch = _safe_git_output(repo_path, ["git", "branch", "--show-current"]) or None
    status = _safe_git_output(repo_path, ["git", "status", "--short"]) if git_repo else ""
    top_level_files = _list_top_level_entries(repo_path)
    readme_excerpt = _read_readme_excerpt(repo_path)
    diff_excerpt = (
        _safe_git_output(repo_path, ["git", "diff"])[:MAX_DIFF_CHARS]
        if git_repo
        else ""
    )

    summary = (
        f"Project '{repo_path_value}'"
        f"{f' on branch {branch!r}' if branch else ''} with "
        f"{len(top_level_files)} top-level entries and "
        f"{'a non-empty' if diff_excerpt else 'no'} working diff."
    )

    context_parts = [
        f"Repository path: {repo_path_value}",
        f"Git repository: {'yes' if git_repo else 'no'}",
        "Top-level entries:",
        "\n".join(f"- {entry}" for entry in top_level_files) or "- (none)",
    ]

    if branch:
        context_parts.insert(1, f"Current branch: {branch}")
    if git_repo:
        context_parts.extend(
            [
                "Git status (--short):",
                status or "(clean)",
            ]
        )

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

    return MinimalRepoContext(
        repo_path_value=repo_path_value,
        repo_root_name=repo_path.name,
        branch=branch,
        is_git_repository=git_repo,
        top_level_entries=top_level_files,
        git_status_excerpt=status or "(not a git repository)",
        readme_excerpt=readme_excerpt,
        diff_excerpt=diff_excerpt,
        summary=summary,
        prompt_context="\n\n".join(context_parts),
    )


@dataclass(frozen=True)
class QueryAwareContext:
    """Extended context that combines baseline repo metadata with task-specific file retrieval."""

    repo_path_value: str
    repo_root_name: str
    branch: str | None
    is_git_repository: bool
    top_level_entries: list[str]
    readme_excerpt: str
    retrieval: RetrievalResult
    summary: str

    @property
    def files_read(self) -> list[str]:
        return self.retrieval.files_read

    def to_prompt_context(self) -> str:
        """
        Build the full context string injected into the model prompt.

        Structure:
          1. Repository metadata (always present)
          2. README excerpt (when no files were retrieved, or always for project review)
          3. Retrieved files / tree (task-specific)
        """
        parts: list[str] = []

        # --- baseline metadata ---
        meta_lines = [
            f"Repository: {self.repo_root_name}",
            f"Path: {self.repo_path_value}",
            f"Git repository: {'yes' if self.is_git_repository else 'no'}",
        ]
        if self.branch:
            meta_lines.append(f"Branch: {self.branch}")
        meta_lines.append(
            "Top-level entries:\n"
            + "\n".join(f"  {e}" for e in self.top_level_entries)
        )
        parts.append("\n".join(meta_lines))

        # --- README (include when retrieval found nothing, or for review/arch/general) ---
        include_readme = self.readme_excerpt and (
            self.retrieval.is_empty()
            or self.retrieval.query_type in {"project_review", "architecture", "general"}
        )
        if include_readme:
            parts.append(f"README excerpt:\n{self.readme_excerpt}")

        # --- retrieved content ---
        if not self.retrieval.is_empty():
            retrieval_block = self.retrieval.to_context_block()
            parts.append(f"Retrieved content ({self.retrieval.query_type}):\n{retrieval_block}")
        elif not self.readme_excerpt:
            parts.append("(No additional file content was retrieved for this query.)")

        return "\n\n".join(parts)


def build_query_aware_context(repo_path_value: str, task: str) -> QueryAwareContext:
    """
    Build a task-aware repository context.

    1. Resolves baseline metadata (branch, top-level entries, README).
    2. Classifies the task and retrieves relevant files.
    3. Combines both into a QueryAwareContext ready for the model prompt.
    """
    repo_path = resolve_project_path(repo_path_value)
    git_repo = is_git_repository(repo_path)

    branch = _safe_git_output(repo_path, ["git", "branch", "--show-current"]) or None
    top_level_files = _list_top_level_entries(repo_path)
    readme_excerpt = _read_readme_excerpt(repo_path)

    retrieval = retrieve_context(repo_path, task)

    files_count = len(retrieval.files)
    summary_parts = [
        f"Project '{repo_path_value}'",
        f"on branch {branch!r}" if branch else None,
        f"with {len(top_level_files)} top-level entries",
        f"retrieved {files_count} file(s) ({retrieval.query_type} strategy)" if files_count else None,
    ]
    summary = " ".join(p for p in summary_parts if p is not None) + "."

    return QueryAwareContext(
        repo_path_value=repo_path_value,
        repo_root_name=repo_path.name,
        branch=branch,
        is_git_repository=git_repo,
        top_level_entries=top_level_files,
        readme_excerpt=readme_excerpt,
        retrieval=retrieval,
        summary=summary,
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
