# Permissions And Sandbox

Use this reference when changing native permission profiles, approval behavior,
or safety claims.

## Native Path

Kiro v3 permissions are configured at
`KIRO_HOME/settings/permissions.yaml`.

## Schema Guidance

The file is YAML with a top-level `rules` list. Rules use native Kiro fields
such as `capability`, `match`, `exclude`, and `effect`. Effects are native Kiro
approval outcomes.

The full-auto profile is intentionally maximum capability for isolated
automation targets:

```yaml
rules:
  - capability: all
    effect: allow
```

The safe profile remains a native ask/deny profile. Its exact current rules are
owned by `profiles/safe/permissions.yaml` and by the manager's public validator.

Do not invent vendor-named profiles. Do not add a balanced profile unless Kiro
defines an exact native meaning for one.

## Safety Boundary

Kiro permissions are not a sandbox claim. The manager's safety boundary is:
explicit absolute target, isolated `KIRO_HOME`, target-local child `HOME` and
XDG directories, secret environment stripping, target-bound stamps and backups,
regular-file writes, bounded reads, drift detection, and rollback.

Managed launch must deny legacy managed state before invoking Kiro.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py install --profile full-auto --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py switch --profile safe --target /absolute/temp-kiro-home --json
```

Inspect only the temporary target.
