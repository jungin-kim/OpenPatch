from __future__ import annotations

import shlex
import time
import re
import json
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
from repooperator_worker.services.json_safe import json_safe, safe_agent_response_payload
from repooperator_worker.services.model_client import ModelGenerationRequest, OpenAICompatibleModelClient


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
        raw_queries.extend(action.payload.get("file_globs") or [])
        queries = []
        for item in raw_queries:
            text = str(item).strip()
            if text and text not in queries:
                queries.append(text)
        text_queries = [str(item).strip() for item in action.payload.get("text_queries") or [] if str(item).strip()]
        max_results = int(action.payload.get("max_results") or 8)
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
            aggregate={"queries": queries, "text_queries": text_queries},
        )
        candidate_details = self._find_file_candidates(repo, queries, text_queries=text_queries, max_results=max_results)
        candidates = [item["path"] for item in candidate_details]
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
            aggregate={"queries": queries, "text_queries": text_queries, "candidates": candidates, "candidate_details": candidate_details},
        )
        return ActionResult(
            action_id=action.action_id,
            status="success",
            observation=f"Found {len(candidates)} candidate file(s).",
            payload={"queries": queries, "text_queries": text_queries, "candidates": candidates, "candidate_details": candidate_details},
        )

    def _find_file_candidates(self, repo: Path, queries: list[str], *, text_queries: list[str] | None = None, max_results: int = 8) -> list[dict[str, Any]]:
        skip_dirs = {".git", ".claude", "node_modules", "runtime", ".next", "dist", "build", "out", "coverage", ".venv", "venv", "__pycache__"}
        text_suffixes = {".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift", ".go", ".rs", ".md", ".json", ".toml", ".yaml", ".yml"}
        files: list[Path] = []
        for path in repo.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo)
            if any(part.lower() in skip_dirs for part in rel.parts):
                continue
            if is_stale_duplicate_copy(rel):
                continue
            if path.suffix.lower() not in text_suffixes and path.name.lower() not in {"readme", "makefile", "dockerfile"}:
                continue
            files.append(path)
        text_queries = text_queries or []
        scored: dict[str, dict[str, Any]] = {}
        for path in files:
            rel = path.relative_to(repo)
            rel_text = str(rel)
            path_lower = rel_text.lower()
            name_lower = path.name.lower()
            stem_lower = path.stem.lower()
            score = 0.0
            reasons: list[str] = []
            matched: list[str] = []
            for query in queries:
                lowered = query.lower()
                query_name = Path(query).name.lower()
                if lowered.startswith("*.") and path.suffix.lower() == lowered[1:]:
                    score += 4.0
                    reasons.append(f"extension: {lowered}")
                    matched.append(query)
                elif path_lower == lowered:
                    score += 120.0
                    reasons.append(f"exact path: {query}")
                    matched.append(query)
                elif name_lower == query_name:
                    score += 90.0
                    reasons.append(f"basename: {query_name}")
                    matched.append(query)
                elif query_name and query_name.rstrip(".cs").lower() in stem_lower:
                    score += 35.0
                    reasons.append(f"name contains: {query}")
                    matched.append(query)
            text = ""
            if text_queries or any("." not in query and not query.startswith("*.") for query in queries):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")[:120_000]
                except OSError:
                    text = ""
            for query in queries:
                if "." in query or query.startswith("*.") or not text:
                    continue
                if re.search(rf"\b(class|struct|interface|enum|def|function|const|let|var)\s+{re.escape(query)}\b", text):
                    score += 70.0
                    reasons.append(f"symbol: {query}")
                    matched.append(query)
            for query in text_queries:
                if not text:
                    continue
                count = text.lower().count(query.lower())
                if count:
                    score += min(60.0, 14.0 * count)
                    reasons.append(f"contains: {query}")
                    matched.append(query)
            if score > 0:
                source_rank = self._candidate_priority(rel)
                score += max(0.0, 5.0 - source_rank[0] - source_rank[1])
                scored[rel_text] = {
                    "path": rel_text,
                    "score": round(score, 2),
                    "reasons": _dedupe_strings(reasons),
                    "matched_queries": _dedupe_strings(matched),
                }
        return sorted(scored.values(), key=lambda item: (-float(item["score"]), item["path"]))[:max_results]

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
            proposal = model_generate_edit_proposal(relative_path, content, self.request.task, action.payload)
            if proposal is None:
                proposed = propose_content_update(relative_path, content, self.request.task)
                proposal = build_fallback_edit_proposal(relative_path, content, proposed, self.request.task)
            if proposal and proposal.get("proposed_content") != content:
                proposals.append(
                    {
                        "file": relative_path,
                        "summary": str(proposal.get("summary") or "Prepare a safe minimal edit proposal."),
                        "before_summary": summarize_code_change(content),
                        "after_summary": summarize_code_change(str(proposal.get("proposed_content") or "")),
                        "proposed_content": str(proposal.get("proposed_content") or ""),
                        "diff_summary": str(proposal.get("unified_diff") or summarize_diff(content, str(proposal.get("proposed_content") or ""))),
                        "risk_notes": list(proposal.get("risk_notes") or []),
                        "preserves_existing_behavior": bool(proposal.get("preserves_existing_behavior")),
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


EDIT_PROPOSAL_PROMPT = """\
You are RepoOperator's edit proposal generator. Return JSON only.
Create a proposal for the single provided file. Do not claim the change was applied.
Schema:
{
  "file": "repo-relative path",
  "summary": "short summary",
  "proposed_content": "complete replacement content for this file",
  "unified_diff": "unified diff from original to proposed",
  "risk_notes": [],
  "preserves_existing_behavior": true
}
Preserve existing class structure and lifecycle methods unless the requested change requires otherwise.
"""


def model_generate_edit_proposal(relative_path: str, content: str, task: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        raw = OpenAICompatibleModelClient().generate_text(
            ModelGenerationRequest(
                system_prompt=EDIT_PROPOSAL_PROMPT,
                user_prompt=json.dumps(
                    {
                        "task": task,
                        "file": relative_path,
                        "content": content[:80_000],
                        "context": json_safe(context or {}),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        payload = parse_json_object(raw)
    except Exception:
        return None
    return validate_edit_proposal(relative_path, content, payload, task)


def validate_edit_proposal(relative_path: str, original: str, payload: dict[str, Any], task: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("file") or relative_path) != relative_path:
        return None
    proposed = str(payload.get("proposed_content") or "")
    if not proposed.strip() or proposed == original or len(proposed) > max(200_000, len(original) * 5):
        return None
    original_structure = extract_source_structure(relative_path, original)
    proposed_structure = extract_source_structure(relative_path, proposed)
    risk_notes = [str(item) for item in payload.get("risk_notes") or []]
    risk_text = " ".join(risk_notes).lower()
    missing_classes = sorted(set(original_structure["classes"]) - set(proposed_structure["classes"]))
    if missing_classes and not mentions_removal_justification(task, risk_text, missing_classes):
        return None
    missing_public = sorted(set(original_structure["public_members"]) - set(proposed_structure["public_members"]))
    if missing_public and not mentions_removal_justification(task, risk_text, missing_public):
        return None
    missing_fields = sorted(set(original_structure["serialized_or_public_fields"]) - set(proposed_structure["serialized_or_public_fields"]))
    if missing_fields and not mentions_removal_justification(task, risk_text, missing_fields):
        return None
    missing_lifecycle = sorted(set(original_structure["unity_lifecycle_methods"]) - set(proposed_structure["unity_lifecycle_methods"]))
    for method in missing_lifecycle:
        if method == "Update" and method_body_is_empty(original, method):
            continue
        if not mentions_removal_justification(task, risk_text, [method]):
            return None
    if relative_path.lower().endswith(".cs") and not csharp_roughly_valid(proposed):
        return None
    hardening = "BinaryFormatter" in original or "binaryformatter" in task.lower()
    if hardening and "BinaryFormatter" in proposed:
        return None
    if hardening and not ("JsonUtility" in proposed or "System.Text.Json" in proposed or "Newtonsoft.Json" in proposed):
        return None
    if hardening and not ("File.Exists" in proposed and ("catch" in proposed or "try" in proposed)):
        return None
    if unsafe_bitwise_change(original, proposed):
        return None
    diff = str(payload.get("unified_diff") or summarize_diff(original, proposed))
    return {
        "file": relative_path,
        "summary": str(payload.get("summary") or "Prepared edit proposal."),
        "proposed_content": proposed,
        "unified_diff": diff,
        "risk_notes": risk_notes,
        "preserves_existing_behavior": bool(payload.get("preserves_existing_behavior", True)),
        "removed_members": {
            "classes": missing_classes,
            "public_members": missing_public,
            "serialized_or_public_fields": missing_fields,
            "unity_lifecycle_methods": missing_lifecycle,
        },
        "preserved_members": proposed_structure,
    }


def build_fallback_edit_proposal(relative_path: str, original: str, proposed: str, task: str) -> dict[str, Any] | None:
    if proposed == original:
        return None
    payload = {
        "file": relative_path,
        "summary": fallback_summary(relative_path, original, proposed, task),
        "proposed_content": proposed,
        "unified_diff": summarize_diff(original, proposed),
        "risk_notes": fallback_risk_notes(original, proposed),
        "preserves_existing_behavior": preserves_named_members(original, proposed),
    }
    return validate_edit_proposal(relative_path, original, payload, task)


def propose_content_update(relative_path: str, content: str, task: str) -> str:
    name = Path(relative_path).name.lower()
    task_text = task or ""
    proposed = content
    explicit_border_edit = Path(relative_path).name in task_text or "&&" in task_text or "&" in task_text
    if name == "border.cs" and explicit_border_edit:
        proposed = replace_boolean_ampersands(proposed)
        proposed = re.sub(
            r"\n\s*(?:private|public|protected|internal)?\s*void\s+Update\s*\(\s*\)\s*\{\s*\}",
            "",
            proposed,
            flags=re.MULTILINE,
        )
    if name == "datahandler.cs" or "BinaryFormatter" in content:
        proposed = propose_json_save_handler(content)
    return proposed


def propose_json_save_handler(content: str) -> str:
    without_binary_formatter = re.sub(r"^\s*using\s+System\.Runtime\.Serialization\.Formatters\.Binary;\s*\n", "", content, flags=re.MULTILINE)
    without_file_stream = re.sub(r"^\s*using\s+System\.Runtime\.Serialization;\s*\n", "", without_binary_formatter, flags=re.MULTILINE)
    if "BinaryFormatter" not in without_file_stream and ".dat" not in without_file_stream:
        return without_file_stream
    if "class DataHandler" not in without_file_stream:
        return without_file_stream.replace("BinaryFormatter", "JsonUtility")
    preserved_methods = "\n\n".join(extract_methods(without_file_stream, ["Awake", "Start"]))
    preserved_members = extract_class_member_lines(without_file_stream)
    preserved_block = (preserved_members + "\n\n" + preserved_methods).strip()
    preserved_block = f"\n{preserved_block}\n\n" if preserved_block else "\n"
    return f"""using System;
using System.IO;
using UnityEngine;

public class DataHandler : MonoBehaviour
{{{preserved_block}
    private string SavePath => Path.Combine(Application.persistentDataPath, "playerData.json");

    public void Save(PlayerData data)
    {{
        string json = JsonUtility.ToJson(data);
        File.WriteAllText(SavePath, json);
    }}

    public PlayerData Load()
    {{
        if (!File.Exists(SavePath))
        {{
            return new PlayerData();
        }}

        try
        {{
            string json = File.ReadAllText(SavePath);
            PlayerData data = JsonUtility.FromJson<PlayerData>(json);
            return data ?? new PlayerData();
        }}
        catch (Exception)
        {{
            return new PlayerData();
        }}
    }}
}}
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


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def csharp_roughly_valid(content: str) -> bool:
    balance = 0
    for char in content:
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
        if balance < 0:
            return False
    return balance == 0


def extract_source_structure(relative_path: str, content: str) -> dict[str, list[str]]:
    suffix = Path(relative_path).suffix.lower()
    if suffix != ".cs":
        return {
            "classes": [],
            "methods": [],
            "fields": [],
            "unity_lifecycle_methods": [],
            "public_members": [],
            "serialized_or_public_fields": [],
        }
    classes = re.findall(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", content)
    methods = re.findall(
        r"\b(?:public|private|protected|internal)?\s*(?:static\s+)?(?:void|bool|int|string|float|double|PlayerData|[A-Za-z_][A-Za-z0-9_<>,\[\]]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        content,
    )
    field_pattern = re.compile(
        r"^\s*(?:\[SerializeField\]\s*)?(?:(public|private|protected|internal)\s+)?(?:static\s+)?(?:readonly\s+)?[A-Za-z_][A-Za-z0-9_<>,\[\]]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|;)",
        re.MULTILINE,
    )
    fields: list[str] = []
    serialized_or_public: list[str] = []
    for match in field_pattern.finditer(content):
        visibility = match.group(1) or ""
        name = match.group(2)
        fields.append(name)
        prefix = content[max(0, match.start() - 80):match.start()]
        if visibility == "public" or "[SerializeField]" in prefix:
            serialized_or_public.append(name)
    lifecycle_names = {"Awake", "Start", "Update", "FixedUpdate", "LateUpdate", "OnEnable", "OnDisable", "OnDestroy"}
    lifecycle = [name for name in methods if name in lifecycle_names]
    public_methods = re.findall(
        r"\bpublic\s+(?:static\s+)?(?:void|bool|int|string|float|double|PlayerData|[A-Za-z_][A-Za-z0-9_<>,\[\]]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        content,
    )
    public_fields = [
        match.group(2)
        for match in field_pattern.finditer(content)
        if (match.group(1) or "") == "public"
    ]
    return {
        "classes": _dedupe_strings(classes),
        "methods": _dedupe_strings(methods),
        "fields": _dedupe_strings(fields),
        "unity_lifecycle_methods": _dedupe_strings(lifecycle),
        "public_members": _dedupe_strings([*public_methods, *public_fields]),
        "serialized_or_public_fields": _dedupe_strings(serialized_or_public),
    }


def mentions_removal_justification(task: str, risk_text: str, names: list[str]) -> bool:
    lowered_task = (task or "").lower()
    if "remove" in lowered_task or "delete" in lowered_task or "제거" in task:
        return True
    return any(name.lower() in risk_text for name in names) and any(word in risk_text for word in ("remove", "rename", "delete", "drop"))


def method_body_is_empty(content: str, method_name: str) -> bool:
    match = re.search(rf"\b{re.escape(method_name)}\s*\([^)]*\)\s*\{{", content)
    if not match:
        return False
    start = content.find("{", match.start())
    end = find_matching_brace(content, start)
    if end == -1:
        return False
    body = re.sub(r"//.*|/\*.*?\*/", "", content[start + 1:end], flags=re.DOTALL).strip()
    return not body


def unsafe_bitwise_change(original: str, proposed: str) -> bool:
    original_lines = original.splitlines()
    proposed_text = proposed
    for line in original_lines:
        stripped = line.strip()
        if not re.search(r"(?<!&)&(?!&)", stripped):
            continue
        bitwise_like = re.search(r"\b(int|long|uint|ulong|short|byte)\b", stripped) or re.search(r"\b(mask|flag|flags|bits?)\b", stripped, re.IGNORECASE)
        if not bitwise_like:
            continue
        if stripped not in proposed_text and re.sub(r"(?<!&)&(?!&)", "&&", stripped) in proposed_text:
            return True
    return False


def replace_boolean_ampersands(content: str) -> str:
    updated: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        likely_boolean_context = stripped.startswith(("if ", "if(", "while ", "while(", "return ")) or re.search(r"\bbool\b", stripped)
        likely_bitwise_context = re.search(r"\b(int|long|uint|ulong|short|byte)\b", stripped) or re.search(r"\b(mask|flag|flags|bits?)\b", stripped, re.IGNORECASE)
        if likely_boolean_context and not likely_bitwise_context:
            line = re.sub(r"(?<!&)&(?!&)", "&&", line)
        updated.append(line)
    return "\n".join(updated) + ("\n" if content.endswith("\n") else "")


def extract_methods(content: str, names: list[str]) -> list[str]:
    methods: list[str] = []
    for name in names:
        match = re.search(
            rf"((?:public|private|protected|internal)?\s*void\s+{re.escape(name)}\s*\([^)]*\)\s*\{{)",
            content,
        )
        if not match:
            continue
        start = match.start(1)
        brace = content.find("{", match.start(1))
        end = find_matching_brace(content, brace)
        if end != -1:
            methods.append(content[start : end + 1].strip())
    return methods


def find_matching_brace(content: str, start: int) -> int:
    if start < 0:
        return -1
    balance = 0
    for index in range(start, len(content)):
        char = content[index]
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance == 0:
                return index
    return -1


def extract_class_member_lines(content: str) -> str:
    class_match = re.search(r"\bclass\s+DataHandler\b[^{]*\{", content)
    if not class_match:
        return ""
    body_start = class_match.end()
    lines = []
    for line in content[body_start:].splitlines():
        stripped = line.strip()
        if not stripped or stripped == "}":
            continue
        if "(" in stripped or "{" in stripped or "}" in stripped:
            continue
        if any(skip in stripped for skip in ("BinaryFormatter", "FileStream", "formatter")):
            continue
        if stripped.endswith(";"):
            lines.append(line.rstrip())
    return "\n".join(lines[:12])


def preserves_named_members(original: str, proposed: str) -> bool:
    names = re.findall(r"\b(?:void|PlayerData|public|private|protected|internal)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", original)
    essential = [name for name in names if name not in {"Save", "Load"}]
    return all(re.search(rf"\b{name}\s*\(", proposed) for name in essential)


def fallback_summary(relative_path: str, original: str, proposed: str, task: str) -> str:
    if "BinaryFormatter" in original and "BinaryFormatter" not in proposed:
        return "Replace BinaryFormatter persistence with JsonUtility JSON persistence and corrupt-file fallback."
    if Path(relative_path).name.lower() == "border.cs":
        return "Use short-circuit boolean checks where safe and remove an empty Unity Update method."
    return "Prepared a validated proposal from the requested file content."


def fallback_risk_notes(original: str, proposed: str) -> list[str]:
    notes: list[str] = []
    if "BinaryFormatter" in original and "BinaryFormatter" not in proposed:
        notes.append("Existing binary save files will not be migrated by this proposal.")
    if not preserves_named_members(original, proposed):
        notes.append("Some existing methods may need manual review before applying.")
    return notes


def is_stale_duplicate_copy(relative_path: Path) -> bool:
    return bool(re.search(r" 2\.(py|tsx|js|json|cs)$", str(relative_path), flags=re.IGNORECASE))


def _dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
