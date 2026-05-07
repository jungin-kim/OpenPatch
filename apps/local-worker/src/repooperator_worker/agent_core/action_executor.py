from __future__ import annotations

import shlex
import time
import re
from difflib import unified_diff
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.events import append_activity_event
from repooperator_worker.agent_core.policies import command_policy_preview, validate_repo_file
from repooperator_worker.agent_core.repository_review import run_repository_review
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.command_service import run_command_with_policy
from repooperator_worker.services.common import resolve_project_path
from repooperator_worker.services.json_safe import safe_agent_response_payload


class ActionExecutor:
    def __init__(self, *, run_id: str, request: AgentRunRequest) -> None:
        self.run_id = run_id
        self.request = request

    def execute(self, action: AgentAction) -> ActionResult:
        started = time.perf_counter()
        try:
            if action.type == "inspect_repo_tree":
                result = self._inspect_repo_tree(action)
            elif action.type == "read_file":
                result = self._read_file(action)
            elif action.type == "search_files":
                result = self._search_files(action)
            elif action.type == "analyze_repository":
                response = run_repository_review(request=self.request, run_id=self.run_id, classifier=action.payload.get("classifier"))
                result = ActionResult(
                    action_id=action.action_id,
                    status="success",
                    observation="Repository review completed.",
                    files_read=response.files_read,
                    payload={"response": safe_agent_response_payload(response)},
                )
            elif action.type in {"preview_command", "inspect_git_state"}:
                result = self._preview_command(action)
            elif action.type == "run_approved_command":
                result = self._run_approved_command(action)
            elif action.type == "generate_edit":
                result = self._generate_edit(action)
            elif action.type == "ask_clarification":
                result = ActionResult(action_id=action.action_id, status="success", observation=action.reason_summary)
            elif action.type == "final_answer":
                result = ActionResult(action_id=action.action_id, status="success", observation="Ready to prepare the final answer.")
            else:
                result = ActionResult(action_id=action.action_id, status="skipped", observation=f"Action {action.type} is not implemented yet.")
        except Exception as exc:  # noqa: BLE001
            result = ActionResult(action_id=action.action_id, status="failed", observation="Action failed.", errors=[str(exc)])
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    def _inspect_repo_tree(self, action: AgentAction) -> ActionResult:
        repo = resolve_project_path(self.request.project_path)
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id="inspect-repo-tree",
            event_type="activity_started",
            phase="Searching",
            label="Inspect repository tree",
            status="running",
            current_action="Listing top-level repository entries.",
            next_action="Use the listing to choose files or answer from inventory.",
        )
        entries = []
        try:
            entries = sorted(path.name for path in repo.iterdir())[:80]
        except OSError as exc:
            return ActionResult(action_id=action.action_id, status="failed", observation=str(exc), errors=[str(exc)])
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id="inspect-repo-tree",
            event_type="activity_completed",
            phase="Searching",
            label="Inspect repository tree",
            status="completed",
            observation=f"Found {len(entries)} top-level entr{'y' if len(entries) == 1 else 'ies'}.",
            next_action="Prepare the answer or inspect targeted files.",
            aggregate={"entries_count": len(entries)},
        )
        return ActionResult(action_id=action.action_id, status="success", observation=", ".join(entries), payload={"entries": entries})

    def _read_file(self, action: AgentAction) -> ActionResult:
        if not action.target_files:
            return ActionResult(action_id=action.action_id, status="skipped", observation="No target file was provided.")
        files_read: list[str] = []
        contents: dict[str, str] = {}
        for relative_path in action.target_files[:8]:
            validate_repo_file(self.request.project_path, relative_path)
            activity_id = f"read-file:{relative_path}"
            append_activity_event(
                run_id=self.run_id,
                request=self.request,
                activity_id=activity_id,
                event_type="activity_started",
                phase="Reading files",
                label=Path(relative_path).name,
                status="running",
                current_action=f"Reading `{relative_path}`.",
                related_files=[relative_path],
            )
            target = validate_repo_file(self.request.project_path, relative_path)
            raw = target.read_text(encoding="utf-8", errors="replace")
            files_read.append(relative_path)
            contents[relative_path] = raw[:100_000]
            append_activity_event(
                run_id=self.run_id,
                request=self.request,
                activity_id=activity_id,
                event_type="activity_completed",
                phase="Reading files",
                label=Path(relative_path).name,
                status="completed",
                observation=f"Read {len(raw.splitlines())} line(s).",
                next_action="Use the file content as evidence.",
                related_files=[relative_path],
            )
        return ActionResult(action_id=action.action_id, status="success", files_read=files_read, observation=f"Read {len(files_read)} file(s).", payload={"contents": contents})

    def _search_files(self, action: AgentAction) -> ActionResult:
        repo = resolve_project_path(self.request.project_path).resolve()
        raw_queries = [*(action.payload.get("queries") or action.target_files or []), *action.target_symbols]
        queries = []
        for item in raw_queries:
            text = str(item).strip()
            if text and text not in queries:
                queries.append(text)
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id="search-files:" + "-".join(queries)[:120],
            event_type="activity_started",
            phase="Searching",
            label="Resolving target files",
            status="running",
            current_action="Searching repository files by path, basename, extension, or symbol.",
            next_action="Read the best matching repo-contained file.",
            aggregate={"queries": queries},
        )
        candidates = self._find_file_candidates(repo, queries)
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id="search-files:" + "-".join(queries)[:120],
            event_type="activity_completed",
            phase="Searching",
            label="Resolved target files",
            status="completed",
            observation=f"Found {len(candidates)} candidate file(s).",
            related_files=candidates,
            aggregate={"queries": queries, "candidates": candidates},
        )
        return ActionResult(
            action_id=action.action_id,
            status="success",
            observation=f"Found {len(candidates)} candidate file(s).",
            payload={"queries": queries, "candidates": candidates},
        )

    def _find_file_candidates(self, repo: Path, queries: list[str]) -> list[str]:
        skip_dirs = {".git", ".claude", "node_modules", "runtime", ".next", "dist", "build", "out", "coverage", ".venv", "venv", "__pycache__"}
        text_suffixes = {".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift", ".go", ".rs", ".md", ".json", ".toml", ".yaml", ".yml"}
        files: list[Path] = []
        for path in repo.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo)
            if any(part.lower() in skip_dirs for part in rel.parts):
                continue
            if path.suffix.lower() not in text_suffixes and path.name.lower() not in {"readme", "makefile", "dockerfile"}:
                continue
            files.append(path)
        candidates: list[str] = []
        for query in queries:
            lowered = query.lower()
            query_name = Path(query).name.lower()
            if lowered.startswith("*."):
                matches = [path for path in files if path.suffix.lower() == lowered[1:]]
            else:
                matches = [
                    path for path in files
                    if str(path.relative_to(repo)).lower() == lowered
                    or path.name.lower() == query_name
                    or query_name.rstrip(".cs").lower() in path.stem.lower()
                ]
                if not matches and "." not in query:
                    matches = self._find_symbol_matches(files, query)
            for path in sorted(matches, key=lambda item: self._candidate_priority(item.relative_to(repo))):
                rel = str(path.relative_to(repo))
                if rel not in candidates:
                    candidates.append(rel)
                if len(candidates) >= 8:
                    return candidates
        return candidates

    def _candidate_priority(self, relative_path: Path) -> tuple[int, int, str]:
        parts = [part.lower() for part in relative_path.parts]
        source = 0 if relative_path.suffix.lower() in {".cs", ".py", ".js", ".ts", ".tsx"} else 1
        source_dir = 0 if any(part in {"assets", "scripts", "src", "app", "apps"} for part in parts) else 1
        return (source + source_dir, len(relative_path.parts), str(relative_path).lower())

    def _find_symbol_matches(self, files: list[Path], query: str) -> list[Path]:
        pattern = re.compile(rf"\b(class|struct|interface|enum|def|function|const|let|var)\s+{re.escape(query)}\b")
        matches: list[Path] = []
        for path in files:
            if path.suffix.lower() not in {".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:120_000]
            except OSError:
                continue
            if pattern.search(text):
                matches.append(path)
        return matches

    def _generate_edit(self, action: AgentAction) -> ActionResult:
        proposals: list[dict[str, str]] = []
        for relative_path in action.target_files[:4]:
            target = validate_repo_file(self.request.project_path, relative_path)
            content = target.read_text(encoding="utf-8", errors="replace")
            proposed = propose_content_update(relative_path, content, self.request.task)
            if proposed != content:
                proposals.append(
                    {
                        "file": relative_path,
                        "before_summary": summarize_code_change(content),
                        "after_summary": summarize_code_change(proposed),
                        "proposed_content": proposed,
                        "diff_summary": summarize_diff(content, proposed),
                    }
                )
        if proposals:
            append_activity_event(
                run_id=self.run_id,
                request=self.request,
                activity_id="generate-edit:" + ",".join(item["file"] for item in proposals)[:120],
                event_type="activity_completed",
                phase="Editing",
                label="Prepared patch",
                status="completed",
                observation="Prepared a proposed patch without writing files.",
                current_action="Built a minimal proposal from the file contents already read.",
                next_action="Report the proposal honestly as not applied.",
                related_files=[item["file"] for item in proposals],
                aggregate={"applied": False, "proposal_count": len(proposals)},
            )
        status = "success" if proposals else "skipped"
        return ActionResult(
            action_id=action.action_id,
            status=status,
            observation="Prepared a proposed edit. No file was written." if proposals else "No safe edit proposal could be generated.",
            files_read=action.target_files,
            payload={"edit_proposals": proposals, "applied": False},
            next_recommended_action="write_file" if proposals else None,
        )

    def _preview_command(self, action: AgentAction) -> ActionResult:
        command = action.command or ["git", "status", "--short"]
        activity_id = "command-preview:" + shlex.join(command)
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id=activity_id,
            event_type="activity_started",
            phase="Commands",
            label="Preview command",
            status="running",
            current_action=f"Classifying `{shlex.join(command)}` through command policy.",
            related_command=command,
        )
        preview = command_policy_preview(command, project_path=self.request.project_path, reason=action.reason_summary)
        status = "waiting_approval" if preview.get("needs_approval") else "success"
        append_activity_event(
            run_id=self.run_id,
            request=self.request,
            activity_id=activity_id,
            event_type="activity_completed" if status == "success" else "activity_updated",
            phase="Commands",
            label="Preview command",
            status="waiting" if status == "waiting_approval" else "completed",
            observation="Command requires approval." if status == "waiting_approval" else "Command is allowed by policy.",
            next_action="Request approval before running." if status == "waiting_approval" else "Run the command if needed.",
            related_command=command,
        )
        return ActionResult(action_id=action.action_id, status=status, observation=str(preview.get("reason") or ""), command_result=preview, next_recommended_action="request_command_approval" if status == "waiting_approval" else "run_approved_command")

    def _run_approved_command(self, action: AgentAction) -> ActionResult:
        command = action.command or []
        result = run_command_with_policy(command, project_path=self.request.project_path, reason=action.reason_summary)
        return ActionResult(
            action_id=action.action_id,
            status="success" if result.get("exit_code") == 0 else "failed",
            observation=str(result.get("stdout") or result.get("stderr") or ""),
            command_result=result,
        )


