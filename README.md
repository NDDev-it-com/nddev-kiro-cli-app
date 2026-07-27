# nddev-kiro-cli-app

Target-explicit NDDev setup manager for Kiro CLI.

This module manages an isolated Kiro home selected with `--target`. It never
defaults to the caller's live `~/.kiro`, never launches Kiro during install or
switch, and never reads or writes Kiro authentication state.

## Current Kiro Baseline

Use `references/kiro-cli-baseline.json`, `config/nddev-contract.json`, and
`build/manifest.json` for the current Kiro release, official provenance,
platform support, native discovery surfaces, managed projection, and runtime
requirements. Use `cli-tools/nddev_kiro_cli.py list --json` for the active
setup and permission-profile catalog.

## Usage

List the content setup and permission profiles:

```bash
python3 cli-tools/nddev_kiro_cli.py list --json
```

Inspect a target:

```bash
python3 cli-tools/nddev_kiro_cli.py status --target /absolute/kiro-home --json
```

Plan without mutating the target:

```bash
python3 cli-tools/nddev_kiro_cli.py plan --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py plan --setup SETUP_ID --profile PROFILE_ID --target /absolute/kiro-home --json
```

Install, update, switch profile, migrate legacy state, restore, or remove:

```bash
python3 cli-tools/nddev_kiro_cli.py install --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py update --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py switch --profile PROFILE_ID --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py migrate --profile PROFILE_ID --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py restore --backup 0 --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py remove --target /absolute/kiro-home --json
```

Choose `SETUP_ID` and `PROFILE_ID` from `list --json`. Legacy managed setup
state may be inspected, migrated, restored, or removed; launch is denied until
the target is migrated to the current managed schema.

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
`software-update` to repair recoverable partial installs or refresh drift;
missing updates fail with an "install first" domain error. A stamp from an older
manager build reports `needs-update` instead of becoming hard-invalid, and
`software-remove` can remove a target-owned tree with a missing or malformed
stamp after strict target trust checks. `software-status --json` reports whether
the target-owned software matches the current baseline owner; non-current
software makes launch unavailable until repaired.

Launch Kiro with the isolated target:

```bash
python3 cli-tools/nddev_kiro_cli.py launch --target /absolute/kiro-home --
```

`launch` requires clean current managed setup state and clean target-owned
software; `status --json` reports the same `launch_allowed` outcome. Launch uses
an isolated target runtime, strips provider credential state, uses a
deterministic child environment, revalidates the target-owned executable before
handoff, and holds lifecycle exclusion until the child exits. Managed-scope
overrides are rejected before launch. Exact runtime paths, lifecycle exclusion
mechanics, environment keys, executable checks, and blocked override arguments
are owned by `cli-tools/nddev_kiro_cli.py`, `config/nddev-contract.json`, and
`build/manifest.json`.

## Builder Content

The builder toolkit is deterministic and regular-file-only. The exact managed
projection, agent configuration, skill routing, profile separation, and native
surface boundaries are owned by `build/manifest.json`,
`config/nddev-contract.json`, the setup sources, and `list --json`. Builder
skills route volatile native paths and schemas back to their code-owned
references instead of copying them.

## Safety Model

The manager requires an explicit absolute target. It enforces target trust,
managed-file integrity, target-bound backups, rollback, restore boundaries, and
preservation of unmanaged state. Exact trust checks, backup layout, rollback
behavior, and removal boundaries are owned by `cli-tools/nddev_kiro_cli.py` and
the public contract.

Official install-channel and artifact provenance are tracked in
`references/kiro-cli-baseline.json`. Runtime installation is target-owned and
does not run a global installer or mutate application locations outside the
explicit target. Platform support is declared by the baseline and contract.
