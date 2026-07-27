# Configuration And Profiles

Use this reference when changing content setup metadata, managed settings,
profile selection, migration semantics, or setup/profile CLI flags.

## Native Paths

- Kiro home defaults to `~/.kiro`.
- `KIRO_HOME` overrides the global Kiro home for this manager's target.
- Managed settings are written to `KIRO_HOME/settings/cli.json`.
- Managed permissions are composed from `profiles/<profile>/permissions.yaml`
  and written to `KIRO_HOME/settings/permissions.yaml`.
- Content setup sources live under `setups/<setup-id>/`.
- Permission profile sources live under `profiles/<profile-id>/`.

## Public Model

The public model is orthogonal:

- A content setup controls deterministic Kiro-native files and managed settings.
- A permission profile controls only native `permissions.yaml` content.
- Future setup switching must keep those axes separate.

The exact current setup IDs, profile IDs, defaults, managed keys, and managed
files are owned by the public contract, manifest, and manager code. Do not copy
those enumerations into documentation.

## Schema Guidance

`setups/<setup-id>/setup.json` is a regular JSON object with stable metadata
for the content setup, including managed content files, managed settings, the
default profile, supported profiles, and whether the builder projection is
enabled.

`profiles/<profile-id>/profile.json` is a regular JSON object declaring the
profile id, description, and `permissions.yaml` filename.

The manager must reject unknown setup IDs and unknown profile IDs before writing
the target. It must preserve unmanaged settings keys when composing
`settings/cli.json`.

## Validation Workflow

Run these checks after changing setup/profile files:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py list --json
python3 cli-tools/nddev_kiro_cli.py plan --setup nddev-builder --profile full-auto --target /absolute/temp-kiro-home --json
```

Use a temporary absolute target for lifecycle tests.
