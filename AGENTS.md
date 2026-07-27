# nddev-kiro-cli-app

This public repository contains Kiro CLI setup-manager implementation, setup
sources, public contracts, release metadata, and public documentation only.
Private tests, benchmarks, fixtures, durable memory, and harness profiles belong
outside this repository.

Use `config/nddev-contract.json`, `build/manifest.json`, and
`references/kiro-cli-baseline.json` as the code-owned source of truth for exact
setup IDs, permission profiles, managed files, Kiro version, native discovery
paths, runtime launch boundaries, platform support, and artifact provenance.

Keep the public model minimal: one content setup, orthogonal permission
profiles, target-owned software, explicit targets, target-bound backups, and
fail-closed launch behavior. Do not introduce a balanced profile unless Kiro
defines a precise native meaning for one.

Do not introduce Amazon Q or CodeWhisperer aliases as product surfaces. Kiro's
Amazon Q migration history may be documented only as migration context. Do not
invent marketplace or plugin formats for Kiro CLI.
