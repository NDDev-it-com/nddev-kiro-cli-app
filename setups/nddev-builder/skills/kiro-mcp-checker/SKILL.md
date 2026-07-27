---
name: kiro-mcp-checker
description: Check Kiro MCP configuration boundaries, native discovery paths, launch guards, and credential handling for the NDDev Kiro module.
---

# Kiro MCP Checker

Read first:

- `../nddev-builder/references/mcp.md`
- `../nddev-builder/references/permissions-sandbox.md`
- `../nddev-builder/references/installation-lifecycle.md`

Checklist:

1. Treat MCP as native Kiro configuration and runtime discovery, not as a
   generated target-managed server catalog.
2. Confirm no MCP credentials or private server definitions are committed.
3. Confirm managed launch blocks caller arguments that override MCP or trust
   scope.
4. Keep `tools: ["*"]` discoverability and let the selected permissions profile
   control approval behavior.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
