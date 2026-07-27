---
name: kiro-permissions-creator
description: Create or revise native Kiro permissions.yaml profiles for NDDev full-auto or safe behavior without inventing vendor profiles.
---

# Kiro Permissions Creator

Read first:

- `../nddev-builder/references/permissions-sandbox.md`
- `../nddev-builder/references/configuration-profiles.md`

Workflow:

1. Edit only profile-owned permission files and matching profile metadata.
2. Keep `full-auto` maximum capability for isolated automation targets.
3. Keep `safe` in documented ask/deny territory and do not claim native sandbox
   semantics beyond Kiro permissions.
4. Do not copy the full current rule list into docs; the profile file and
   validator own exact rules.
5. Validate with `python3 cli-tools/validate_public_contracts.py` and temporary
   target `install` plus `switch --profile safe`.
