#!/usr/bin/env python3
"""Validate public nddev-kiro-cli-app contracts without private inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETUP_IDS = ["safe", "balanced", "full-auto"]
MANAGED_FILES = [
    "settings/cli.json",
    "settings/permissions.yaml",
    "agents/nddev-builder.md",
    "skills/nddev-builder/SKILL.md",
    "steering/nddev-builder.md",
    "hooks/nddev-builder.json",
]
BUILDER_FILES = [
    "agents/nddev-builder.md",
    "skills/nddev-builder/SKILL.md",
    "steering/nddev-builder.md",
    "hooks/nddev-builder.json",
]
WORKFLOWS = [
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
]
EXPECTED_SETTINGS = {
    "chat.defaultAgent": "nddev-builder",
    "chat.disableInheritingDefaultResources": False,
    "chat.ui": "terminal",
    "telemetry.enabled": False,
}


def load_json(relative: str, errors: list[str]) -> dict[str, Any] | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required JSON file: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top-level value must be an object")
        return None
    return value


def check_text(relative: str, errors: list[str]) -> str:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required text file: {relative}")
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{relative}: unreadable text: {exc}")
        return ""
    if not text.strip() or not text.endswith("\n"):
        errors.append(f"{relative}: must be non-empty LF-terminated text")
    return text


def expected_permissions(setup_id: str) -> tuple[str, ...]:
    if setup_id == "safe":
        return ("rules:", "effect: ask", "capability: skill", "**/.env")
    if setup_id == "balanced":
        return ("rules:", "npm test*", "effect: ask", "capability: subagent")
    if setup_id == "full-auto":
        return ("rules:", "capability: all", "effect: allow")
    raise AssertionError(setup_id)


def check_setup(setup_id: str, errors: list[str]) -> None:
    root = ROOT / "setups" / setup_id
    metadata = load_json(f"setups/{setup_id}/setup.json", errors)
    settings = load_json(f"setups/{setup_id}/settings/cli.json", errors)
    hook = load_json(f"setups/{setup_id}/hooks/nddev-builder.json", errors)
    permissions = check_text(f"setups/{setup_id}/settings/permissions.yaml", errors)
    if metadata is not None:
        if metadata.get("id") != setup_id:
            errors.append(f"setups/{setup_id}/setup.json: id mismatch")
        if metadata.get("managed_files") != MANAGED_FILES:
            errors.append(f"setups/{setup_id}/setup.json: managed_files mismatch")
        if metadata.get("managed_settings") != EXPECTED_SETTINGS:
            errors.append(f"setups/{setup_id}/setup.json: managed_settings mismatch")
        if metadata.get("permission_profile") != setup_id:
            errors.append(f"setups/{setup_id}/setup.json: permission_profile mismatch")
        if metadata.get("builder_enabled") is not True:
            errors.append(f"setups/{setup_id}/setup.json: builder must be enabled")
    if settings != EXPECTED_SETTINGS:
        errors.append(f"setups/{setup_id}/settings/cli.json: settings mismatch")
    for marker in expected_permissions(setup_id):
        if marker not in permissions:
            errors.append(f"setups/{setup_id}/settings/permissions.yaml: missing {marker}")
    if hook is not None:
        if hook.get("version") != "v1" or not isinstance(hook.get("hooks"), list):
            errors.append(f"setups/{setup_id}/hooks/nddev-builder.json: invalid hook file")
    for relative in (
        "agents/nddev-builder.md",
        "skills/nddev-builder/SKILL.md",
        "steering/nddev-builder.md",
    ):
        check_text(f"setups/{setup_id}/{relative}", errors)
    if not root.is_dir():
        errors.append(f"setups/{setup_id}: setup directory missing")


def main() -> int:
    errors: list[str] = []
    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/kiro-cli-baseline.json", errors)

    if version is not None:
        if version.get("build_version") != version_text:
            errors.append("VERSION disagrees with build/version.json:build_version")
        if version.get("kiro_cli_current") != "2.14.2":
            errors.append("build/version.json: kiro_cli_current must be 2.14.2")
    if manifest is not None:
        if manifest.get("build_version") != version_text:
            errors.append("build/manifest.json: build_version mismatch")
        if manifest.get("setup_ids") != SETUP_IDS:
            errors.append("build/manifest.json: setup_ids mismatch")
        builder = manifest.get("builder")
        if (
            not isinstance(builder, dict)
            or builder.get("projection") != "native-agent-skill-steering-hook"
        ):
            errors.append("build/manifest.json: Kiro native builder projection required")
        elif builder.get("marketplace") is not None:
            errors.append("build/manifest.json: marketplace must be null")
    if contract is not None:
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton status is not allowed")
        if contract.get("manifest_ref") != "build/manifest.json":
            errors.append("config/nddev-contract.json: manifest_ref mismatch")
        if contract.get("managed_state", {}).get("target_model") != "isolated-kiro-home":
            errors.append("config/nddev-contract.json: isolated-kiro-home target required")
        if contract.get("managed_state", {}).get("managed_files") != MANAGED_FILES:
            errors.append("config/nddev-contract.json: managed_files mismatch")
        setup_system = contract.get("setup_system", {})
        if "update_command" not in setup_system:
            errors.append("config/nddev-contract.json: setup update_command required")
        builder = contract.get("builder")
        if (
            not isinstance(builder, dict)
            or builder.get("projection") != "native-agent-skill-steering-hook"
        ):
            errors.append("config/nddev-contract.json: Kiro native builder projection required")
        elif builder.get("marketplace") is not None:
            errors.append("config/nddev-contract.json: marketplace must be null")
        elif builder.get("managed_files") != BUILDER_FILES:
            errors.append("config/nddev-contract.json: builder managed_files mismatch")
        software = contract.get("software_distribution")
        if not isinstance(software, dict):
            errors.append("config/nddev-contract.json: software_distribution required")
        else:
            if software.get("manager_installs_software") is not True:
                errors.append("config/nddev-contract.json: manager must install software")
            if software.get("install_mode") != "harness-owned-official-artifact":
                errors.append("config/nddev-contract.json: software install mode mismatch")
            if software.get("install_only_absent") is not True:
                errors.append("config/nddev-contract.json: install_only_absent required")
            if software.get("update_repairs_safe_partial") is not True:
                errors.append("config/nddev-contract.json: update repair contract required")
            if software.get("update_installs_absent") is not False:
                errors.append("config/nddev-contract.json: absent update must be disabled")
            if software.get("absent_update_behavior") != "domain-error-install-first":
                errors.append("config/nddev-contract.json: absent update behavior mismatch")
            manifest_pin = software.get("official_manifest")
            if not isinstance(manifest_pin, dict):
                errors.append("config/nddev-contract.json: official manifest pin required")
            else:
                if manifest_pin.get("sha256") != (
                    "2df08fa37b6bbb66c3fc626b458f3b2a0689da7957238bd94b6c1667dc74f5fe"
                ):
                    errors.append("config/nddev-contract.json: manifest sha256 mismatch")
                if manifest_pin.get("size") != 9313:
                    errors.append("config/nddev-contract.json: manifest size mismatch")
            if software.get("supported_platforms") != [
                "macos-universal-dmg",
                "linux-x86_64-glibc-zip",
                "linux-aarch64-glibc-zip",
                "linux-x86_64-musl-zip",
                "linux-aarch64-musl-zip",
            ]:
                errors.append("config/nddev-contract.json: supported platforms mismatch")
            installer = software.get("official_vendor_installer")
            if not isinstance(installer, dict):
                errors.append("config/nddev-contract.json: official installer record required")
            else:
                if installer.get("sha256") != (
                    "91a21bfa05cd7b58601cb83e0f1f187a9d0084726e5b824d4a4cf60306250908"
                ):
                    errors.append("config/nddev-contract.json: installer sha256 mismatch")
                if installer.get("target_owned") is not False or installer.get(
                    "used_by_manager"
                ) is not False:
                    errors.append("config/nddev-contract.json: installer limitation mismatch")
    if baseline is not None:
        if version is not None and baseline.get("release", {}).get("version") != version.get(
            "kiro_cli_current"
        ):
            errors.append("references/kiro-cli-baseline.json: version mismatch")
        configuration = baseline.get("configuration", {})
        if configuration.get("marketplace") is not None:
            errors.append("references/kiro-cli-baseline.json: marketplace must be null")
        if configuration.get("settings_file") != "~/.kiro/settings/cli.json":
            errors.append("references/kiro-cli-baseline.json: settings path mismatch")
        if baseline.get("runtime", {}).get("executable") != "kiro-cli":
            errors.append("references/kiro-cli-baseline.json: executable must be kiro-cli")
        if baseline.get("release", {}).get("install_script_sha256") != (
            "91a21bfa05cd7b58601cb83e0f1f187a9d0084726e5b824d4a4cf60306250908"
        ):
            errors.append("references/kiro-cli-baseline.json: install script sha256 mismatch")
        if baseline.get("release", {}).get("install_manifest_sha256") != (
            "2df08fa37b6bbb66c3fc626b458f3b2a0689da7957238bd94b6c1667dc74f5fe"
        ):
            errors.append("references/kiro-cli-baseline.json: install manifest sha256 mismatch")
        if baseline.get("release", {}).get("install_manifest_size") != 9313:
            errors.append("references/kiro-cli-baseline.json: install manifest size mismatch")
        software = baseline.get("software_installation")
        if not isinstance(software, dict):
            errors.append("references/kiro-cli-baseline.json: software installation missing")
        elif software.get("official_vendor_installer_supported") is not False:
            errors.append("references/kiro-cli-baseline.json: installer limitation missing")
        elif software.get("update_installs_absent") is not False:
            errors.append("references/kiro-cli-baseline.json: absent update must be disabled")
        elif software.get("absent_update_behavior") != "domain-error-install-first":
            errors.append("references/kiro-cli-baseline.json: absent update behavior mismatch")
        packages = baseline.get("install_manifest", {}).get("packages")
        if not isinstance(packages, list) or not packages:
            errors.append("references/kiro-cli-baseline.json: install packages missing")
        elif not all(isinstance(item, dict) and item.get("sha256") for item in packages):
            errors.append("references/kiro-cli-baseline.json: package sha256 missing")

    for setup_id in SETUP_IDS:
        check_setup(setup_id, errors)
    for relative in (
        "README.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "cli-tools/nddev_kiro_cli.py",
    ):
        check_text(relative, errors)
    for workflow in WORKFLOWS:
        check_text(f".github/workflows/{workflow}", errors)

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
