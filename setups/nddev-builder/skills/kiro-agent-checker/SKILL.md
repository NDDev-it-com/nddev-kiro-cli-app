---
name: kiro-agent-checker
description: Check native Kiro agent files, resources, subagent boundaries, tool access, and NDDev builder projection consistency.
---

# Kiro Agent Checker

Read first:

- `../nddev-builder/references/agents-subagents.md`
- `../nddev-builder/references/permissions-sandbox.md`

Checklist:

1. Confirm the agent frontmatter stays native Kiro Markdown/YAML.
2. Confirm tool access remains the full native category and is not replaced by
   a hand-maintained partial list.
3. Confirm subagent availability is native tool/permission behavior, not a
   separate unmanaged file projection.
4. Confirm resources point to installed public builder files only.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
