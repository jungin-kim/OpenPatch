from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.actions import AgentAction, ActionResult
from repooperator_worker.agent_core.events import append_activity_event
from repooperator_worker.agent_core.policies import command_policy_preview, validate_repo_file
from repooperator_worker.agent_core.repository_review import run_repository_review
from repooperator_worker.schemas import AgentRunRequest
from repooperator_worker.services.command_service import run_command_with_policy
from repooperator_worker.services.common import resolve_project_path


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
            elif action.type == "analyze_repository":
                response = run_repository_review(request=self.request, run_id=self.run_id, classifier=action.payload.get("classifier"))
                result = ActionResult(
                    action_id=action.action_id,
                    status="success",
                    observation="Repository review completed.",
                    files_read=response.files_read,
                    payload={"response": response},
                )
            elif action.type in {"preview_command", "inspect_git_state"}:
                result = self._preview_command(action)
            elif action.type == "run_approved_command":
                result = self._run_approved_command(action)
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
