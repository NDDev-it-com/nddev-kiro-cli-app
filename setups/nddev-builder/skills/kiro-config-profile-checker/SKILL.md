---
name: kiro-config-profile-checker
description: Check Kiro setup catalog, profile metadata, managed settings, and setup/profile switching behavior for public contract consistency.
---

# Kiro Config Profile Checker

Read first:

- `../nddev-builder/references/configuration-profiles.md`
- `../nddev-builder/references/permissions-sandbox.md`

Checklist:

1. Confirm setup IDs, profile IDs, defaults, managed settings, and managed file
   projection are owned by the public contract, manifest, manager, and validator.
2. Confirm setup files are deterministic regular files and unmanaged settings
   keys are preserved.
3. Confirm profile switching does not mutate content setup semantics.
4. Validate with `python3 cli-tools/validate_public_contracts.py` and
   `python3 cli-tools/nddev_kiro_cli.py list --json`.
