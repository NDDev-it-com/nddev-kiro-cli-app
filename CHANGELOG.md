# Changelog

## 0.2.2

- Pin the official stable Kiro CLI 2.16.0 manifest with exact provenance for all 24 vendor artifacts.
- Refresh canonical build, runtime, platform-package, and public validation contracts.

## 0.2.1

- Capture and strictly resolve the caller workspace once at launch entry and
  pass it explicitly as the Kiro child working directory.
- Declare target/workspace roles in public status and contracts without adding
  an unsupported native workspace option.

## 0.2.0

- Breaking pre-1.0: replace setup variants with one `nddev-builder` content
  setup plus orthogonal `full-auto` and `safe` permission profiles.
- Make `full-auto` the default profile and keep managed launch on Kiro v3
  `--v3`, recorded as early-access-required in the public baseline.
- Add current managed schema with explicit legacy status, migrate, restore, and
  remove boundaries; legacy managed state cannot launch.
- Update official stable Kiro CLI artifact provenance and target-owned install
  contract.
- Pin Kiro CLI 2.15.1 and scope product software installs to macOS arm64/x64
  and Ubuntu glibc arm64/x64 while preserving all upstream assets as observed
  vendor evidence.
- Expand the managed `nddev-builder` Agent Skills toolkit with routed focused
  references for native Kiro setup, permissions, agents, skills, hooks, MCP,
  installation lifecycle, marketplace limits, and validation workflows.

## 0.1.0

- Add target-explicit Kiro CLI setup manager.
- Add `safe`, `balanced`, and `full-auto` setup variants.
- Add native `nddev-builder` projection with Kiro agents, skills, steering, and hooks.
- Add public contract, manifest, runtime baseline, validator, and shared-CI
  workflow callers.
