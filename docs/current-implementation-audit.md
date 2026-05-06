# RepoOperator Current Implementation Audit

Audit date: 2026-05-06
Repository path: `/Users/junginkim/Documents/GitHub/RepoOperator`
Branch audited: `main`

This report is based on the current codebase and commands run locally. It intentionally reports implementation evidence, partial behavior, and risks; it does not treat roadmap text as implementation.

## 0. Top-Level Reviewer Summary

- Status: Red
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/agent_service.py`
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/web/src/components/chat/ChatApp.tsx`
  - `apps/web/src/components/chat/ProgressTimeline.tsx`
  - `packages/cli/src/index.js`
  - `docs/implementation-status-report.md`
- Relevant functions/classes/components/routes
  - `run_agent_orchestration_graph`, `stream_agent_orchestration_graph`
  - `run_agent`, `stream_agent_run`
  - `append_run_event`, `start_active_run`, `complete_active_run`
  - `ChatApp`, `ChatComposer`, `ProgressTimeline`
  - CLI commands `onboard`, `up`, `down`, `doctor`, `status`
- How it currently works
  - RepoOperator has an installed CLI, a FastAPI local worker, a Next.js web app, a LangGraph-backed routing path, local command preview/run endpoints, memory/events/debug foundations, vLLM onboarding support, and recent UI work for active runs, queues, activity logs, changed files, and steering.
  - The product is not yet internally consistent. Some desired behavior is implemented as durable backend behavior; other behavior is UI-local, fallback-driven, or still partially backed by old settings such as `write_mode`.
- What user-facing behavior exists
  - Users can run the CLI, onboard providers, start web/worker processes, chat with a repository, see `/debug`, view activity/progress, see changed files, queue messages while a run is active, preview/run approved commands, and inspect memory/events/tool status.
- What is still missing
  - The LangGraph architecture is not yet a true central Plan/Act/Observe controller loop. Multi-step execution exists but is still implemented largely inside workflow functions.
  - Queueing, steering, and cancellation are only partially durable. Steering is recorded, but the active agent loop does not fully adapt from it.
  - File edit policy is mixed: auto-edit behavior exists in the graph, but ProposalCard/Apply paths and legacy `write_mode` remain.
  - Routines and context compression are missing.
  - Some packaging and workspace hygiene issues remain, including stale duplicate-looking files.
- Known bugs or risks
  - Architectural risk: multiple layers still carry agent behavior: `agent_orchestration_graph.py`, `agent_graph.py`, command/tool services, skills, and UI-local queue state. This can create divergent product behavior.
  - UX risk: run progress, queue state, steering, and changed-file views are improving but not fully durable or verified across reloads.
  - Safety risk: normal file edits can auto-apply in the graph, but permission profile still maps Basic/Auto review to legacy write-with-approval strings, making safety policy hard to reason about.
- Suggested next fix
  - Stabilize a single authoritative agent loop contract: durable run state, action events, queue/steer/cancel semantics, command approvals, auto file edits, and deterministic validators in one backend state machine.
- Verification commands or UI steps
  - `PYTHONPATH=apps/local-worker/src python3 -m unittest discover -s apps/local-worker/tests`
  - `npm --prefix apps/web run build`
  - `node --check packages/cli/src/index.js`
  - Open `/app`, start a long run, queue a message, steer it, navigate to `/debug`, return, and verify the active run is scoped to the original thread.

### Product Readiness Assessment

RepoOperator is a promising alpha-quality local-first coding agent, but it is not product-ready. The repository contains substantial working foundations: CLI packaging, runtime bootstrap, LangGraph routing, command safety, debug panels, memory/event storage, vLLM support, and modern chat UI pieces. The biggest problem is consistency: several features exist in partial layers, with UI state, worker state, config state, and graph state not always sharing one durable source of truth. The implementation direction broadly matches the intended product, but the core agent loop and state model need consolidation before additional feature work.

### Top 10 Working Features

1. CLI command surface exists: `onboard`, `up`, `down`, `doctor`, `status`, `worker`.
2. npm packaging bundles local-worker and web runtime through `packages/cli/scripts/prepare-runtime.js`.
3. FastAPI worker exposes health, agent, debug, command, tool, integration, memory, and permission endpoints.
4. LangGraph is used for the main orchestration path in `agent_orchestration_graph.py`.
5. Local command preview/run service exists with argv execution, cwd scoping, risk classification, redaction, and approvals.
6. Basic/Auto review/Full access UI labels exist in the web app and worker permission response.
7. Debug page exists with Dashboard, Agents, Memory, Skills, Integrations, Tools, Events/Runs, and Settings panels.
8. Memory storage and memory graph foundations exist.
9. vLLM is supported in onboarding and model configuration as an OpenAI-compatible local runtime.
10. Active run/event persistence exists under `~/.repooperator/runs` and the web app can rehydrate active run events.

### Top 15 Blockers

1. The graph is not yet a clean, general Plan/Act/Observe/Reflect agent loop.
2. `agent_graph.py` still exists as a read-only subgraph and is called from the orchestration graph.
3. Some workflow behavior remains hardcoded in Python functions rather than skill-driven planning.
4. Permission policy is split between new `permission_mode` and legacy `write_mode`.
5. Auto file-edit policy is implemented in parts of the graph, while ProposalCard/Apply code still remains.
6. Queue state is mostly client/localStorage scoped, not fully backend durable by repo/branch/thread.
7. Steering endpoint records the instruction but does not prove the active loop adapts at safe checkpoints.
8. Cancel endpoint marks the run cancelled but cannot reliably interrupt all in-flight work immediately.
9. Active run persistence exists, but stream reconnect is polling-oriented and `last_event_id` support is not complete.
10. Repository source merge/reload behavior needs manual verification; stale config risks remain.
11. Composio is a status/API foundation, not a full OAuth/connect implementation.
12. Routines are missing.
13. Context compression is missing.
14. README still describes read-only/old permission behavior in several places.
15. The working tree contains stale duplicate-looking files such as `package-lock 5.json`, `package-lock 6.json`, `package-lock 7.json`, and `apps/web/src/app/debug/page 2.tsx`.

### Direction Match

- Local-first coding agent: Partial. CLI, local worker, web runtime, local commands, and repo sandbox foundations exist.
- LangGraph/LLM-centered agent loop: Partial. LangGraph is used, but the graph is not yet a full controller loop.
- Skill-driven workflows: Partial. Skills discovery and built-ins exist, but workflows are still partly hardcoded.
- Command approval: Implemented foundation. Command preview/run/approval endpoints exist with risk classes.
- Auto file edits inside repo sandbox: Partial. Graph write steps can auto-write after validation, but legacy proposal and `write_mode` paths remain.
- Debug/observability: Partial to implemented. Debug has many panels and event storage, but some panels are shallow or placeholder-level.

### Recommended Next 10 Tasks

1. Consolidate agent execution into a durable backend Plan/Act/Observe loop with explicit action contracts.
2. Resolve permission/file-edit policy: remove legacy `write_mode` from active logic or make it clearly compatibility-only.
3. Make queue, steering, cancellation, and active-run state fully server-backed and thread/repo/branch scoped.
4. Finish repository source reload consistency and stale config detection across CLI, worker, and web.
5. Replace remaining hardcoded workflow functions with skill-guided planner inputs while keeping validators deterministic.
6. Make changed-file archive and auto-edit summary the canonical edit UX; retire ProposalCard for normal in-repo edits if policy remains auto-apply.
7. Add rigorous UI tests for activity timeline, timers, queue, steer, changed-file drawer, and sidebar behavior.
8. Implement context compression or remove UI/docs references until implemented.
9. Implement routines or remove placeholder navigation until implemented.
10. Clean packaging hygiene: remove duplicate generated files and update README to current behavior.

