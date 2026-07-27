# Installation And Lifecycle

Use this reference when changing target-owned Kiro CLI software installation,
runtime launch, status, backup, migration, restore, or remove behavior.

## Native Provenance

The public baseline owns the current official stable manifest URL, artifact
paths, checksums, byte sizes, platform support, and installer script evidence.
Do not copy those volatile values into prose.

The official vendor shell installer is evidence only for this manager. It is
not the manager install primitive because it is not faithful to an isolated
target on every supported host.

## Target-Owned Install Design

The manager installs only into the explicit target under
`target/.nddev-runtime/software/kiro-cli`. It downloads the official manifest
and selected official artifact, verifies pinned SHA-256 and size values, stages
extraction, validates the bounded software tree, writes a target-bound software
stamp, and atomically promotes the staged tree.

Linux uses official zip artifacts. macOS uses the official DMG artifact and
extracts the app-contained CLI into the target-owned tree. Windows is
unsupported.

## Lifecycle Commands

Use these public manager commands:

```bash
python3 cli-tools/nddev_kiro_cli.py software-status --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-probe --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-install --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-update --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py software-remove --target /absolute/temp-kiro-home --json
```

`software-install` requires an absent software tree. `software-update` repairs
safe partial state or current drift, but fails on absent state with an
install-first domain error.

Managed launch requires clean current managed content state and clean
target-owned software, isolates `KIRO_HOME`, `HOME`, XDG, and logs under the
target, strips provider credential environment variables, and blocks
managed-scope Kiro commands or flags before the child process starts.

## Validation Workflow

For non-live public validation, run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py software-status --target /absolute/temp-kiro-home --json
```

Only run networked probe/install/update when the task explicitly permits
official artifact access.
