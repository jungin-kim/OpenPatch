# RepoOperator Roadmap

## Principles

The roadmap is organized around small, testable vertical slices. Each phase should leave the repository in a usable state and reduce uncertainty for the next one.

The goal is not to build every feature immediately. The goal is to prove the architecture with the simplest implementation that can support real contributor iteration.

## Phase 0: Repo / Bootstrap / Docs

Focus:

- create the initial repository structure
- document architecture and security assumptions
- define package boundaries
- agree on naming and protocol direction

Outcomes:

- repository scaffold in place
- first-pass project docs complete
- contribution guidelines available
- implementation backlog shaped for MVP work

## Phase 1: Local Worker MVP

Focus:

- build a small local worker bound to `localhost`
- define a narrow HTTP or RPC surface
- support repository attachment and basic local operations

Target capabilities:

- health check
- repository open or attach
- file read
- file write
- command execution
- diff generation

Success criteria:

- a developer can point RepoOperator at a local repository
- the worker can safely execute a constrained set of local operations
- request and response schemas are stable enough for UI and backend integration

## Phase 2: Central Model Integration

Focus:

- add a central model backend
- define structured task requests and response streaming
- build the first orchestration loop between worker and model backend

Target capabilities:

- provider abstraction
- prompt assembly from local context
- streamed model responses
- structured tool or action envelopes

Success criteria:

- a task can collect minimal repository context locally and send it to the model backend
- the backend can return actionable edits or next-step instructions
- the integration works without moving repository ownership off the developer machine

## Phase 3: Hosted UI MVP

Focus:

- build the first hosted web interface
- connect a browser session to a local worker and model backend
- support task submission and streamed output display

Target capabilities:

- session bootstrap
- worker connectivity check
- task composer
- streamed execution view
- simple diff or patch presentation

Success criteria:

- a user can submit a task from the browser
- the UI can coordinate with the local worker
- model output can be reviewed in a usable interface

## Phase 4: Editing Workflow

Focus:

- move from read-only reasoning to controlled local editing
- add patch generation, preview, and application flows
- support local validation after edits

Target capabilities:

- patch preview
- file write and patch apply
- command reruns for verification
- basic acceptance and rejection UX

Success criteria:

- a user can review and apply proposed changes
- the worker can run local validation commands
- edit operations are transparent and reversible through normal git workflows

## Phase 5: Git Workflow

Focus:

- integrate branch and commit workflows
- support remote collaboration after local edits are complete

Target capabilities:

- branch creation
- status and diff inspection
- commit creation
- push support
- pull request or merge request preparation

Success criteria:

- a task can move from local edits to a clean git workflow
- users retain control over commits and remote publication
- git provider specifics remain pluggable rather than hard-coded

## Phase 6: Packaging And Deployment

Focus:

- make the system installable and runnable by contributors
- improve developer onboarding and operational packaging

Target capabilities:

- repeatable local worker installation
- backend deployment guidance
- hosted UI deployment guidance
- environment configuration examples
- release process outline

Success criteria:

- a new contributor can run the stack with reasonable effort
- the project can be deployed in a small self-hosted environment
- packaging choices do not lock the project into a single platform

## Cross-Cutting Work

These areas should be revisited throughout all phases:

- security review
- protocol versioning
- logging and observability
- test strategy
- contributor experience
- documentation quality

## Notable Non-Goals For Early Phases

- large-scale autonomous multi-repository orchestration
- full enterprise policy engines
- deep IDE-specific integrations
- tightly coupled assumptions about a single git hosting provider

The initial priority is a clean, understandable open-source foundation.