## 1. Repository / Packaging / Release Status

- Status: Partial
- Relevant files
  - `packages/cli/package.json`
  - `packages/cli/scripts/prepare-runtime.js`
  - `packages/cli/src/index.js`
  - `apps/local-worker/src/repooperator_worker`
  - `apps/web/src`
  - `README.md`
- Relevant functions/classes/components/routes
  - `ensureRuntimeInstalled`
  - `prepareRuntime`
  - CLI `main`
- How it currently works
  - Current branch: `main`.
  - Latest commits:
    - `4ca8da5 Improve queue, steering, and active run UI`
    - `3dbe4e5 Fix queue visibility, steering actions, and activity keys`
    - `8155bce Improve active run UX, queueing, steering, and worklog details`
    - `3174c05 Persist active runs and improve live worklog UI`
    - `98451bc Stabilize repository sources, auto edits, and activity streaming`
  - Package version from `node -p "require('./packages/cli/package.json').version"` is `0.2.5`.
  - `npm pack --dry-run` from `packages/cli` runs `scripts/prepare-runtime.js` and bundles local-worker and web runtime into the package.
  - The package dry-run tarball includes `runtime/local-worker/src/repooperator_worker/...` and `runtime/web/src/...`.
- What user-facing behavior exists
  - A user can install the CLI package and have bundled worker/web sources copied into `~/.repooperator/runtime`.
- What is still missing
  - `npm --prefix packages/cli pack --dry-run` failed from the repository root with `ENOENT Could not read package.json ... /RepoOperator/package.json`; running `npm pack --dry-run` inside `packages/cli` succeeded. This suggests packaging commands/documentation should be normalized.
  - Pack output includes local-worker tests and runtime web lockfile. This may be acceptable for alpha, but should be intentional.
  - README still contains old read-only/product descriptions that do not match the newer auto-edit and command-approval direction.
- Known bugs or risks
  - `git status --short` shows stale duplicate-looking files and dirty files from recent work:
    - `apps/web/src/app/debug/page 2.tsx`
    - `packages/cli/package-lock 2.json`
    - `packages/cli/package-lock 5.json`
    - `packages/cli/package-lock 6.json`
    - `packages/cli/package-lock 7.json`
  - Active code grep found no OpenPatch references, but `docs/implementation-status-report.md` contains historical audit references to the term.
  - `.claude/worktrees` was not used during this audit. `.claude` was excluded from greps as requested.
- Suggested next fix
  - Remove duplicate generated files, confirm npm package contents intentionally exclude stale files, and update README to reflect current permissions and edit behavior.
- Verification commands or UI steps
  - `git branch --show-current`
  - `git status --short`
  - `git log --oneline -5`
  - `node -p "require('./packages/cli/package.json').version"`
  - `npm pack --dry-run` from `packages/cli`
  - `rg -n "openpatch" . --glob '!.git' --glob '!.claude' --glob '!node_modules' --glob '!.venv' --glob '!.next' --glob '!runtime' --glob '!*.tgz'`

## 2. CLI Onboarding / Runtime Bootstrap Status

- Status: Partial
- Relevant files
  - `packages/cli/src/index.js`
  - `packages/cli/package.json`
  - `packages/cli/scripts/prepare-runtime.js`
  - `docs/onboarding.md`
  - `docs/local-worker-setup.md`
- Relevant functions/classes/components/routes
  - `runOnboard`
  - `runUp`
  - `runDown`
  - `runDoctor`
  - `runStatus`
  - `startWorker`
  - `startWeb`
  - `ensureRuntimeInstalled`
  - `detectPython`
- How it currently works
  - CLI command dispatch supports `onboard`, `up`, `down`, `doctor`, `status`, and `worker`.
  - Python candidates include `python3.13`, `python3.12`, `python3.11`, `python3`, and `python`.
  - Bootstrap detects insufficient Python versions and prints guidance including Homebrew installation suggestions.
  - Worker and web processes are tracked under the RepoOperator home/run paths. Logs are written under RepoOperator-managed directories.
  - Runtime install is prepared from package-bundled sources.
- What user-facing behavior exists
  - `repooperator onboard` configures model/runtime and repository source information.
  - `repooperator up` starts worker and web.
  - `repooperator down` stops tracked processes.
  - `repooperator doctor/status` report runtime and model status.
- What is still missing
  - Homebrew-assisted Python installation appears to be guidance, not a fully automated bootstrap.
  - Runtime process lifecycle is still vulnerable to stale external processes not created by the CLI.
  - Package dry-run command behavior differs depending on current working directory.
- Known bugs or risks
  - README still frames some CLI flows as read-only alpha behavior.
  - Stale process cleanup depends on PID/run files and port checks; manual verification is still needed on machines with existing Next/FastAPI processes.
- Suggested next fix
  - Add a CLI bootstrap verification test that installs from packed tarball into a clean temp home and runs `doctor`, `status`, `up`, and `down`.
- Verification commands or UI steps
  - `node --check packages/cli/src/index.js`
  - `repooperator doctor`
  - `repooperator status`
  - `repooperator up`
  - `repooperator down`

## 3. Re-Onboarding Config Reload Status

- Status: Partial
- Relevant files
  - `packages/cli/src/index.js`
  - `apps/local-worker/src/repooperator_worker/config.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/local-worker/src/repooperator_worker/services/model_client.py`
  - `apps/web/src/components/chat/ChatHeader.tsx`
- Relevant functions/classes/components/routes
  - `summarizeRuntimeConfigChanges`
  - `promptReonboardingPlan`
  - `POST /admin/reload-config`
  - `GET /health`
  - `ModelConnectivityResult`
- How it currently works
  - Onboarding compares old/new config and can prompt for worker restart/reload when runtime-sensitive settings change.
  - Config fields include model connection mode, provider, model name, base URL, and API key presence/hash-style handling in CLI comparison logic.
  - Worker health exposes safe effective model fields including provider/name/base URL and config load metadata.
  - vLLM/OpenAI-compatible validation calls `/models`.
- What user-facing behavior exists
  - The user can re-onboard and be prompted to reload/restart the worker if settings changed.
  - Health/debug can show configured/effective model details without API keys.
- What is still missing
  - Full confidence requires manual verification that chat uses the new model without `repooperator down/up`.
  - Stale model mismatch warning exists in pieces, but should be tested end-to-end in web header and Debug.
  - `/models` validation checks configured model names when IDs are returned, but providers with unusual OpenAI-compatible responses may still pass with limited validation.
- Known bugs or risks
  - Running worker state can still be stale if the user skips restart/reload.
  - API key comparison must remain presence/hash only; no raw keys should be logged.
- Suggested next fix
  - Add integration tests that change provider/model/base URL while the worker is running, call reload, then verify `/health` and chat use the new model.
- Verification commands or UI steps
  - Re-onboard from Ollama to vLLM while worker is running.
  - Confirm `/health` shows `configured_model_provider = vllm` and the new model.
  - Try a missing model on an OpenAI-compatible endpoint and confirm the error lists available model IDs safely.

## 4. Repository Source / Provider Status

- Status: Partial
- Relevant files
  - `packages/cli/src/index.js`
  - `apps/local-worker/src/repooperator_worker/config.py`
  - `apps/local-worker/src/repooperator_worker/services/repository_service.py`
  - `apps/local-worker/src/repooperator_worker/services/active_repository.py`
  - `apps/web/src/lib/local-worker-client.ts`
  - `apps/web/src/components/chat/ProjectSelector.tsx`
  - `apps/web/src/app/debug/page.tsx`
