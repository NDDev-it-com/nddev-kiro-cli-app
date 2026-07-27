---
name: kiro-lifecycle-checker
description: Check Kiro target-owned installation, lifecycle locking, launch isolation, migration, backup, restore, remove, and status behavior.
---

# Kiro Lifecycle Checker

Read first:

- `../nddev-builder/references/installation-lifecycle.md`
- `../nddev-builder/references/permissions-sandbox.md`
- `../nddev-builder/references/creator-checker-release.md`

Checklist:

1. Confirm lifecycle mutations use explicit absolute targets and never live
   `~/.kiro`.
2. Confirm launch requires clean current setup state plus clean target-owned
   software and holds lifecycle exclusion through child cleanup.
3. Confirm official artifact provenance, stamps, backups, rollback, and
   restore/remove behavior remain target-bound and fail-closed.
4. Confirm runtime `HOME`, `TMPDIR`, XDG, logs, and settings stay writable while
   software and launcher artifacts remain immutable.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
