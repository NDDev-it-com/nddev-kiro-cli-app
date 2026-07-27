# Agents And Subagents

Use this reference when changing the managed builder agent, agent resources,
tool access, or subagent boundaries.

## Native Paths

- Global agents: `KIRO_HOME/agents/<agent-name>.md`
- Workspace agents: `.kiro/agents/<agent-name>.md`

The managed builder installs `KIRO_HOME/agents/nddev-builder.md`.

## Managed Agent Schema

The managed agent is Markdown with YAML frontmatter and a Markdown body. The
frontmatter must keep the Kiro-native maximum tool category:

```yaml
description: NDDev builder setup-module implementation agent.
tools: ["*"]
resources:
  - skill://~/.kiro/skills/nddev-builder/SKILL.md
  - file://~/.kiro/skills/nddev-builder/references/**/*.md
  - file://~/.kiro/steering/nddev-builder.md
welcomeMessage: "NDDev builder context loaded."
```

Do not replace `tools: ["*"]` with a hand-maintained partial tool list.
Maximum capability is required so MCP, todo, knowledge, subagents, web,
read/write/shell, and future Kiro built-ins remain discoverable. Permission
control belongs in the selected `permissions.yaml` profile.

The public setup does not define separate subagent files. It preserves native
agent discovery and grants subagent availability through native tool access and
permissions.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py install --target /absolute/temp-kiro-home --json
```

Then inspect the temporary target's `agents/nddev-builder.md` and stamp digest.