- Relevant functions/classes/components/routes
  - Repository source config read/write helpers in CLI
  - `GET /repositories`
  - `GET /repositories/branches`
  - `GET /debug/runtime`
  - `ProjectSelector`
- How it currently works
  - RepoOperator supports configured source lists and active repository state.
  - The web app can fetch projects/branches from the worker and switch selected providers.
  - Debug renders configured/effective source information.
- What user-facing behavior exists
  - Users can select repository providers and branches from the web UI.
  - Debug can display repository source state.
- What is still missing
  - End-to-end source merge and cache invalidation after re-onboarding were not manually verified in this audit.
  - It is not proven that default provider only affects initial selection in every web path.
- Known bugs or risks
  - Previous reports indicated default-source coupling. Current code has fixes, but this remains a high-risk area until tested with both GitHub and GitLab configured in both orders.
- Suggested next fix
  - Add tests for GitLab-only to GitHub-added, GitHub-only to GitLab-added, and non-default provider project loading.
- Verification commands or UI steps
  - Configure GitLab only, then add GitHub through onboarding.
  - Verify Debug shows both sources.
  - Set default GitLab and load GitHub projects.
  - Set default GitHub and load GitLab projects.

## 5. Permission Model Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/permissions_service.py`
  - `apps/local-worker/src/repooperator_worker/config.py`
  - `apps/local-worker/src/repooperator_worker/services/file_service.py`
  - `apps/local-worker/src/repooperator_worker/services/edit_service.py`
  - `apps/web/src/components/chat/ChatHeader.tsx`
  - `apps/web/src/lib/local-worker-client.ts`
- Relevant functions/classes/components/routes
  - `permission_profile`
  - `get_permission_mode`
  - `update_permission_mode`
  - `GET /permissions`
  - `POST /permissions`
  - `PermissionModeSelector`
- How it currently works
  - User-facing modes are `basic`, `auto_review`, and `full_access`.
  - Legacy aliases map `read_only` to Basic, `write_with_approval` to Auto review, and `auto_apply` to Full access.
  - Basic and Auto review both allow repository file read/write in the structured sandbox profile, but both still report `write_mode = write-with-approval`.
  - Full access reports `write_mode = auto-apply`, broader sandbox, and network/outside-repo capability.
  - Command approvals are handled separately by command services.
- What user-facing behavior exists
  - The web header displays Basic permissions, Auto review, and Full access.
  - Full access requires a browser confirmation before enabling.
- What is still missing
  - Legacy `write_mode` is still used in `file_service.py` and `edit_service.py`.
  - It is not fully clear whether Basic always auto-applies normal in-repo edits, because the new graph can auto-write while old file/proposal paths still check `write_mode`.
- Known bugs or risks
  - Permission semantics are internally inconsistent: structured profile says Basic allows file writes, but legacy write mode says write-with-approval.
  - Read-only still exists as compatibility text/code alias.
- Suggested next fix
  - Remove active runtime dependence on `write_mode`, keep it only as config migration metadata, and make all file-edit decisions use the structured permission profile.
- Verification commands or UI steps
  - Set each permission mode in UI.
  - Ask for a normal in-repo edit and verify Basic auto-edits while command requests still require approval as appropriate.
  - Try outside-repo edit and destructive command requests.

## 6. LangGraph Architecture Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/agent_service.py`
  - `apps/local-worker/src/repooperator_worker/services/agent_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/context_reference_service.py`
  - `apps/local-worker/src/repooperator_worker/services/thread_context_service.py`
  - `apps/local-worker/src/repooperator_worker/services/recommendation_context_service.py`
- Relevant functions/classes/components/routes
  - `build_agent_orchestration_graph`
  - `run_agent_orchestration_graph`
  - `stream_agent_orchestration_graph`
  - `_classify_intent`
  - `_classify_with_llm`
  - `_controller_llm`
  - `_decide_next_action`
  - `_decompose_and_execute`
  - `_execute_plan_step`
  - `run_read_only_graph`
- How it currently works
  - `/agent/run` calls `agent_service.run_agent`, which delegates to `run_agent_orchestration_graph`.
  - LangGraph is used via `StateGraph`.
  - Graph nodes include context loading, validation, LLM classification, controller, action decision, context/reference resolution, recommendation handling, pasted spec handling, multi-step execution, patch generation, command/git workflows, and final answer.
  - `agent_service.py` no longer appears to contain old write-intent keyword routing.
  - Searches found no active symbols named `_refers_to_previous_file`, `_refers_to_previous_symbol`, `_is_write_confirmation`, `WRITE_INTENT_KEYWORDS`, `WRITE_KEYWORDS`, `RECOMMEND_TARGET_KEYWORDS`, or `REPO_ANALYSIS_KEYWORDS`.
- What user-facing behavior exists
  - Users get LangGraph-routed answers, edit attempts, command requests, Git/MR handling, recommendation follow-ups, and debug traces.
- What is still missing
  - The graph is not yet a clean controller loop. It has nodes named `controller_llm` and `decide_next_action`, but most workflows branch to one-way handlers or a single `_decompose_and_execute` function.
  - `agent_graph.py` still exists and is used for read-only Q&A from inside orchestration.
  - Git action and command planning still include deterministic text/action mapping functions.
- Known bugs or risks
  - Hardcoded workflow behavior remains in functions such as `_git_action_from_classifier`, `_command_for_classification`, `_fallback_plan_steps`, and multi-step fallback logic.
  - The old exact target-file failure strings were not found in active `apps`/`packages` code, but deterministic fallback clarification still exists.
- Suggested next fix
  - Convert graph execution to a genuine action loop: controller chooses action, executor runs one action, observation returns to controller, loop stops on completion/approval/clarification/error.
- Verification commands or UI steps
  - Run route-level tests for read-only Q&A, recommendations, write request, write confirmation, Git commit request, MR request, and pasted prompt handling.
  - Inspect trust trace for classifier, intent, confidence, graph path, files, symbols, validation, and stop reason.

## 7. Skills Architecture Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/skills_service.py`
  - `apps/web/src/app/debug/page.tsx`
  - Repository/user paths: `skills.md`, `.repooperator/skills.md`, `~/.repooperator/skills.md`, `~/.repooperator/skills/*.md`
- Relevant functions/classes/components/routes
  - `discover_skills`
  - `select_relevant_skills`
  - `GET /debug/skills`
  - Debug Skills panel
- How it currently works
  - Built-in skills include Git workflow and GitLab workflow.
  - Discovery includes repo root `skills.md`, repo `.repooperator/skills.md`, user `~/.repooperator/skills.md`, and user skill files.
  - Debug Skills renders discovered skills or an empty message.
- What user-facing behavior exists
  - Users can see discovered skills in Debug.
  - Skills can be selected and injected into agent context as instructions.
- What is still missing
  - Enabled/disabled state appears shallow; there is no robust user-facing skills management UI.
  - It is not proven that skills materially guide all Git/MR/commit planning; graph code still contains workflow-specific logic.
  - Large skill capping/summarization needs dedicated tests.
- Known bugs or risks
  - Skills may be present but not authoritative. Workflow knowledge is split between built-ins and hardcoded graph functions.
- Suggested next fix
  - Move Git/GitLab/Docker/Python workflow recipes into skills and keep only deterministic validators in code.
- Verification commands or UI steps
  - Add repo `skills.md` and user `~/.repooperator/skills.md`; verify both appear and neither overwrites the other.
  - Ask Git/MR tasks and verify trust trace lists relevant skills.

