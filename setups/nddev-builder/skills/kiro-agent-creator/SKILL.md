---
name: kiro-agent-creator
description: Create or revise native Kiro agent Markdown/frontmatter for the NDDev builder projection, including resources and maximum tool-category access.
---

# Kiro Agent Creator

Read first:

- `../nddev-builder/references/agents-subagents.md`
- `../nddev-builder/references/skills-instructions.md`

Workflow:

1. Keep the managed builder agent under `agents/nddev-builder.md`.
2. Preserve native Markdown plus YAML frontmatter.
3. Keep the maximum native tool category for the builder agent; permission
   restriction belongs in selected `permissions.yaml` profiles.
4. Keep agent resources on the entry skill, reference owners, and steering; the
   entry skill routes to the focused skill layer.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
