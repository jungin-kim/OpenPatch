# OpenPatch CLI

The OpenPatch CLI is the first product-oriented onboarding surface for the project.

It currently provides:

- `openpatch onboard`
- `openpatch doctor`
- `openpatch status`

## Install

From the repository root:

```bash
npm install -g ./packages/cli
```

## Commands

### `openpatch onboard`

Creates the local OpenPatch config directory, writes a config file, and prepares the machine for future daemon installation.

### `openpatch doctor`

Checks whether the local configuration, worker detection, worker reachability, model backend config, and git provider config look healthy.

### `openpatch status`

Prints the current OpenPatch configuration summary and worker status.