## 8. Recommendation Context / Follow-Up Apply Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/recommendation_context_service.py`
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/thread_context_service.py`
- Relevant functions/classes/components/routes
  - `build_recommendation_context`
  - `recommendation_context_from_history`
  - `resolve_recommendation_followup`
  - `selected_recommendation_items`
  - `_resolve_recommendation_followup`
- How it currently works
  - Recommendation context is structured with `recommendation_id`, source request summary, recommended files/symbols, items, rationale, risk, category, timestamp, repo, and branch.
  - Follow-up resolution uses the model to produce JSON describing selected recommendations/files and requested action.
  - Deterministic validation checks selected files are inside the repo and exist.
- What user-facing behavior exists
  - Recommendation answers can carry machine-readable context in metadata for later follow-up.
- What is still missing
  - Recommendation items are often generated from candidate files and generic category suggestions, not always from deep evidence per file.
  - Multi-file application exists in principle but may still collapse if fallback plan generation chooses limited steps.
  - Invalid edit output retry and context preservation need more test evidence.
- Known bugs or risks
  - `build_recommendation_context` uses generic suggestions for categories, so context can be too weak for robust later edits.
- Suggested next fix
  - Store per-file evidence snippets and exact suggested changes from inspected content, then build follow-up plans from those records.
- Verification commands or UI steps
  - Ask for project improvement recommendations.
  - Ask to narrow scope, inspect more files, and apply selected/all recommendations.
  - Verify selected recommendation IDs/files appear in trust trace.

## 9. Pasted Prompt / Spec Handling Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/recommendation_context_service.py`
  - `apps/local-worker/tests`
- Relevant functions/classes/components/routes
  - `_classify_with_llm`
  - `_handle_pasted_spec`
  - Intent values `pasted_prompt_or_spec`, `apply_spec_to_repo`
- How it currently works
  - The classifier supports pasted prompt/spec and apply-spec-to-repo intent categories.
  - Handler behavior can summarize/ask what the user wants instead of directly editing when apply intent is absent.
- What user-facing behavior exists
  - Long specs can be routed away from arbitrary target-file edits.
- What is still missing
  - Needs stronger route-level tests with varied synthetic specs and no exact report phrase dependency.
  - Applying a spec to repo should plan first; this is implemented in outline but needs end-to-end verification.
- Known bugs or risks
  - Product-term self-targeting can still occur if classifier confidence is high but no plan confirmation gate is enforced for large specs.
- Suggested next fix
  - Add a plan preview/confirmation state for large `apply_spec_to_repo` tasks before editing.
- Verification commands or UI steps
  - Paste a long coding-agent prompt with no apply instruction; expect summary/options, no edit.
  - Paste a spec with explicit apply instruction; expect plan preview first.

## 10. Multi-Step Planning and Execution Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/web/src/components/chat/ProgressTimeline.tsx`
- Relevant functions/classes/components/routes
  - `_decompose_task`
  - `_decompose_and_execute`
  - `_execute_plan_step`
  - `_summarize_plan_result`
  - `append_run_event`
- How it currently works
  - Multi-step requests can create a plan with step IDs, labels, statuses, files, actions, and summaries.
  - Execution emits plan and file activity events and can read/edit files step by step.
  - State includes plan, files read, files changed, edits applied, stop reason, and observations in the orchestration state.
- What user-facing behavior exists
  - Users can see plan/activity events and changed files in the UI.
- What is still missing
  - Plan execution is implemented in one function rather than a true graph loop with observation fed back to a controller after each action.
  - Fallback plan generation may still produce simplistic per-file steps.
  - It is not proven that dependency/config updates always wait for source inspection.
- Known bugs or risks
  - Multi-file tasks can still be brittle because step planning and edit generation depend on model output plus fallback behavior.
- Suggested next fix
  - Promote individual plan steps into first-class graph actions with controller re-entry between steps.
- Verification commands or UI steps
  - Ask a multi-file maintenance task and verify plan events stream before final, files are read before edits, and final summary matches actual events.

## 11. File Edit Behavior Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/edit_service.py`
  - `apps/local-worker/src/repooperator_worker/services/file_service.py`
  - `apps/web/src/components/chat/ChangedFilesArchive.tsx`
  - `apps/web/src/components/chat/ChangedFileDrawer.tsx`
  - `apps/web/src/components/chat/ProposalCard.tsx`
- Relevant functions/classes/components/routes
  - `_generate_patch`
  - `_validate_patch`
  - `_execute_plan_step`
  - `write_text_file`
  - `apply_structured_edit`
  - `ChangedFilesArchive`
  - `ChangedFileDrawer`
  - `ProposalCard`
- How it currently works
  - In multi-step graph write steps, generated replacements can be validated and written directly inside the active repo.
  - Changed file records include path, status, additions, deletions, summary, diff, and plan step linkage.
  - ProposalCard still exists and is rendered for `change_proposal` response types.
- What user-facing behavior exists
  - Auto-applied edits can show changed-file archive and diff drawer.
  - Older proposal/apply flow may still appear for proposal responses.
- What is still missing
  - There is no single canonical file edit UX. Auto-edit and proposal flows coexist.
  - File hash checking before apply/write appears stronger in old apply flow than in auto-write graph path.
  - High-risk edit confirmation is not fully proven.
- Known bugs or risks
  - Basic/Auto review permissions still map to legacy write-with-approval, while graph can auto-write; this ambiguity is a safety and UX risk.
  - Template-only apply messages may remain in older apply paths.
- Suggested next fix
  - Make auto-applied changed-file archive the canonical normal edit path and keep ProposalCard only for high-risk/external/approval-needed edits.
- Verification commands or UI steps
  - Request a normal in-repo edit in Basic permissions.
  - Verify file changes immediately after validation, changed files appear, no Apply button appears, commands still require approval.

## 12. Structured Edit Generation Robustness

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/edit_service.py`
  - `apps/local-worker/tests`
- Relevant functions/classes/components/routes
  - `_generate_patch`
  - `_validate_patch`
  - `_proposal_error`
  - `validate_structured_edit`
- How it currently works
  - Preferred edit schema is structured JSON with edits containing path, replacement, and summary.
  - Validation rejects empty replacements, unchanged replacements, invalid paths, and mismatched target files.
  - Invalid output routes to error response instead of showing arbitrary raw JSON as a diff.
- What user-facing behavior exists
  - Users can receive an EditError/ProposalError style response when edit generation fails.
- What is still missing
  - Repair/retry behavior is limited and should be verified for malformed JSON, refusal JSON, prose-only output, and wrong-file output.
  - File creation/deletion semantics are not as robust as modification.
- Known bugs or risks
  - The model may produce syntactically valid JSON that is semantically weak; validators need deeper checks for prose-as-file-content and destructive broad deletes.
- Suggested next fix
  - Add exhaustive edit-generation tests for malformed JSON, refusal JSON, no-op edits, wrong target path, outside repo, and destructive replacement.
- Verification commands or UI steps
  - Force a mock model to return `{"response":"..."}` and verify no diff drawer/proposal is shown.

## 13. Local Command Execution / Command Approval Status

- Status: Implemented foundation
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/command_service.py`
  - `apps/local-worker/src/repooperator_worker/services/tool_service.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/web/src/components/chat/CommandApprovalCard.tsx`
  - `apps/web/src/lib/local-worker-client.ts`
- Relevant functions/classes/components/routes
  - `preview_command`
  - `run_command_with_policy`
  - `list_command_approvals`
  - `revoke_command_approval`
  - `get_tools_status`
  - `POST /commands/preview`
  - `POST /commands/run`
  - `GET /commands/approvals`
  - `DELETE /commands/approvals/{approval_id}`
  - `GET /tools`
  - `POST /tools/run-preview`
  - `POST /tools/run`
