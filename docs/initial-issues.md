# RepoOperator Initial Issue Backlog

This document proposes an initial GitHub issue backlog for RepoOperator based on the current repository structure and the documented roadmap.

The backlog is organized around:

- epics for major workstreams
- milestones aligned to the roadmap phases
- actionable issues with suggested labels

Priority is intentionally weighted toward the local worker MVP so the project can prove its core architecture before deeper UI and agent integration work begins.

## Proposed Epics

### Epic 1: Local Worker MVP

Establish a safe, auditable localhost worker that can attach to repositories, read files, run commands, and generate diffs.

### Epic 2: Shared Contracts And Agent Foundations

Define common schemas and execution primitives that keep the worker, web UI, and future model backend aligned.

### Epic 3: Hosted Web UI MVP

Build the first usable browser workflow for worker connection checks, task submission, and response display.

### Epic 4: Security And Trust Boundaries

Harden the local worker boundary, minimize data transmission, and document early security guarantees and tradeoffs.

### Epic 5: Contributor Experience And Docs

Improve onboarding, issue hygiene, development workflow, and documentation quality for early contributors.

## Proposed Milestones

### Milestone: Phase 1 - Local Worker MVP

Scope:

- worker API stability
- repository attach and open behavior
- file read and write foundations
- command execution and diff behavior
- basic tests and safety guardrails

### Milestone: Phase 2 - Central Model Integration

Scope:

- shared request and response schemas
- agent execution loop foundations
- minimal context packaging
- model backend interface definition

### Milestone: Phase 3 - Hosted UI MVP

Scope:

- worker health checks from the browser
- task submission flow
- response streaming shell
- basic diff and patch presentation

### Milestone: Phase 4 - Editing Workflow

Scope:

- patch apply and file write flows
- review UX
- validation command reruns

### Milestone: Phase 5 - Git Workflow

Scope:

- branch and commit flows
- push preparation
- provider-aware remote workflows

### Milestone: Phase 6 - Packaging And Deployment

Scope:

- install and run guidance
- environment configuration
- local and hosted deployment ergonomics

## Proposed Issues

### 1. Define initial shared API schema package for worker requests and responses

Description:
Create the first shared schema module in `packages/shared` for worker-facing request and response payloads so the web UI, local worker, and future backend do not drift.

Suggested labels:
`architecture`, `worker`, `agent`

Milestone:
Phase 1 - Local Worker MVP

### 2. Add automated tests for local worker service layer

Description:
Add unit tests for repository path validation, file reads, command execution behavior, timeout handling, and git diff responses.

Suggested labels:
`worker`, `good first issue`

Milestone:
Phase 1 - Local Worker MVP

### 3. Implement `POST /fs/write` endpoint for controlled local file updates

Description:
Add the first write endpoint to the worker with path safety checks, overwrite rules, and clear error handling. This is a prerequisite for later editing workflows.

Suggested labels:
`worker`

Milestone:
Phase 1 - Local Worker MVP

### 4. Add worker capability discovery endpoint

Description:
Implement a worker endpoint that reports supported operations, version, and runtime details needed by the web UI to adapt to worker capabilities.

Suggested labels:
`worker`, `architecture`

Milestone:
Phase 1 - Local Worker MVP

### 5. Harden repository path validation and workspace boundaries in the worker

Description:
Review and improve repo path handling so worker operations stay within an intended repository root and produce predictable errors for invalid or unsafe paths.

Suggested labels:
`worker`, `security`

Milestone:
Phase 1 - Local Worker MVP

### 6. Improve `/repo/open` to support fetch-and-checkout flows cleanly

Description:
Refine repository open behavior so existing repositories can fetch remote updates, check out target branches more predictably, and return structured status details.

Suggested labels:
`worker`

Milestone:
Phase 1 - Local Worker MVP

### 7. Add structured command execution logging and request IDs

Description:
Introduce request identifiers and structured logs for worker actions so command execution and repository operations can be traced without leaking excessive context.

