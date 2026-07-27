---
name: kiro-skill-checker
description: Check native Kiro Agent Skills, entry routing, reference reachability, and managed builder projection completeness.
---

# Kiro Skill Checker

Read first:

- `../nddev-builder/references/skills-instructions.md`
- `../nddev-builder/references/creator-checker-release.md`

Checklist:

1. Confirm every focused skill has valid frontmatter, a body, and direct routes
   to existing reference owners.
2. Confirm the entry skill routes every focused skill.
3. Confirm setup metadata, manager constants, manifest, contract, and validator
   include every installed regular file.
4. Reject private QA, memories, live paths, or evidence in public skills.
5. Validate with `python3 cli-tools/validate_public_contracts.py`.
