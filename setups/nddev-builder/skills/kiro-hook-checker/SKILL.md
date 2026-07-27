---
name: kiro-hook-checker
description: Check Kiro hook surface decisions and prevent unsupported target-managed hook projection in the public NDDev Kiro module.
---

# Kiro Hook Checker

Read first:

- `../nddev-builder/references/hooks.md`
- `../nddev-builder/references/creator-checker-release.md`

Checklist:

1. Treat hooks as native workspace discovery unless the public baseline and
   contract are updated first.
2. Do not install `hooks/nddev-builder.json` into managed `KIRO_HOME`.
3. Keep legacy hook state read-only except status, migrate, restore, and remove.
4. Require current official Kiro hook documentation before adding any future
   hook-authoring behavior.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
