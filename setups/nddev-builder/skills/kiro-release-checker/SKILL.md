---
name: kiro-release-checker
description: Check public Kiro CLI module release metadata, package closure, workflow policy, and version/changelog consistency before a module release commit.
---

# Kiro Release Checker

Read first:

- `../nddev-builder/references/creator-checker-release.md`
- `../nddev-builder/references/installation-lifecycle.md`

Workflow:

1. Compare `VERSION`, `CHANGELOG.md`, `build/version.json`,
   `build/manifest.json`, `config/nddev-contract.json`, and
   `references/kiro-cli-baseline.json` through the public validator.
2. Keep release package paths public, tracked when `.git` is present, and
   complete when checked from an extracted archive.
3. Do not duplicate workflow pins or artifact hashes in skill prose; the
   validator and baseline own those values.
4. Run `python3 cli-tools/validate_public_contracts.py` and `git diff --check`.
