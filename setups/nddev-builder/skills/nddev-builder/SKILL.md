---
name: nddev-builder
description: Build, review, and validate public NDDev setup-manager modules for Kiro CLI native surfaces.
---

# NDDev Builder

Use this skill for public Kiro CLI setup-manager work: runtime lifecycle,
content setup catalogs, permission profiles, native Kiro configuration surfaces,
public contracts, public documentation, and release metadata.

## Required Orientation

Before changing behavior, read these repository-owned facts:

- `config/nddev-contract.json` for the public product contract.
- `references/kiro-cli-baseline.json` for official Kiro source evidence,
  native discovery paths, platform support, and runtime status.
- `cli-tools/nddev_kiro_cli.py` for executable manager behavior.
- `cli-tools/validate_public_contracts.py` for public invariants.

Do not copy volatile versions, checksums, platform lists, launch guards, managed
file lists, or profile enumerations into new prose. Point to the owner files
above.

## Routing

- Configuration, setup catalogs, profile switching, managed settings:
  `references/configuration-profiles.md`
- Permissions, approval behavior, sandbox claims, and launch safety:
  `references/permissions-sandbox.md`
- Agents, tool access, resources, and subagent boundaries:
  `references/agents-subagents.md`
- Agent Skills, steering, AGENTS.md, and instruction layering:
  `references/skills-instructions.md`
- Hooks:
  `references/hooks.md`
- MCP configuration:
  `references/mcp.md`
- Native plugin or marketplace questions:
  `references/plugins-marketplace.md`
- Target-owned Kiro CLI installation and runtime lifecycle:
  `references/installation-lifecycle.md`
- Creator, checker, and release-readiness validation:
  `references/creator-checker-release.md`

Load only the references needed for the current task.

## Validation

For public-module-only validation, run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kiro_cli.py list --json
```

For lifecycle behavior, use an isolated temporary target and the manager CLI.
Never use live `~/.kiro`, live Kiro software, private validation fixtures, or
provider credentials from the caller environment.
