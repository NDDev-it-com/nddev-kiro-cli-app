---
name: kiro-skill-creator
description: Create or revise native Kiro Agent Skills for the NDDev builder toolkit using progressive disclosure and code-owned facts.
---

# Kiro Skill Creator

Read first:

- `../nddev-builder/references/skills-instructions.md`
- `../nddev-builder/references/creator-checker-release.md`

Workflow:

1. Use one `SKILL.md` per focused skill directory.
2. Keep frontmatter to native Kiro skill metadata and keep bodies concise.
3. Route to reference owners instead of copying current version pins, managed
   file enumerations, profile rules, or validator internals.
4. Add every installed skill file to setup metadata, manager projection,
   manifest, contract, and public validator constants.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
