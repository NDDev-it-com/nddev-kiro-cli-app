---
name: kiro-module-creator
description: Create or revise public Kiro CLI setup-module implementation surfaces while preserving the NDDev public/private boundary.
---

# Kiro Module Creator

Read first:

- `../nddev-builder/references/creator-checker-release.md`
- `../nddev-builder/references/configuration-profiles.md`
- `../nddev-builder/references/installation-lifecycle.md`

Workflow:

1. Keep changes inside the public module unless the caller explicitly opens a
   later private phase.
2. Add only native Kiro surfaces recorded in the public contract and baseline.
3. Keep setup content, permission profiles, runtime lifecycle, release
   metadata, and docs synchronized through the manager-owned projection.
4. Do not copy volatile versions, checksums, package lists, managed file lists,
   or validation internals into prose; point to the owner files named above.
5. Validate with `python3 cli-tools/validate_public_contracts.py` and
   `python3 cli-tools/nddev_kiro_cli.py list --json`.
