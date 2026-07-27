# nddev-kiro-cli-app

Target-explicit NDDev setup manager for Kiro CLI.

This module manages an isolated Kiro home selected with `--target`. It never
defaults to the caller's live `~/.kiro`, never launches Kiro during install or
switch, and never reads or writes Kiro authentication state.

## Current Kiro Baseline

The source-owned baseline is `references/kiro-cli-baseline.json`. The public
contract is `config/nddev-contract.json`.

The current public contract pins Kiro CLI stable `2.14.2`. Managed launch uses
`kiro-cli --v3` because the native permissions and agent configuration used by
this setup are Kiro v3 surfaces; the baseline records this engine as
`early-access-required`.

Kiro marketplace/plugin projection is unsupported and intentionally `null`.

## Usage

List the content setup and permission profiles:

```bash
python3 cli-tools/nddev_kiro_cli.py list --json
```

Plan without mutating the target:

```bash
python3 cli-tools/nddev_kiro_cli.py plan --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py plan --setup nddev-builder --profile safe --target /absolute/kiro-home --json
```

Install, update, switch profile, migrate legacy state, restore, or remove:

```bash
python3 cli-tools/nddev_kiro_cli.py install --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py update --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py switch --profile safe --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py migrate --profile full-auto --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py restore --backup 0 --target /absolute/kiro-home --json
python3 cli-tools/nddev_kiro_cli.py remove --target /absolute/kiro-home --json
```

`nddev-builder` is the only content setup in this release. `full-auto` is the
default permission profile. `safe` is available for ask/deny semantics.
Former `safe`, `balanced`, and `full-auto` setup IDs are legacy managed state
only: status, migrate, restore, and remove may read them, but launch is denied.

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
absent updates fail with an "install first" domain error. A stamp from an older
manager build reports `needs-update` instead of becoming hard-invalid, and
`software-remove` can remove a target-owned tree with a missing or malformed
stamp after strict target trust checks. Mutating software paths verify the
official Kiro manifest SHA-256/size and exact pinned artifact SHA-256/size
before writing the target; the public manager does not expose alternate
manifest, artifact, fixture, or environment-selected software sources.

Launch Kiro with the isolated target:

```bash
python3 cli-tools/nddev_kiro_cli.py launch --target /absolute/kiro-home --
```

`launch` requires clean current managed setup state and clean target-owned
software; `status` reports the same `launch_allowed` precondition. It sets
`KIRO_HOME` to the target, places child `HOME`, XDG
directories, and logs under the target runtime directory, strips provider
credential environment variables, uses a deterministic system `PATH`, and
invokes the target-installed `kiro-cli --v3`. Arguments that would override
managed engine, agent, trust, auth, settings, integrations, MCP, or update scope
are rejected before the target lock is taken.

## Builder Content

The managed native content is deterministic and regular-file-only:

- `agents/nddev-builder.md`
- `skills/nddev-builder/SKILL.md`
- `skills/nddev-builder/references/*.md`
- `steering/nddev-builder.md`

The canonical builder agent uses native Kiro v3 agent frontmatter with
`tools: ["*"]` so built-in tools, MCP, todo, knowledge, subagents, web,
read/write/shell, and future Kiro built-ins remain discoverable. Permission
profile behavior stays in `profiles/*/permissions.yaml`, not in the agent file.

Kiro workspace hooks and MCP configuration are native discovery surfaces, but
this target-owned setup does not synthesize or manage them.

## Safety Model

The manager requires an explicit absolute target. It rejects target symlinks,
targets not owned by the current user with mode `0700`, managed symlinks,
managed hard links, oversized metadata, malformed JSON, drift from the
target-bound stamp, and backups copied from another target. Lock and backup
state lives under the owner-private target runtime directory. Mutations use
target-bound backups and rollback on failure. It preserves unmanaged files and
unowned settings keys.

The public Kiro shell installer at `https://cli.kiro.dev/install` is tracked as
official evidence, but the manager does not execute it as the runtime install
primitive: its macOS branch writes `/Applications` and launches the app. The
manager instead downloads official stable artifacts, verifies pinned SHA-256 and
byte sizes, extracts in staging, and atomically moves only the bounded software
tree into the explicit target. Windows is not supported.