- How it currently works
  - Commands are parsed as argv arrays with `shlex.split` for string input.
  - `subprocess.run` is called without `shell=True`, with cwd set to the active repository, stdout/stderr capture, timeout 120s, and redaction.
  - Read-only prefixes include `pwd`, `ls`, `find`, `git status`, `git branch`, `git diff`, `git log`, `glab mr list`, `glab mr view`, and `glab pipeline list`.
  - Approval prefixes include `npm install`, `pip install`, `brew install`, `curl`, `wget`, `git checkout`, `git add`, `git commit`, `git push`, `glab mr create`, and `glab mr update`.
  - Dangerous prefixes include `sudo`, `rm -rf`, broad `chmod/chown`, `git reset`, and `git clean`.
- What user-facing behavior exists
  - Safe read-only commands can run without approval.
  - Mutating/network commands require approval.
  - Dangerous commands are blocked by default.
  - Session approvals can be listed and revoked.
- What is still missing
  - Session approvals are in-memory only.
  - Command stdout/stderr summary is basic and may need safer auth-specific summarization in every UI path.
  - Tool install flow for missing glab is not a full managed sandbox install.
- Known bugs or risks
  - Prefix-based command classification is deterministic and useful, but it can miss complex shell semantics if string parsing is abused. Current service avoids `shell=True`, which reduces risk.
- Suggested next fix
  - Extend command classifier tests and ensure all agent command planning goes through this service.
- Verification commands or UI steps
  - Preview/run `git status`.
  - Preview `npm install` and verify approval required.
  - Preview `git commit` and verify approval required.
  - Preview `rm -rf` and verify blocked.

## 14. Queue / Steering / Cancel Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/web/src/components/chat/ChatApp.tsx`
  - `apps/web/src/components/chat/ChatComposer.tsx`
  - `apps/web/src/lib/local-worker-client.ts`
- Relevant functions/classes/components/routes
  - `record_run_steering`
  - `request_run_cancellation`
  - `POST /agent/runs/{run_id}/steer`
  - `POST /agent/runs/{run_id}/cancel`
  - `Queued next` UI in `ChatComposer`
  - `handleQuestionSubmit`
  - `handleSteerQueuedMessage`
  - `handleCancelQueuedMessage`
- How it currently works
  - Composer remains usable while a run is active.
  - Active-run submissions default to queue.
  - Queue/Steer global radio controls have been removed.
  - Queued messages appear above the composer with Steer and Cancel actions.
  - When a queued item starts, UI removes it from the waiting queue.
  - Steering calls `/agent/runs/{run_id}/steer`; accepted steering removes the queued item.
  - Cancel calls `/agent/runs/{run_id}/cancel` and marks run cancelled.
- What user-facing behavior exists
  - Users can queue messages, steer a queued item into the current run, cancel queued messages, and stop active runs from the UI.
- What is still missing
  - Queue state is primarily localStorage/client state, not fully backend durable by repo/branch/thread.
  - Steering is recorded as an event/meta entry, but the active agent loop does not clearly consume and adapt to steering instructions.
  - Cancellation marks the run cancelled; immediate interruption of model calls/commands is not guaranteed.
  - Queue events are not consistently persisted as backend Events/Runs records.
- Known bugs or risks
  - If the page reloads mid-queue, only client-restored queue information is available.
  - Queued items are scoped by thread in UI, but repo/branch scoping should be hardened.
  - Duplicate React key risk has been addressed by composite keys and event dedupe, but needs browser-console verification.
- Suggested next fix
  - Move queue state and steering/cancel checkpoints into a backend run coordinator that the agent loop actively checks.
- Verification commands or UI steps
  - Start a long run, queue two messages, confirm first disappears from queued list when promoted, steer one item, cancel another, stop active run.

## 15. Active Run Persistence / Thread Scoping Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/web/src/components/chat/ChatApp.tsx`
  - `apps/web/src/components/chat/ThreadSidebar.tsx`
- Relevant functions/classes/components/routes
  - `start_active_run`
  - `append_run_event`
  - `complete_active_run`
  - `get_active_runs`
  - `list_run_events`
  - `GET /agent/runs/active`
  - `GET /agent/runs/{run_id}`
  - `GET /agent/runs/{run_id}/events`
- How it currently works
  - Run metadata and events are persisted under `~/.repooperator/runs`.
  - Events include `run_id`, `thread_id`, repo, branch, sequence, and timestamp.
  - Active runs can be looked up by `thread_id`.
  - UI stores active run maps per thread and polls/rehydrates events.
- What user-facing behavior exists
  - Progress can continue when navigating away and returning.
  - Other threads can show compact running indicators instead of full progress content.
- What is still missing
  - SSE reconnect with `last_event_id` is not fully implemented; fallback is polling/events fetch.
  - Active run state is not a complete backend job queue; it records and rehydrates but does not manage all execution lifecycle concerns.
- Known bugs or risks
  - If stream and polling both deliver events, dedupe relies on event IDs/sequences and frontend normalization.
  - Thread/repo/branch scoping should be covered by tests.
- Suggested next fix
  - Add durable active-run integration tests for thread switching, page navigation, completion while away, and refresh.
- Verification commands or UI steps
  - Start long run in Thread A, switch to Thread B, confirm no Thread A progress leaks; return to Thread A and verify rehydration.

## 16. Streaming / Activity Timeline / Timers Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/web/src/components/chat/ProgressTimeline.tsx`
  - `apps/web/src/components/chat/ChatApp.tsx`
- Relevant functions/classes/components/routes
  - `stream_agent_orchestration_graph`
  - `append_run_event`
  - `normalizeActivityEvents`
  - `mergeProgressStep`
  - `ProgressTimeline`
- How it currently works
  - Streamed event types include progress/activity deltas, assistant deltas, reasoning deltas, final message, and errors.
  - Activity timeline is now chronological-first in the component, with category badges rather than full-list grouping.
  - Running item duration is computed from `started_at` on the frontend with a one-second tick.
  - Completed items freeze duration from `ended_at` or stored duration.
  - Event keys use stable composite data such as run, sequence, type, and index.
- What user-facing behavior exists
  - Users see activity rows with labels, statuses, category badges, and timers.
  - Completed work log remains available after final answer.
- What is still missing
  - Plan steps can stream live, but the underlying graph still may batch significant work in a single function.
  - Assistant delta streaming and reasoning delta handling require provider-specific verification.
  - Raw `<think>` tag separation should be tested with models that emit those tags.
- Known bugs or risks
  - Browser timer behavior requires manual verification after route changes and rehydration.
  - If backend events lack unique IDs, frontend composite keys prevent React warnings but backend uniqueness should still improve.
- Suggested next fix
  - Standardize activity event schema from backend and add UI tests for chronological rendering, live timers, dedupe, and remount.
- Verification commands or UI steps
  - Start a long run and watch timers increment 0s, 1s, 2s.
  - Navigate to Debug and back; timers continue from original `started_at`.

## 17. Changed Files UI / Diff Drawer Status

- Status: Partial
- Relevant files
  - `apps/web/src/components/chat/ChangedFilesArchive.tsx`
  - `apps/web/src/components/chat/ChangedFileDrawer.tsx`
  - `apps/web/src/components/chat/ProposalCard.tsx`
  - `apps/web/src/components/chat/ChatMessages.tsx`
  - `apps/web/src/app/globals.css`
- Relevant functions/classes/components/routes
  - `ChangedFilesArchive`
  - `ChangedFileDrawer`
  - Proposal diff viewer styles/components
