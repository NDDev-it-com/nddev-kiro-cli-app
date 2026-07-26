# nddev-kiro-cli-app

Target-explicit NDDev setup manager for Kiro CLI.

This module manages an isolated Kiro home selected with `--target`. It never
defaults to the caller's live `~/.kiro`, never launches Kiro during install or
switch, and never reads or writes Kiro authentication state.

## Current Kiro Baseline

- Product: Kiro CLI
- Command: `kiro-cli`
- Current stable version: `2.14.2`
- Native config root: `~/.kiro`, overridden by `KIRO_HOME`
- Settings: `~/.kiro/settings/cli.json`
- Permissions: `~/.kiro/settings/permissions.yaml`
- Native builder projection: agents, skills, steering, v3 hooks, permissions
- Marketplace/plugin projection: unsupported and intentionally `null`

The current artifact checksums are pinned in
`references/kiro-cli-baseline.json`.

## Usage

List setup variants:

```bash
python3 cli-tools/nddev_kiro_cli.py list --json
```

Plan a setup without mutating the target:

```bash
python3 cli-tools/nddev_kiro_cli.py plan --setup safe --target /absolute/kiro-home --json
```

Install or switch:

```bash
python3 cli-tools/nddev_kiro_cli.py install --setup safe --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py switch --setup balanced --target /absolute/kiro-home --json
```

Restore or remove managed state:

```bash
python3 cli-tools/nddev_kiro_cli.py update --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py restore --backup 0 --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py remove --target /absolute/kiro-home --json
```

Inspect, stage-probe, install, update, or remove the target-owned Kiro CLI
software tree:

```bash
python3 cli-tools/nddev_kiro_cli.py software-status --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-probe --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-install --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-update --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-remove --target /absolute/kiro-home --json
```

`software-install` only installs into an absent software tree. Use
`software-update` to repair safe partial installs or refresh drift; missing or
absent updates fail with an "install first" domain error. Both mutating paths
verify the official Kiro manifest SHA-256/size and the exact pinned artifact
SHA-256/size before writing the target.

Launch Kiro with the isolated target:

```bash
python3 cli-tools/nddev_kiro_cli.py launch --target /absolute/kiro-home --
```

`launch` requires both clean managed setup state and clean target-owned
software. It sets `KIRO_HOME` to the target, places child `HOME`, XDG
directories, and logs under the target runtime directory, strips provider
credential environment variables, and invokes the target-installed
`kiro-cli --v3`. Arguments that would override the managed Kiro v3 engine,
agent, trust, auth, settings, integrations, MCP, or update scope are rejected
before the target lock is taken.

## Setup Variants

- `safe`: asks for shell, write, web, MCP, and subagent capabilities while
  allowing builder skill/context loading.
- `balanced`: allows read-only context, common local test commands, subagents,
  skills, diagnostics, and context; asks for writes and external actions.
- `full-auto`: uses Kiro v3 `permissions.yaml` with `capability: all` and
  `effect: allow` for isolated automation targets.

All variants include `nddev-builder` by default through Kiro-native files under
the selected target:

- `agents/nddev-builder.md`
- `skills/nddev-builder/SKILL.md`
- `steering/nddev-builder.md`
- `hooks/nddev-builder.json`

## Safety Model

The manager requires an explicit absolute target. It rejects target symlinks,
managed symlinks, managed hard links, oversized metadata, malformed JSON, drift
from the target-bound stamp, and backups copied from another target. Mutations
use target-bound backups and rollback on failure. It preserves unmanaged files
and unowned settings keys.

The public Kiro shell installer at `https://cli.kiro.dev/install` is tracked as
official evidence, but the manager does not execute it as the runtime install
primitive: its macOS branch writes `/Applications` and launches the app. The
manager instead uses a harness-owned official-artifact installer path that
downloads the official manifest/artifact, verifies the pinned SHA-256 and byte
sizes, extracts in staging, and atomically moves only the bounded software tree
into the explicit target.
