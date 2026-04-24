# OpenPatch Onboarding

OpenPatch is moving toward a developer-product onboarding flow built around:

- one-command install
- one-command onboarding
- a local worker on each developer machine
- a centralized model backend
- pluggable git providers such as GitLab and GitHub

The first step in that direction is the new `openpatch` CLI.

## Install The CLI

From the repository root:

```bash
npm install -g ./packages/cli
```

This makes the `openpatch` command available on your machine.

## Run Onboarding

```bash
openpatch onboard
```

The onboarding flow will:

1. create the local OpenPatch config directory
2. create a config file
3. prompt for model backend settings
4. prompt for git provider selection
5. prompt for a local repo base directory
6. detect whether a local worker installation is already present
7. prepare local directories for a future daemon installation flow

## Run Diagnostics

After onboarding:

```bash
openpatch doctor
```

This validates:

- config file exists
- local worker installation is detected
- local worker is reachable
- model backend config is present
- git provider config is present

## View Current Status

```bash
openpatch status
```

This prints the current configuration summary and worker reachability.

## Localhost Worker Expectation

At the current phase, OpenPatch still assumes the worker runs on the local machine and binds to `127.0.0.1`.

That means:

- the worker remains the trusted local execution layer
- repository reads, writes, diffs, commands, and git actions stay local
- the CLI and current web flow assume a localhost worker URL

## Current Limits

The current onboarding phase is real, but intentionally minimal:

- it prepares configuration and local directories
- it detects repo-source worker availability
- it does not yet install a background daemon automatically
- it does not yet provide a one-command hosted pairing flow

Those are the next product steps after the first onboarding surface is stable.

## Related Docs

- [README](../README.md)
- [Deployment guide](../DEPLOYMENT.md)
- [Local worker setup](local-worker-setup.md)
- [Troubleshooting](troubleshooting.md)