- How it currently works
  - Changed files are shown compactly with filename, additions, deletions, and status.
  - Full path is available via title/tooltip behavior.
  - Clicking a changed file opens a right-side drawer.
  - Drawer is read-only and should not show Apply/Reject buttons.
- What user-facing behavior exists
  - Users can inspect already-applied file diffs and copy path/diff.
- What is still missing
  - Keyboard accessibility and dark-mode polish need verification.
  - Drawer diff design is adapted from proposal style but should be visually reviewed.
- Known bugs or risks
  - If changed file event lacks diff content, drawer may be sparse.
- Suggested next fix
  - Add frontend tests for compact list, hover path, drawer open/close, no Apply/Reject controls, copy buttons, and dark mode.
- Verification commands or UI steps
  - Run an auto-edit, click a changed file, verify polished read-only diff drawer with path/copy controls.

## 18. Sidebar / Layout Status

- Status: Partial
- Relevant files
  - `apps/web/src/components/chat/ThreadSidebar.tsx`
  - `apps/web/src/components/chat/ChatApp.tsx`
  - `apps/web/src/app/globals.css`
- Relevant functions/classes/components/routes
  - Sidebar collapsed state handlers
  - Thread running indicator rendering
- How it currently works
  - Left sidebar can collapse/expand.
  - Collapsed state persists in local storage.
  - A floating expand button is intended to remain visible at the left edge.
  - Thread items can show active-run spinner/ring indicators.
- What user-facing behavior exists
  - Users can hide the thread sidebar and expand the chat area.
- What is still missing
  - Needs browser verification that collapsed expand button is not clipped, is keyboard accessible, and works in dark mode/responsive layout.
- Known bugs or risks
  - Active run spinner and collapse rail can visually conflict if not tested at small widths.
- Suggested next fix
  - Add visual/UI tests for collapsed sidebar, floating expand button, active thread spinner, and mobile layout.
- Verification commands or UI steps
  - Collapse sidebar, refresh, verify button remains visible and accessible; expand again.

## 19. Memory / Memory Graph Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/memory_service.py`
  - `apps/local-worker/src/repooperator_worker/services/thread_context_service.py`
  - `apps/web/src/app/debug/page.tsx`
- Relevant functions/classes/components/routes
  - `record_memory`
  - `list_memory_items`
  - `_build_memory_graph`
  - `GET /debug/memory`
  - Debug Memory table and graph
- How it currently works
  - Memory records are stored under RepoOperator home, not in the repo.
  - Memory graph is built from memory/thread/run-related data.
  - Debug Memory includes table and graph views.
  - Graph supports clusters/filters for repositories, threads, files, symbols, skills, runs, proposals/edits, commands, and memories.
- What user-facing behavior exists
  - Debug can show memory records and a visual graph when data exists.
- What is still missing
  - Memory triggers are limited. It is not guaranteed every useful conversation produces memory.
  - Explicit `remember...` and accepted/applied edit memory need more tests.
  - Graph performance limits are not established.
- Known bugs or risks
  - If no memory-worthy events are captured, Debug still appears empty even after chat.
- Suggested next fix
  - Add deterministic memory triggers for explicit preferences, repo instructions, applied edit summaries, recurring project facts, and explicit remember requests.
- Verification commands or UI steps
  - Discuss a file/symbol, apply an edit, ask to remember a preference, then open Debug > Memory graph.

## 20. Events / Runs Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/event_service.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/web/src/app/debug/page.tsx`
- Relevant functions/classes/components/routes
  - `record_agent_run`
  - `record_event`
  - `start_active_run`
  - `append_run_event`
  - `complete_active_run`
  - `GET /debug/runtime`
  - `GET /agent/runs/*`
- How it currently works
  - Global events and per-run events are stored in JSONL files under `~/.repooperator/runs`.
  - Run metadata tracks run ID, thread ID, repo, branch, task summary, status, timestamps, final result, and error.
  - Per-run events are ordered by sequence.
- What user-facing behavior exists
  - Debug Events/Runs can show recent runs and active runs.
  - Chat UI can rehydrate activity logs from run events.
- What is still missing
  - Not every UI queue/steering lifecycle event is persisted as a backend event.
  - Event schema is flexible JSON, not strongly versioned.
  - Compaction/routine events are not meaningful because those features are missing.
- Known bugs or risks
  - Debug can show sparse/no recent runs if event writes fail or if only UI-local state occurred.
- Suggested next fix
  - Define a versioned run event schema and make all agent, file, command, queue, steer, cancel, memory, config reload, and source switch actions append events.
- Verification commands or UI steps
  - Ask any chat question, run a command, edit a file, queue a message, steer/cancel, then inspect Debug > Events/Runs.

## 21. Git / GitLab Workflow Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/command_service.py`
  - `apps/local-worker/src/repooperator_worker/services/tool_service.py`
  - `apps/local-worker/src/repooperator_worker/services/skills_service.py`
- Relevant functions/classes/components/routes
  - `_plan_git_workflow`
  - `_git_action_from_classifier`
  - `_git_status_workflow`
  - `_git_recent_commit_workflow`
  - `_git_commit_plan_workflow`
  - `_git_push_plan_workflow`
  - `get_tools_status`
- How it currently works
  - Git workflow skill exists.
  - Git actions can plan/run status, diff, recent commit, commit plan, push plan, and MR create plan.
  - Commit/push commands go through command approval.
  - `glab` detection and auth status are available through tool service.
  - MR list/view uses `glab` when available/authenticated.
- What user-facing behavior exists
  - Users can ask for git status, recent commit info, commit planning, push planning, and MR information.
- What is still missing
  - Git action mapping still has deterministic text/action fallback.
  - Missing `glab` install flow is not fully implemented as a managed sandbox installer.
  - GitLab API fallback is limited or absent; `glab` is the primary path.
  - MR create flow should be manually verified for preview and approval.
- Known bugs or risks
  - Auth output sanitization exists in services but must be checked in every UI path.
  - Self-managed GitLab host handling must be tested from actual remotes.
- Suggested next fix
  - Make Git/GitLab workflows skill-driven plans using command service for every command and add tests for status, log, commit, push, MR list, auth failure, and missing glab.
- Verification commands or UI steps
  - Ask for current branch state, recent commit details, commit current changes, push current branch, and MR list in a GitLab repo.

## 22. Composio Integration Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/composio_service.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `apps/web/src/app/debug/page.tsx`
- Relevant functions/classes/components/routes
  - `get_composio_status`
  - `get_composio_toolkits`
  - `get_composio_accounts`
  - `get_composio_connect`
  - `GET /integrations/composio/status`
  - `GET /integrations/composio/toolkits`
  - `GET /integrations/composio/accounts`
  - `POST /integrations/composio/connect`
- How it currently works
  - `REPOOPERATOR_COMPOSIO_API_KEY` is supported.
  - Without an API key, Debug shows Not configured/setup guidance.
  - With an API key, service attempts status/toolkit/account API calls and redacts the key.
- What user-facing behavior exists
  - Debug Integrations can show real not-configured/configured/error state instead of vague Coming soon text.
- What is still missing
  - Full OAuth/connect/link flow is not implemented.
  - It is not a full Composio tool execution integration.
  - Onboarding mention may be limited.
- Known bugs or risks
  - API behavior depends on current Composio endpoints and SDK/API compatibility. No fake connected state should be shown.
- Suggested next fix
  - Add official SDK/API-backed connect flow with account linking, toolkit selection, and no secret exposure.
- Verification commands or UI steps
  - Open Debug > Integrations without API key.
  - Set `REPOOPERATOR_COMPOSIO_API_KEY`, restart/reload worker, and verify configured/error status without exposing the key.

