# Plugins And Marketplace

Use this reference when a task asks about Kiro plugins, extensions,
marketplaces, or catalog projection.

## Native Status

No native Kiro CLI marketplace or plugin projection is part of this public
contract. The builder projection records marketplace as `null`.

Do not emulate a marketplace with generated catalog files, private harness
metadata, Amazon Q concepts, CodeWhisperer aliases, or Codex plugin formats.

If Kiro later documents an official native plugin or marketplace surface, update
the public baseline and contract first, then add manager behavior and public
validation in the same module-only change.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```

The validator must fail if marketplace projection becomes non-null without a
contract update.
