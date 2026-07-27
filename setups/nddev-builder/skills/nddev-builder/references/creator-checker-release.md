# Creator, Checker, And Release Validation

Use this reference when adding public Kiro setup content, changing manager
behavior, reviewing release readiness, or preparing public-module commits.

## Creator Checklist

- Keep public changes in this module.
- Keep private tests, fixtures, benchmarks, durable memory, and evidence out of
  this module.
- Add only native Kiro surfaces verified in the baseline and contract.
- Keep content setup and permission profile behavior orthogonal.
- Keep setup files deterministic regular files.
- Keep launch fail-closed for drift, legacy schema, unmanaged targets, and
  managed-scope argument overrides.

## Checker Workflow

Run the public validator:

```bash
python3 cli-tools/validate_public_contracts.py
```

Then exercise focused isolated lifecycle commands with an absolute temporary
target:

```bash
python3 cli-tools/nddev_kiro_cli.py list --json
python3 cli-tools/nddev_kiro_cli.py plan --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py install --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py status --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py switch --profile safe --target /absolute/temp-kiro-home --json
python3 cli-tools/nddev_kiro_cli.py remove --target /absolute/temp-kiro-home --json
```

Do not use live `~/.kiro` or live installed Kiro software for public validation.

## Release Readiness

Public release metadata must agree with `VERSION`, `build/version.json`,
`build/manifest.json`, `config/nddev-contract.json`, and
`references/kiro-cli-baseline.json`.

Private release gates and root orchestration are outside this public module.