## 23. vLLM / Model Provider Status

- Status: Partial to implemented foundation
- Relevant files
  - `packages/cli/src/index.js`
  - `apps/local-worker/src/repooperator_worker/config.py`
  - `apps/local-worker/src/repooperator_worker/services/model_client.py`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
  - `README.md`
- Relevant functions/classes/components/routes
  - vLLM onboarding prompts in CLI
  - `OpenAICompatibleModelClient`
  - model connectivity checks
  - `GET /health`
- How it currently works
  - vLLM is offered as a local runtime alongside Ollama.
  - Provider stores as `vllm`.
  - Base URL, model name, and optional API key are supported.
  - Connectivity checks call OpenAI-compatible `/models`.
  - Worker uses OpenAI-compatible code path.
- What user-facing behavior exists
  - Users can configure local or LAN vLLM endpoints and see safe provider/model/base URL status.
- What is still missing
  - vLLM is not started by RepoOperator, by design.
  - Reasoning/thinking fields for vLLM need provider-specific verification.
  - README has vLLM docs but still has old permission/read-only text elsewhere.
- Known bugs or risks
  - `/models` endpoint shape varies across providers; configured model validation can still be partial.
- Suggested next fix
  - Add provider integration tests with mocked `/models`, missing model, and chat 404 errors.
- Verification commands or UI steps
  - Configure vLLM with `http://127.0.0.1:8001/v1`, verify `/models`, health, doctor/status, and chat.

## 24. Context Compression / Routines Status

### Context Compression

- Status: Missing
- Relevant files
  - No complete implementation found.
- Relevant functions/classes/components/routes
  - None confirmed as complete.
- How it currently works
  - Thread context exists, but automatic token estimation/compaction is not implemented as a product feature.
- What user-facing behavior exists
  - No complete context usage indicator or manual compact action verified.
- What is still missing
  - Token estimate, UI context usage, automatic compaction, manual compact, compacted summary, compaction events, and LangGraph compacted-summary loading.
- Known bugs or risks
  - Long-running chats may lose relevance or exceed model context without a robust compaction path.
- Suggested next fix
  - Implement thread token estimation, compacted summary storage, recent-message retention, and debug visibility.
- Verification commands or UI steps
  - Long chat should show context usage and preserve file/symbol context after compaction.

### Routines

- Status: Missing
- Relevant files
  - Debug page has no confirmed Routines tab/panel.
- Relevant functions/classes/components/routes
  - None confirmed as complete.
- How it currently works
  - Routine creation/run/storage is not implemented.
- What user-facing behavior exists
  - None verified.
- What is still missing
  - Routines page/panel, create routine, run routine, routine storage, LangGraph execution path, Events/Runs logging, and scheduling placeholder.
- Known bugs or risks
  - Docs/prompts may mention routines ahead of implementation.
- Suggested next fix
  - Add simple manual routines CRUD and run-through-agent path.
- Verification commands or UI steps
  - Create a “Check repo health” routine, run it, and verify Events/Runs.

## 25. Chat Copy / Export Status

- Status: Partial
- Relevant files
  - `apps/web/src/components/chat/ChatMessages.tsx`
  - `apps/web/src/components/chat/ChatApp.tsx`
  - `apps/web/src/components/chat/ChangedFilesArchive.tsx`
- Relevant functions/classes/components/routes
  - Message copy buttons
  - Copy chat/export helpers
- How it currently works
  - Per-message copy and chat copy/export have been implemented in the web UI.
  - Changed-file summaries can be included in chat metadata.
- What user-facing behavior exists
  - Users can copy messages and chat transcripts.
- What is still missing
  - Needs verification that copied/exported text includes queued/steering events, work logs, changed files, errors, and trace while filtering secrets.
- Known bugs or risks
  - Copy output may omit newer event types if not wired into transcript serialization.
- Suggested next fix
  - Add transcript snapshot tests covering changed files, command approvals, queue/steering/cancel, errors, and trace redaction.
- Verification commands or UI steps
  - Run a chat with activity, edit, command approval, queued item, and error; copy/export chat and inspect output.

## 26. Debug Page Status

- Status: Partial
- Relevant files
  - `apps/web/src/app/debug/page.tsx`
  - `apps/web/src/lib/local-worker-client.ts`
  - `apps/local-worker/src/repooperator_worker/api/routes.py`
- Relevant functions/classes/components/routes
  - `/debug`
  - Dashboard
  - Agents
  - Memory
  - Skills
  - Integrations
  - Tools
  - Events/Runs
  - Settings
- How it currently works
  - Debug page renders multiple panels backed by worker endpoints.
  - It can show runtime/model/source status, memory graph, skills, integrations, tools, recent runs, and settings.
- What user-facing behavior exists
  - Users can inspect many runtime and observability surfaces from `/debug`.
- What is still missing
  - Routines panel is missing.
  - Some panels still show shallow data or placeholders when backing events are sparse.
  - Active queue/steering/cancel events are not comprehensively shown.
- Known bugs or risks
  - Debug can appear stale if worker config or source caches were not reloaded.
- Suggested next fix
  - Make Debug consume the same durable state used by chat for active runs, sources, permissions, queues, and config revisions.
- Verification commands or UI steps
  - Open `/debug` while a run is active; confirm active run, events, source/model state, tools, memory graph, and changed files.

## 27. Korean Output Quality Status

- Status: Partial
- Relevant files
  - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
  - `apps/local-worker/src/repooperator_worker/services/model_client.py`
  - `apps/local-worker/tests`
- Relevant functions/classes/components/routes
  - Prompt builders for final answers and summaries
  - Response cleanup/repair helpers if present in graph/model services
- How it currently works
  - Agent prompts include instructions to answer in natural Korean when the user asks in Korean and preserve code identifiers/paths/commands.
  - There are output-quality tests in the local-worker test suite.
- What user-facing behavior exists
  - Korean responses are expected to avoid malformed multilingual artifacts and unsupported file claims.
- What is still missing
  - Cleanup/repair is lightweight and may not catch all artifacts.
  - Hallucination control depends on files-read evidence and prompt compliance.
- Known bugs or risks
  - Model output can still misidentify languages or make unsupported security claims if file evidence is weak.
- Suggested next fix
  - Add stronger evidence tags in answers and a repair pass for obvious cross-language artifacts.
- Verification commands or UI steps
  - Ask Korean project analysis questions after reading Python files and verify natural Korean, correct language identification, and evidence-based claims.

## 28. Test Matrix

