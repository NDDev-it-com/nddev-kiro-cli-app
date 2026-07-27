# Hooks

Use this reference when changing hook documentation or deciding whether hooks
belong in the managed target projection.

## Native Path

Kiro v3 hooks are workspace files:

```text
.kiro/hooks/<name>.json
```

No global `KIRO_HOME/hooks` discovery path is part of this public managed
target contract.

## Schema Guidance

Kiro v3 hook files are JSON. The public module only treats the top-level hook
file shape as native Kiro data and does not synthesize hook definitions. Hook
event names, matchers, and command fields must be taken from current official
Kiro documentation before any future hook authoring support is added.

The setup manager must not install `hooks/nddev-builder.json` into `KIRO_HOME`.
Legacy managed hook files may be read only for status, migrate, restore, and
remove.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py install --target /absolute/temp-kiro-home --json
```

The temporary target must not contain `hooks/nddev-builder.json` after current
managed install or migration.
