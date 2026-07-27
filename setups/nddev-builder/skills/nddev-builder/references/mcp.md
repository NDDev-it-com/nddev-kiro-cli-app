# MCP

Use this reference when changing MCP documentation, agent resource boundaries,
or launch guards.

## Native Paths

Kiro MCP configuration is native Kiro JSON:

- Global target config: `KIRO_HOME/settings/mcp.json`
- Workspace config: `.kiro/settings/mcp.json`
- Agent-local config: agent frontmatter `mcpServers`

Kiro's documented priority is agent config, then workspace config, then global
config.

## Schema Guidance

MCP config uses a top-level `mcpServers` object. Server transport, command,
argument, URL, and environment details must come from official Kiro MCP
documentation and from the user's explicitly chosen MCP server.

This public setup does not install MCP servers, does not write MCP config, and
does not commit credentials. The builder agent keeps `tools: ["*"]` so native
MCP tools are discoverable when Kiro loads configured servers.

Managed launch blocks Kiro commands and flags that would override MCP or trust
scope from the caller's unmanaged arguments.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py launch --target /absolute/temp-kiro-home -- mcp
```

The second command should fail before launch because `mcp` is a managed-scope
command. It must use a temporary target.
