import shutil
import subprocess
import sys
from pathlib import Path

from repooperator_worker.schemas import (
    DirEntry,
    DirListRequest,
    DirListResponse,
    RevealFolderRequest,
    RevealFolderResponse,
)
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


def reveal_in_file_manager(request: RevealFolderRequest) -> RevealFolderResponse:
    """Open the repository's working folder in the OS file manager.

    macOS -> Finder (``open``), Windows -> Explorer (``explorer``),
    Linux -> default handler (``xdg-open``). The path is always the resolved,
    validated repository root, never arbitrary user input.
    """

    repo_path = resolve_project_path(request.project_path)
    target = str(repo_path)
    platform = sys.platform

    if platform == "darwin":
        argv = ["open", target]
    elif platform.startswith("win"):
        argv = ["explorer", target]
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError(
                "No file manager opener found (xdg-open is not installed on this system)."
            )
        argv = [opener, target]

    try:
        # Windows explorer returns exit code 1 even on success, so we do not
        # gate on returncode there; on other platforms a failure raises.
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Failed to launch file manager: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out while opening the file manager.") from exc

    opened = platform.startswith("win") or result.returncode == 0
    if not opened:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"Failed to open folder: {detail}")

    return RevealFolderResponse(
        project_path=request.project_path,
        resolved_path=target,
        platform=platform,
        opened=True,
    )
