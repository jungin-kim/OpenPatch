# OpenPatch Security Notes

## Overview

OpenPatch is designed around a security-sensitive boundary: a local worker can read files and execute commands on a developer machine, while a central backend can perform model inference on selected context. The system should therefore be conservative by default and explicit about trust boundaries.

This document captures the first-pass security posture for the project.

## Local Worker Binds To `localhost`

The local worker should bind only to `127.0.0.1` or another loopback interface by default.

Why this matters:

- repository access and command execution are high-trust operations
- exposing the worker on a network interface would dramatically increase the attack surface
- most workflows only require a browser on the same machine to talk to the worker

Early design guidance:

- do not bind to `0.0.0.0` by default
- require deliberate opt-in for any non-local exposure
- include clear warnings if remote access modes are ever introduced

## Command Execution Risk

Command execution is one of the highest-risk capabilities in OpenPatch.

Risks include:

- destructive filesystem changes
- secret exposure through command output
- package install scripts or untrusted shell behavior
- commands that differ across local environments and shells

Initial guardrails should include:

- explicit user-visible execution requests
- narrow command execution interfaces
- working-directory awareness
- captured stdout and stderr for review
- timeouts and cancellation support
- clear distinction between proposed actions and executed actions

Longer term, the project may also add policy hooks, command allowlists, or interactive approval layers, but the earliest version should at least make all command execution observable and deliberate.

## Secret Handling

OpenPatch should avoid centralizing secrets wherever possible.

Guidelines:

- local credentials used for git, package registries, or shell tooling should remain on the developer machine
- secrets should not be embedded in prompts unless they are explicitly required
- logs should avoid dumping full environment variables or sensitive command output
- any stored tokens for the hosted UI or backend should be scoped minimally and documented clearly

The local worker should treat command environments, `.env` files, and repository configuration as potentially sensitive sources.

## Minimal Context Transmission

The central model backend should receive only the context required for the current task.

This is important because:

- source code may be proprietary even when the platform is open-source
- repositories can contain credentials, customer data samples, or internal infrastructure details
- smaller prompts improve privacy posture and often improve system efficiency

Practical direction:

- read only the files or ranges needed for the current task
- prefer diffs, summaries, and excerpts over entire repository snapshots
- avoid transmitting ignored files, generated artifacts, or local machine metadata unless necessary
- make upstream context collection explicit in the worker protocol

## Trust Boundaries

OpenPatch has at least three trust zones:

1. Browser and hosted UI session
2. Local worker with repository and command access
3. Central backend with model-provider access

Each boundary should be documented and treated explicitly. The worker is not merely a proxy. It is the component with the highest local privilege and should be designed as such.

## Secure Defaults For Early Development

As implementation begins, the project should favor these defaults:

- localhost-only worker binding
- explicit user initiation of repository attachment
- minimal file and command scope
- no background remote repository mirroring by default
- no assumption that full repository contents are sent upstream
- auditable logs that avoid sensitive payload duplication

## Open Questions

Security work should continue alongside implementation. Important follow-up areas include:

- authentication and pairing between hosted UI sessions and the local worker
- CSRF or origin protections for localhost worker endpoints
- transport encryption and token handling between UI, worker, and backend
- redaction strategies for logs and traces
- approval workflows for writes and commands
- threat modeling for malicious prompts or prompt-injected repository content

The initial goal is not to claim complete security. It is to establish clear boundaries and sensible defaults before implementation expands.
