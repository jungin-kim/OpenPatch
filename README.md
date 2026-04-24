# OpenPatch

OpenPatch is an open-source coding agent architecture for teams that want:

- a hosted web UI
- a local worker running on each developer machine
- centralized model inference
- repository operations performed locally, not on a central server

## Why OpenPatch?

Most coding-agent systems fall into one of two categories:

1. Everything runs on a central server, including repository checkout and file operations
2. Everything runs locally on a developer machine

OpenPatch is designed for a third model:

- **UI is centralized**
- **model inference is centralized**
- **repository clone, file access, patch application, and command execution happen locally**

This architecture is useful when teams want:

- shared access through a hosted web app
- centralized GPU/model infrastructure
- local repository ownership and execution
- stronger control over what code leaves a developer machine

## Core architecture

```text
Browser
  -> Hosted Web UI
  -> Local Worker on the developer machine
  -> Local repository clone, file reads/writes, command execution
  -> Central model API
```
Project status

OpenPatch is currently in the early design / build phase.

The first goal is to create a minimal end-to-end system with:

a local worker API
repository clone/pull
file read/write
command execution
central model inference
a simple hosted UI
Planned components
Hosted Web UI

The hosted web UI handles:

authentication
project selection
task input
result display
patch/diff review
future PR/MR workflows
Local Worker

The local worker runs on each developer machine and handles:

cloning or updating repositories
reading and writing files
generating diffs
running tests and shell commands
applying patches
Central Model Backend

The model backend handles:

prompt completion
tool-aware planning
patch generation
response streaming
Design principles
local repositories stay local
model inference can be centralized
protocol between UI and worker should be explicit and portable
git provider support should be pluggable
the system should support GitHub, GitLab, and self-hosted setups over time
Initial roadmap
Phase 1

Local worker MVP

GET /health
POST /repo/open
POST /fs/read
POST /cmd/run
POST /git/diff
Phase 2

Central model integration

model client abstraction
task execution loop
context collection from local repositories
Phase 3

Hosted UI MVP

authentication
local worker connection check
task composer
streamed responses
Phase 4

Editing workflow

write files
apply patches
show diffs
run tests
Phase 5

Git provider integration

branch creation
commit/push
pull request / merge request creation
Non-goals for the first version
full autonomous multi-repo orchestration
enterprise policy enforcement
fine-grained remote execution scheduling
deep IDE integration
Contributing

Contributions, design feedback, and implementation ideas are welcome.

See:

docs/architecture.md
docs/roadmap.md
docs/security.md
CONTRIBUTING.md
License

MIT
