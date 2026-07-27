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

Load a focused skill for the concrete task, then load only the references it
names:

- Public module creation or revision:
  `skill://~/.kiro/skills/kiro-module-creator/SKILL.md`
- Public module checking and unsupported-surface review:
  `skill://~/.kiro/skills/kiro-module-checker/SKILL.md`
- Release metadata and package readiness:
  `skill://~/.kiro/skills/kiro-release-checker/SKILL.md`
- Setup catalog or profile metadata creation:
  `skill://~/.kiro/skills/kiro-config-profile-creator/SKILL.md`
- Setup catalog or profile metadata checking:
  `skill://~/.kiro/skills/kiro-config-profile-checker/SKILL.md`
- Native permission profile creation:
  `skill://~/.kiro/skills/kiro-permissions-creator/SKILL.md`
- Native permission profile checking:
  `skill://~/.kiro/skills/kiro-permissions-checker/SKILL.md`
- Native builder agent creation:
  `skill://~/.kiro/skills/kiro-agent-creator/SKILL.md`
- Native builder agent checking:
  `skill://~/.kiro/skills/kiro-agent-checker/SKILL.md`
- Agent Skill creation:
  `skill://~/.kiro/skills/kiro-skill-creator/SKILL.md`
- Agent Skill checking:
  `skill://~/.kiro/skills/kiro-skill-checker/SKILL.md`
- Hook surface checking:
  `skill://~/.kiro/skills/kiro-hook-checker/SKILL.md`
- MCP surface checking:
  `skill://~/.kiro/skills/kiro-mcp-checker/SKILL.md`
- Plugin or marketplace surface checking:
  `skill://~/.kiro/skills/kiro-plugin-marketplace-checker/SKILL.md`
- Installation, runtime, migration, backup, restore, remove, and launch
  checking: `skill://~/.kiro/skills/kiro-lifecycle-checker/SKILL.md`

Reference owner routes:

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
