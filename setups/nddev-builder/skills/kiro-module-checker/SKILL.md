---
name: kiro-module-checker
description: Check public Kiro CLI setup-module changes for contract drift, unsupported native surfaces, safety regressions, and missing validation.
---

# Kiro Module Checker

Read first:

- `../nddev-builder/references/creator-checker-release.md`
- `../nddev-builder/references/installation-lifecycle.md`
- `../nddev-builder/references/plugins-marketplace.md`

Checklist:

1. Confirm every changed public surface is owned by this module.
2. Reject private fixtures, memories, evidence bundles, live user paths,
   credentials, and root-harness assumptions.
3. Confirm new behavior is backed by current contract, baseline, manager code,
   and validator assertions.
4. Treat undocumented Kiro plugin, marketplace, hook-management, or sandbox
   claims as unsupported until the baseline and contract change first.
5. Run `python3 cli-tools/validate_public_contracts.py` before release review.