Suggested labels:
`worker`, `security`, `architecture`

Milestone:
Phase 1 - Local Worker MVP

### 8. Add command execution policy hooks for approval and allowlist checks

Description:
Create extension points in the worker for future approval flows, command policies, or allowlists before more powerful edit and git operations are enabled.

Suggested labels:
`worker`, `security`

Milestone:
Phase 1 - Local Worker MVP

### 9. Define minimal context packaging contract for model requests

Description:
Document and prototype how file excerpts, diffs, and command results should be packaged before they are sent to the central model backend.

Suggested labels:
`architecture`, `agent`, `security`

Milestone:
Phase 2 - Central Model Integration

### 10. Scaffold `packages/agent-core` execution loop interfaces

Description:
Create the first agent-core interfaces for task state, tool invocation envelopes, streamed events, and orchestration primitives that can be reused across services.

Suggested labels:
`agent`, `architecture`

Milestone:
Phase 2 - Central Model Integration

### 11. Draft central model backend API contract

Description:
Write an initial API proposal for task submission, streamed responses, and tool or action envelopes so backend work can proceed independently of the UI.

Suggested labels:
`architecture`, `agent`, `docs`

Milestone:
Phase 2 - Central Model Integration

### 12. Implement worker health check polling in the web UI

Description:
Wire the web app to poll the localhost worker health endpoint and render connected, unavailable, and error states in the worker connection panel.

Suggested labels:
`web`, `worker`

Milestone:
Phase 3 - Hosted UI MVP

### 13. Add browser-side configuration for local worker base URL

Description:
Introduce a small configuration layer for the web app so localhost worker URLs and future environment-specific settings are not hard-coded in components.

Suggested labels:
`web`, `good first issue`

Milestone:
Phase 3 - Hosted UI MVP

### 14. Implement task submission shell from web UI to backend-facing client

Description:
Turn the current task input area into a real form flow with local state, submit handling, disabled states, and a clean client abstraction for future backend calls.

Suggested labels:
`web`, `agent`

Milestone:
Phase 3 - Hosted UI MVP

### 15. Build placeholder streamed response state model in the web app

Description:
Define the UI state model for pending, streaming, completed, and failed task responses so real backend streaming can be added without redesigning the page.

Suggested labels:
`web`, `agent`

Milestone:
Phase 3 - Hosted UI MVP

### 16. Add localhost origin and CSRF protection design note for worker endpoints

Description:
Document the first approach for protecting worker endpoints accessed from the browser, including origin expectations, token ideas, and local trust assumptions.

Suggested labels:
`security`, `docs`, `architecture`

Milestone:
Phase 1 - Local Worker MVP

### 17. Create issue templates for bug reports and feature proposals

Description:
Add initial GitHub issue templates under `.github/ISSUE_TEMPLATE` to help contributors file reproducible bugs and focused feature requests.

Suggested labels:
`docs`, `good first issue`

Milestone:
Phase 1 - Local Worker MVP

### 18. Expand contributor setup docs for web and worker development

Description:
Document a simple end-to-end local development workflow covering the FastAPI worker, the Next.js app, expected ports, and basic troubleshooting steps.

Suggested labels:
`docs`, `good first issue`

Milestone:
Phase 1 - Local Worker MVP

## Suggested Issue Ordering

Recommended first wave:

1. Define initial shared API schema package for worker requests and responses
2. Add automated tests for local worker service layer
3. Implement `POST /fs/write` endpoint for controlled local file updates
4. Add worker capability discovery endpoint
5. Harden repository path validation and workspace boundaries in the worker
6. Improve `/repo/open` to support fetch-and-checkout flows cleanly
7. Add command execution policy hooks for approval and allowlist checks
8. Add localhost origin and CSRF protection design note for worker endpoints

This ordering keeps the first milestone centered on making the worker API safer, more stable, and easier for the future web and agent layers to consume.
