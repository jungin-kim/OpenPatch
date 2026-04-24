# Contributing To OpenPatch

Thanks for considering a contribution to OpenPatch.

This project is being built as a general-purpose, open-source foundation for coding-agent workflows with a hosted UI, a local worker, and a centralized model backend. Early contributions are especially valuable because they help shape the architecture and contributor experience from the beginning.

## Development Principles

Please keep these principles in mind when contributing:

- prefer simple, inspectable interfaces over clever hidden behavior
- keep repository operations local unless there is a clear reason not to
- keep model integration provider-agnostic where possible
- minimize the amount of source code and machine context sent upstream
- make risky actions reviewable, observable, and explicit
- choose portable abstractions over deployment-specific shortcuts

## Repository Structure

The repository is currently organized as follows:

- `apps/web`: hosted web application
- `apps/local-worker`: local repository and command worker
- `packages/shared`: shared types, protocol definitions, and utilities
- `packages/agent-core`: agent orchestration primitives
- `docs`: architecture, roadmap, and security notes

As implementation evolves, please keep package boundaries intentional and update documentation when those boundaries change.

## Working Style

Small, focused pull requests are strongly preferred.

Good PRs usually:

- solve one clear problem
- keep the scope easy to review
- include or update tests when behavior changes
- update docs when interfaces or assumptions change
- avoid unrelated cleanup in the same patch

If a change is large, consider splitting it into a preparatory refactor and a feature patch.

## Good First Contribution Areas

Helpful early contribution areas include:

- shared request and response schema design
- local worker API shape and capability boundaries
- transport and event model proposals
- documentation improvements and examples
- security review and threat-model feedback
- contributor tooling and local development setup
- basic tests and fixtures for future worker and backend code

If you want a small starting point, docs, types, tests, and narrow interface proposals are all strong first contributions.

## Pull Request Guidance

When opening a PR:

- explain the problem being solved
- explain the chosen approach and any tradeoffs
- call out follow-up work that is intentionally out of scope
- keep the diff narrow enough that reviewers can reason about it quickly

If your PR changes architecture or protocol assumptions, please also update the relevant files in `docs/`.

## Issues And Discussions

Design discussions are welcome, especially around:

- local worker trust and security model
- protocol definitions between UI, worker, and backend
- editing and git workflow UX
- packaging and deployment options
- test strategy across components

When reporting a bug or proposing a feature, include enough context to reproduce the problem or evaluate the design tradeoff.

## Code Of Conduct

Until a dedicated code of conduct is added, please interact with other contributors respectfully, assume good intent, and keep feedback constructive and specific.

## License

By contributing to OpenPatch, you agree that your contributions will be licensed under the MIT License.