| Scenario category | Expected behavior | Current result | Status | Evidence / files | Next fix |
|---|---|---|---|---|---|
| Re-onboarding changes vLLM model while worker running | Worker reloads or restarts, health shows new effective model | Reload support exists; end-to-end not verified | Partial | `packages/cli/src/index.js`, `/admin/reload-config`, `/health` | Add integration test with running worker |
| Add GitHub after GitLab and show both in Debug | Both sources visible after reload | Source list foundations exist; not manually verified | Partial | `ProjectSelector`, Debug dashboard | Add source merge/cache tests |
| Switch non-default provider in Web UI | Selected provider loads projects regardless of default | Intended support exists; stale default coupling risk remains | Partial | `ProjectSelector`, repository endpoints | Add provider-order tests |
| Pasted coding-agent prompt with no apply request | Summarize/ask intent, no edit | Intent category exists | Partial | `_handle_pasted_spec` | Add varied spec tests |
| Pasted coding-agent prompt with explicit apply request | Plan first, no arbitrary target | Apply intent exists | Partial | `apply_spec_to_repo` | Add confirmation/plan tests |
| Project improvement recommendations then follow-up apply | Structured context selects recommendations/files | Context service exists; robustness partial | Partial | `recommendation_context_service.py` | Store stronger per-file evidence |
| Multi-file maintenance request | Ordered plan reads/edits all relevant files | Multi-step exists but not true loop | Partial | `_decompose_and_execute` | Promote steps to graph loop |
| Auto file edit inside active repo | Edit auto-applies after validation, changed files shown | Graph path can auto-write; legacy paths remain | Partial | `_execute_plan_step`, `ChangedFilesArchive` | Resolve permission/edit UX split |
| Command request requiring approval | Approval card for mutating/network commands | Command service implemented | Implemented foundation | `command_service.py` | Expand command tests |
| Git recent commit request | Uses `git log`, not status | Workflow exists | Partial | `_git_recent_commit_workflow` | Add service-level tests |
| Commit current changes request | Inspect status/diff, propose message, approval for add/commit | Workflow exists | Partial | `_git_commit_plan_workflow` | Verify in UI |
| MR list request | Use glab/API or explain missing auth/tool | glab path exists | Partial | `tool_service.py`, command service | Add self-managed/auth tests |
| Queue message during active run | Message appears above composer and waits | UI implemented, localStorage | Partial | `ChatApp.tsx`, `ChatComposer.tsx` | Move queue server-side |
| Steer queued item into active run | Calls steer endpoint, activity event recorded, loop adapts | Endpoint records; adaptation not proven | Partial | `record_run_steering` | Add loop checkpoint consumption |
| Stop active run | Run cancelling/cancelled, no corruption | Endpoint marks cancelled | Partial | `request_run_cancellation` | Add interrupt-safe execution |
| Switch threads while run active | Progress scoped to original thread; spinner on original | UI maps active runs by thread | Partial | `ChatApp.tsx`, `ThreadSidebar.tsx` | Add UI tests |
| Navigate to Debug while run active and return | Rehydrate active run events | Event endpoints exist | Partial | `/agent/runs/*` | Add reconnect tests |
| Activity timer live count | Running item counts upward; completed freezes | Frontend interval implemented | Partial | `ProgressTimeline.tsx` | Browser test |
| Changed-file drawer | Compact list opens read-only diff drawer | UI exists | Partial | `ChangedFileDrawer.tsx` | Visual/accessibility tests |
| Sidebar collapse/expand | Visible floating expand button, persisted state | UI exists | Partial | `ThreadSidebar.tsx`, CSS | Browser test |
| Memory graph clustering | Real clustered graph with filters/details | Graph foundation exists | Partial | Debug page, `memory_service.py` | Add data-rich tests |
| Composio no API key | Shows Not configured/setup instructions | Implemented foundation | Partial | `composio_service.py` | Verify UI |
| Composio with API key | Shows configured/status or API error, no key | API calls exist | Partial | `composio_service.py` | Mock API tests |
| skills.md layering | Built-ins, repo, user layered | Discovery exists | Partial | `skills_service.py` | Add overwrite regression tests |
| Korean project analysis quality | Natural Korean, evidence-based | Prompt/tests partial | Partial | graph/model tests | Strengthen repair/evidence |
| Invalid structured edit output | Error card, no raw JSON diff | Validation exists | Partial | `_validate_patch` | Add refusal/prose tests |
| npm pack stale files | Tarball excludes duplicate stale files | Dry-run tarball did not list `page 2.tsx` or lock duplicates; tests included | Partial | `npm pack --dry-run` | Clean stale files and review manifest |

## 29. Commands Run

- Status: Partial
- Relevant files
  - `apps/local-worker/tests`
  - `apps/web`
  - `packages/cli`
- Relevant functions/classes/components/routes
  - Test suites and build scripts.
- How it currently works
  - Backend unit tests pass.
  - Web build passes.
  - CLI syntax check passes.
  - Package dry-run from `packages/cli` succeeds.
- What user-facing behavior exists
  - The codebase can currently build/test at a baseline level.
- What is still missing
  - No full browser/UI automation was run in this audit.
  - `npm --prefix packages/cli pack --dry-run` failed from repo root; equivalent command from package directory passed.
- Known bugs or risks
  - Frontend lint/test harness appears incomplete; previous `npm --prefix apps/web run lint` prompted for ESLint setup.
- Suggested next fix
  - Add non-interactive frontend test/lint configuration.
- Verification commands or UI steps
  - `PYTHONPATH=apps/local-worker/src python3 -m unittest discover -s apps/local-worker/tests`
    - Result: pass, 49 tests.
  - `npm --prefix apps/web run build`
    - Result: pass.
  - `node --check packages/cli/src/index.js`
    - Result: pass.
  - `npm --prefix packages/cli pack --dry-run`
    - Result: failed with `ENOENT` for root `package.json`.
  - `npm pack --dry-run` from `packages/cli`
    - Result: pass, `repooperator-0.2.5.tgz` dry-run package.
  - OpenPatch grep with exclusions
    - Result: no active code references; only historical docs references found.
  - Stale duplicate file search
    - Result: duplicate-looking package lock files and `page 2.tsx` present in working tree.

## 30. Final Output Summary

- Status: Red
- Relevant files
  - Most important review files:
    - `apps/local-worker/src/repooperator_worker/services/agent_orchestration_graph.py`
    - `apps/local-worker/src/repooperator_worker/services/agent_service.py`
    - `apps/local-worker/src/repooperator_worker/services/event_service.py`
    - `apps/local-worker/src/repooperator_worker/services/permissions_service.py`
    - `apps/local-worker/src/repooperator_worker/services/command_service.py`
    - `apps/local-worker/src/repooperator_worker/services/recommendation_context_service.py`
    - `apps/local-worker/src/repooperator_worker/services/skills_service.py`
    - `apps/local-worker/src/repooperator_worker/services/memory_service.py`
    - `apps/web/src/components/chat/ChatApp.tsx`
    - `apps/web/src/components/chat/ChatComposer.tsx`
    - `apps/web/src/components/chat/ProgressTimeline.tsx`
    - `apps/web/src/components/chat/ChangedFilesArchive.tsx`
    - `apps/web/src/components/chat/ChangedFileDrawer.tsx`
    - `apps/web/src/app/debug/page.tsx`
    - `packages/cli/src/index.js`
- Relevant functions/classes/components/routes
  - Same as the sections above.
- How it currently works
  - RepoOperator has many important foundations, but still behaves like an alpha with overlapping control paths and partial state durability.
- What user-facing behavior exists
  - CLI bootstrap, web chat, debug page, LangGraph routing, local commands, permissions UI, queue/steer/cancel UI, changed-file UI, memory graph, integrations status, vLLM support.
- What is still missing
  - True single agent loop, unified permission/edit semantics, durable queue/steering/cancel semantics, routines, context compression, full Composio OAuth, fully verified source/model reload behavior, and updated documentation.
- Known bugs or risks
  - The highest-priority blocker is still architectural: agent state and execution are spread across graph functions, legacy-compatible services, UI-local state, and flexible event records.
- Suggested next fix
  - Suggested next Codex prompt:
    - "Work directly in `/Users/junginkim/Documents/GitHub/RepoOperator`. Consolidate active run execution into a backend-owned agent run coordinator: make queue, steering, cancellation, activity events, auto file edits, and command approvals durable and thread/repo/branch scoped. Do not add new product features. Remove UI-local-only queue semantics after backend endpoints are in place. Add tests for thread switching, queue promotion, steering acceptance/rejection, cancellation, and event rehydration."
- Verification commands or UI steps
  - Re-run the commands in section 29 after any changes.
