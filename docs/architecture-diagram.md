# RepoOperator Architecture Diagram

This diagram shows the current intended RepoOperator architecture and the current localhost expectation for the local worker.

## High-Level Diagram

```mermaid
flowchart LR
    User["Developer"]
    Browser["Browser / Web UI"]
    Worker["Local Worker (127.0.0.1)"]
    Repo["Local Repository"]
    Git["Local Git + Toolchain"]
    Model["Centralized Model API"]
    GitLab["GitLab API (optional)"]

    User --> Browser
    Browser -->|"worker health, repo open, tasks"| Worker
    Worker -->|"read/write files"| Repo
    Worker -->|"commands, diff, commit, push"| Git
    Worker -->|"minimal repo context"| Model
    Worker -->|"merge request creation"| GitLab
```

## Localhost Expectation

The key operational assumption is:

- the worker runs on the developer machine
- the worker binds to `127.0.0.1`
- repository operations do not happen on a central clone

That means the worker is the only component that:

- sees the full local working tree
- executes local commands
- performs local git operations

## Current Development Topology

```mermaid
flowchart TD
    WebDev["Next.js Dev Server"]
    WorkerLocal["FastAPI Worker on 127.0.0.1:8000"]
    Proxy["Local API Proxy Routes"]
    ModelAPI["OpenAI-Compatible API"]

    WebDev --> Proxy
    Proxy --> WorkerLocal
    WorkerLocal --> ModelAPI
```

This is the current practical development setup. A future hosted version will need a more deliberate browser-to-local-worker connection design.

## Why The Worker Stays Local

- repository state is already on the user machine
- command execution is only meaningful in the local environment
- credentials and development tooling are often local
- fewer repository contents need to leave the machine

## Related Docs

- [Architecture](architecture.md)
- [Security](security.md)
- [Deployment guide](../DEPLOYMENT.md)
