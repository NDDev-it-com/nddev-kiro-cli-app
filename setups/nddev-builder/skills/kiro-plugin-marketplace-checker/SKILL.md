---
name: kiro-plugin-marketplace-checker
description: Check Kiro plugin and marketplace requests against the public baseline, rejecting unsupported marketplace emulation or private catalog leakage.
---

# Kiro Plugin Marketplace Checker

Read first:

- `../nddev-builder/references/plugins-marketplace.md`
- `../nddev-builder/references/creator-checker-release.md`

Checklist:

1. Keep marketplace projection `null` unless official Kiro CLI documentation
   defines a native surface and the baseline/contract change first.
2. Do not emulate a marketplace with generated catalog files, private harness
   metadata, Codex plugin formats, Amazon Q aliases, or CodeWhisperer concepts.
3. If native support appears later, add baseline evidence, contract shape,
   manager behavior, and validator assertions in the same public-module change.
4. Validate with `python3 cli-tools/validate_public_contracts.py`.
