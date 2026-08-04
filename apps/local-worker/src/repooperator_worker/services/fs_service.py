from pathlib import Path

from repooperator_worker.schemas import DirEntry, DirListRequest, DirListResponse
from repooperator_worker.services.common import (
    ensure_relative_to_repo,
    resolve_project_path,
)

# Directories that only add noise to a file picker.
IGNORED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".DS_Store",
}


def list_directory(request: DirListRequest) -> DirListResponse:
    """List the immediate children of a directory inside the repository.

    ``relative_path`` empty means the repository root. Only one level is
    returned so the UI can browse lazily, folder by folder.
    """

    repo_path = resolve_project_path(request.project_path)
    relative_path = request.relative_path.strip("/")

    if relative_path:
        target_dir = ensure_relative_to_repo(repo_path, relative_path)
    else:
        target_dir = repo_path

    if not target_dir.exists():
        raise FileNotFoundError(f"Directory does not exist: {relative_path or '.'}")
    if not target_dir.is_dir():
        raise ValueError(f"Not a directory: {relative_path or '.'}")

    entries: list[DirEntry] = []
    for child in target_dir.iterdir():
        name = child.name
        if name in IGNORED_DIR_NAMES:
            continue
        try:
            child_relative = str(child.relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            continue
        if child.is_dir():
            entries.append(DirEntry(name=name, relative_path=child_relative, type="dir"))
        elif child.is_file():
            size: int | None = None
            try:
                size = child.stat().st_size
            except OSError:
                size = None
            entries.append(
                DirEntry(name=name, relative_path=child_relative, type="file", size=size)
            )

    # Folders first, then files, each alphabetical (case-insensitive).
    entries.sort(key=lambda entry: (entry.type != "dir", entry.name.lower()))

    parent_path: str | None = None
    if relative_path:
        parent = str(Path(relative_path).parent).replace("\\", "/")
        parent_path = "" if parent == "." else parent

    return DirListResponse(
        project_path=request.project_path,
        relative_path=relative_path,
        parent_path=parent_path,
        entries=entries,
    )
