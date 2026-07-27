---
name: kiro-permissions-checker
description: Check native Kiro permissions.yaml profiles, approval behavior, and sandbox wording for NDDev public module correctness.
---

# Kiro Permissions Checker

Read first:

- `../nddev-builder/references/permissions-sandbox.md`
- `../nddev-builder/references/installation-lifecycle.md`

Checklist:

1. Confirm permission profile files use native Kiro `permissions.yaml` rules.
2. Confirm full-auto and safe are profiles, not content setups.
3. Reject invented balanced/vendor-named profiles and unsupported sandbox claims.
4. Confirm launch still strips credentials and denies managed-scope overrides.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
