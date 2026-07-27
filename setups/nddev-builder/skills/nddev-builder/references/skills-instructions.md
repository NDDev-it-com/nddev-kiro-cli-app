# Skills And Instructions

Use this reference when changing Agent Skills, steering, AGENTS.md, or
instruction onboarding.

## Native Paths

- Global skills: `KIRO_HOME/skills/<skill-name>/SKILL.md`
- Workspace skills: `.kiro/skills/<skill-name>/SKILL.md`
- Skill references: files under the skill directory, commonly
  `references/*.md`
- Global steering: `KIRO_HOME/steering/*.md`
- Workspace steering: `.kiro/steering/*.md`
- AGENTS.md may be used as repository or global steering context where Kiro
  discovers it.

The managed toolkit installs an entry skill plus focused references under
`KIRO_HOME/skills/nddev-builder/`.

## Skill Schema Guidance

An Agent Skill uses Markdown with YAML frontmatter. Keep entry skill routing
precise and progressive: route to focused references instead of loading every
topic up front.

Use references for stable native path/schema guidance. For volatile facts such
as current Kiro version, artifact checksums, managed file lists, profile IDs,
and launch blocklists, point to the public contract, baseline, validator, or
manager code.

## Instruction Boundary

Public module instructions must remain English and public. Do not include
private validation procedures, private durable memory, private evidence bundles,
live paths, credentials, or orchestrator-only workflow steps.

## Validation Workflow

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```

The public validator must check that every routed reference path exists.