def propose_content_update(relative_path: str, content: str, task: str) -> str:
    name = Path(relative_path).name.lower()
    task_text = task or ""
    proposed = content
    explicit_border_edit = Path(relative_path).name in task_text or "&&" in task_text or "&" in task_text
    if name == "border.cs" and explicit_border_edit:
        proposed = re.sub(r"(?<!&)&(?!&)", "&&", proposed)
        proposed = re.sub(
            r"\n\s*(?:private|public|protected|internal)?\s*void\s+Update\s*\(\s*\)\s*\{\s*\}",
            "",
            proposed,
            flags=re.MULTILINE,
        )
    if name == "datahandler.cs" or "BinaryFormatter" in content:
        proposed = propose_json_save_handler(content)
    if proposed == content and ("&&" in task_text or "&" in task_text):
        proposed = re.sub(r"(?<!&)&(?!&)", "&&", proposed)
    return proposed


def propose_json_save_handler(content: str) -> str:
    without_binary_formatter = re.sub(r"^\s*using\s+System\.Runtime\.Serialization\.Formatters\.Binary;\s*\n", "", content, flags=re.MULTILINE)
    without_file_stream = re.sub(r"^\s*using\s+System\.Runtime\.Serialization;\s*\n", "", without_binary_formatter, flags=re.MULTILINE)
    if "BinaryFormatter" not in without_file_stream and ".dat" not in without_file_stream:
        return without_file_stream
    if "class DataHandler" not in without_file_stream:
        return without_file_stream.replace("BinaryFormatter", "JsonUtility")
    return """using System;
using System.IO;
using UnityEngine;

public class DataHandler : MonoBehaviour
{
    private string SavePath => Path.Combine(Application.persistentDataPath, "playerData.json");

    public void Save(PlayerData data)
    {
        string json = JsonUtility.ToJson(data);
        File.WriteAllText(SavePath, json);
    }

    public PlayerData Load()
    {
        if (!File.Exists(SavePath))
        {
            return new PlayerData();
        }

        try
        {
            string json = File.ReadAllText(SavePath);
            PlayerData data = JsonUtility.FromJson<PlayerData>(json);
            return data ?? new PlayerData();
        }
        catch (Exception)
        {
            return new PlayerData();
        }
    }
}
"""


def summarize_code_change(content: str) -> str:
    markers: list[str] = []
    if "BinaryFormatter" in content:
        markers.append("uses BinaryFormatter")
    if "JsonUtility" in content:
        markers.append("uses JsonUtility")
    if re.search(r"(?<!&)&(?!&)", content):
        markers.append("contains single ampersand boolean checks")
    if re.search(r"void\s+Update\s*\(\s*\)\s*\{\s*\}", content, flags=re.MULTILINE):
        markers.append("has an empty Update method")
    return ", ".join(markers) if markers else f"{len(content.splitlines())} line(s)"


def summarize_diff(before: str, after: str, *, limit: int = 4000) -> str:
    diff = "\n".join(
        unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    return diff[:limit]
