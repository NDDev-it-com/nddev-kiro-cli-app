---
name: kiro-config-profile-creator
description: Create or revise Kiro setup catalog and permission profile metadata while keeping content setup and profile selection orthogonal.
---

# Kiro Config Profile Creator

Read first:

- `../nddev-builder/references/configuration-profiles.md`
- `../nddev-builder/references/creator-checker-release.md`

Workflow:

1. Keep content setup metadata under `setups/<setup-id>/`.
2. Keep permission profile metadata under `profiles/<profile-id>/`.
3. Preserve future switching semantics: setup controls content, profile controls
   native permissions only.
4. Do not add a balanced profile or vendor-named profile without an exact native
   Kiro meaning recorded in the baseline and contract.
5. Validate with `python3 cli-tools/validate_public_contracts.py`,
   `python3 cli-tools/nddev_kiro_cli.py list --json`, and a temporary-target
   `plan` command.
