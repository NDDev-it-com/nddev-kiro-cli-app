#!/usr/bin/env python3
"""Validate public nddev-kiro-cli-app contracts without private inputs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETUP_IDS = ["nddev-builder"]
PROFILE_IDS = ["safe", "full-auto"]
DEFAULT_PROFILE_ID = "full-auto"
LEGACY_SETUP_IDS = ["safe", "balanced", "full-auto"]
BUILD_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
REFERENCE_FILES = [
    "skills/nddev-builder/references/agents-subagents.md",
    "skills/nddev-builder/references/configuration-profiles.md",
    "skills/nddev-builder/references/creator-checker-release.md",
    "skills/nddev-builder/references/hooks.md",
    "skills/nddev-builder/references/installation-lifecycle.md",
    "skills/nddev-builder/references/mcp.md",
    "skills/nddev-builder/references/permissions-sandbox.md",
    "skills/nddev-builder/references/plugins-marketplace.md",
    "skills/nddev-builder/references/skills-instructions.md",
]
BUILDER_FILES = [
    "agents/nddev-builder.md",
    "skills/nddev-builder/SKILL.md",
    *REFERENCE_FILES,
    "steering/nddev-builder.md",
]
MANAGED_FILES = [
    "settings/cli.json",
    "settings/permissions.yaml",
    *BUILDER_FILES,
]
LEGACY_MANAGED_FILES = [
    "settings/cli.json",
    "settings/permissions.yaml",
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
    "app.disableAutoupdates": True,
    "chat.defaultAgent": "nddev-builder",
    "chat.ui": "tui",
    "telemetry.enabled": False,
}
EXPECTED_FULL_AUTO_PERMISSIONS = (
    "rules:\n"
    "  - capability: all\n"
    "    effect: allow\n"
)
EXPECTED_SAFE_PERMISSIONS = (
    "rules:\n"
    "  - capability: fs_read\n"
    "    effect: deny\n"
    "    match:\n"
    '      - "**/.env"\n'
    '      - "**/.env.*"\n'
    '      - "**/*.pem"\n'
    '      - "secrets/**"\n'
    "  - capability: shell\n"
    "    effect: ask\n"
    "  - capability: fs_write\n"
    "    effect: ask\n"
    "  - capability: web_fetch\n"
    "    effect: ask\n"
    "  - capability: web_search\n"
    "    effect: ask\n"
    "  - capability: mcp\n"
    "    effect: ask\n"
    "  - capability: subagent\n"
    "    effect: ask\n"
    "  - capability: skill\n"
    "    effect: allow\n"
    "  - capability: diagnostics\n"
    "    effect: allow\n"
    "  - capability: context\n"
    "    effect: allow\n"
)
EXPECTED_AGENT_FRONTMATTER = (
    "description: NDDev builder setup-module implementation agent.\n"
    'tools: ["*"]\n'
    "resources:\n"
    "  - skill://~/.kiro/skills/nddev-builder/SKILL.md\n"
    "  - file://~/.kiro/skills/nddev-builder/references/**/*.md\n"
    "  - file://~/.kiro/steering/nddev-builder.md\n"
    'welcomeMessage: "NDDev builder context loaded."\n'
)
MANAGED_LAUNCH_BLOCKED_COMMANDS = [
    "agent",
    "diagnostic",
    "integrations",
    "launch",
    "login",
    "logout",
    "mcp",
    "settings",
    "update",
    "whoami",
]
MANAGED_LAUNCH_BLOCKED_OPTIONS = [
    "--agent",
    "--classic",
    "--no-interactive",
    "--require-mcp-startup",
    "--trust-all-tools",
    "--trust-tools",
    "--v3",
]
SUPPORTED_PLATFORMS = [
    "macos-universal-dmg",
    "linux-x86_64-glibc-zip",
    "linux-aarch64-glibc-zip",
    "linux-x86_64-musl-zip",
    "linux-aarch64-musl-zip",
]
TRUSTED_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
MANIFEST_SHA256 = "2df08fa37b6bbb66c3fc626b458f3b2a0689da7957238bd94b6c1667dc74f5fe"
INSTALLER_SHA256 = "91a21bfa05cd7b58601cb83e0f1f187a9d0084726e5b824d4a4cf60306250908"
DISALLOWED_MANAGER_SOURCE_TOKENS = [
    "NDDEV_KIRO_CLI_ALLOW_TEST_SOURCES",
    "ALLOW_TEST",
    "_TEST_SOURCES",
    "test_sources_enabled",
    "package_from_manifest_for_tests",
    "--manifest-url",
    "--manifest-path",
    "--artifact-base-url",
    "--artifact-path",
    "manifest_path",
    "manifest_url",
    "artifact_path",
    "artifact_base_url",
    "private-test",
    "local software manifest",
    "local software artifact",
    "non-official software",
]


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
    if not text.strip() or not text.endswith("\n") or "\r" in text:
        errors.append(f"{relative}: must be non-empty LF-terminated text")
    return text


def check_absent(relative: str, errors: list[str]) -> None:
    if (ROOT / relative).exists():
        errors.append(f"{relative}: unsupported public surface must be absent")


def expected_permissions(profile_id: str) -> str:
    if profile_id == "safe":
        return EXPECTED_SAFE_PERMISSIONS
    if profile_id == "full-auto":
        return EXPECTED_FULL_AUTO_PERMISSIONS
    raise AssertionError(profile_id)


def frontmatter(text: str, relative: str, errors: list[str]) -> str:
    if not text.startswith("---\n"):
        errors.append(f"{relative}: missing YAML frontmatter")
        return ""
    _, separator, rest = text[4:].partition("---\n")
    if not separator:
        errors.append(f"{relative}: unclosed YAML frontmatter")
        return ""
    if not rest.strip():
        errors.append(f"{relative}: missing body")
    return _


def check_profile(profile_id: str, errors: list[str]) -> None:
    root = ROOT / "profiles" / profile_id
    metadata = load_json(f"profiles/{profile_id}/profile.json", errors)
    permissions = check_text(f"profiles/{profile_id}/permissions.yaml", errors)
    if metadata is not None:
        if metadata.get("schema_version") != 1:
            errors.append(f"profiles/{profile_id}/profile.json: schema_version mismatch")
        if metadata.get("id") != profile_id:
            errors.append(f"profiles/{profile_id}/profile.json: id mismatch")
        if metadata.get("permissions_file") != "permissions.yaml":
            errors.append(f"profiles/{profile_id}/profile.json: permissions_file mismatch")
        if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
            errors.append(f"profiles/{profile_id}/profile.json: description required")
    if permissions != expected_permissions(profile_id):
        errors.append(f"profiles/{profile_id}/permissions.yaml: exact native rules mismatch")
    if not root.is_dir():
        errors.append(f"profiles/{profile_id}: profile directory missing")


def check_setup(errors: list[str]) -> None:
    setup_id = "nddev-builder"
    root = ROOT / "setups" / setup_id
    metadata = load_json(f"setups/{setup_id}/setup.json", errors)
    settings = load_json(f"setups/{setup_id}/settings/cli.json", errors)
    agent = check_text(f"setups/{setup_id}/agents/nddev-builder.md", errors)
    entry_skill = check_text(f"setups/{setup_id}/skills/nddev-builder/SKILL.md", errors)
    for relative in BUILDER_FILES:
        check_text(f"setups/{setup_id}/{relative}", errors)
    check_absent(f"setups/{setup_id}/settings/permissions.yaml", errors)
    check_absent(f"setups/{setup_id}/hooks/nddev-builder.json", errors)
    for legacy_id in LEGACY_SETUP_IDS:
        check_absent(f"setups/{legacy_id}/setup.json", errors)

    if metadata is not None:
        if metadata.get("id") != setup_id:
            errors.append(f"setups/{setup_id}/setup.json: id mismatch")
        if metadata.get("managed_content_files") != BUILDER_FILES:
            errors.append(f"setups/{setup_id}/setup.json: managed_content_files mismatch")
        if metadata.get("managed_settings") != EXPECTED_SETTINGS:
            errors.append(f"setups/{setup_id}/setup.json: managed_settings mismatch")
        if metadata.get("default_permission_profile") != DEFAULT_PROFILE_ID:
            errors.append(f"setups/{setup_id}/setup.json: default profile mismatch")
        if metadata.get("supported_permission_profiles") != PROFILE_IDS:
            errors.append(f"setups/{setup_id}/setup.json: supported profiles mismatch")
        if metadata.get("builder_enabled") is not True:
            errors.append(f"setups/{setup_id}/setup.json: builder must be enabled")
    if settings != EXPECTED_SETTINGS:
        errors.append(f"setups/{setup_id}/settings/cli.json: settings mismatch")
    if frontmatter(agent, f"setups/{setup_id}/agents/nddev-builder.md", errors) != (
        EXPECTED_AGENT_FRONTMATTER
    ):
        errors.append(
            f"setups/{setup_id}/agents/nddev-builder.md: exact agent frontmatter mismatch"
        )
    for relative in REFERENCE_FILES:
        routed = relative.removeprefix("skills/nddev-builder/")
        if f"`{routed}`" not in entry_skill:
            errors.append(
                f"setups/{setup_id}/skills/nddev-builder/SKILL.md: "
                f"missing route to {routed}"
            )
    if not root.is_dir():
        errors.append(f"setups/{setup_id}: setup directory missing")


def check_runtime(runtime: dict[str, Any], label: str, errors: list[str]) -> None:
    if runtime.get("engine_argument") != "--v3":
        errors.append(f"{label}: launch must force --v3")
    if runtime.get("engine_status") != "early-access-required":
        errors.append(f"{label}: engine_status mismatch")
    if runtime.get("managed_launch_blocked_commands") != MANAGED_LAUNCH_BLOCKED_COMMANDS:
        errors.append(f"{label}: managed launch command guard mismatch")
    if runtime.get("managed_launch_blocked_options") != MANAGED_LAUNCH_BLOCKED_OPTIONS:
        errors.append(f"{label}: managed launch option guard mismatch")
    if runtime.get("trusted_system_path") not in (None, TRUSTED_SYSTEM_PATH):
        errors.append(f"{label}: trusted system PATH mismatch")


def check_builder(builder: Any, label: str, errors: list[str]) -> None:
    if not isinstance(builder, dict):
        errors.append(f"{label}: builder object required")
        return
    if builder.get("id") != "nddev-builder":
        errors.append(f"{label}: builder id mismatch")
    if builder.get("projection") != "native-agent-skill-steering":
        errors.append(f"{label}: Kiro native builder projection mismatch")
    if builder.get("marketplace") is not None:
        errors.append(f"{label}: marketplace must be null")
    if builder.get("managed_files") != BUILDER_FILES:
        errors.append(f"{label}: builder managed_files mismatch")
    if builder.get("agent_tools") not in (None, ["*"]):
        errors.append(f"{label}: agent tools must be ['*']")


def check_manifest(manifest: dict[str, Any], version_text: str, errors: list[str]) -> None:
    if manifest.get("build_version") != version_text:
        errors.append("build/manifest.json: build_version mismatch")
    if manifest.get("setup_ids") != SETUP_IDS:
        errors.append("build/manifest.json: setup_ids mismatch")
    if manifest.get("default_setup_id") != "nddev-builder":
        errors.append("build/manifest.json: default setup mismatch")
    if manifest.get("permission_profile_ids") != PROFILE_IDS:
        errors.append("build/manifest.json: permission profile ids mismatch")
    if manifest.get("default_permission_profile_id") != DEFAULT_PROFILE_ID:
        errors.append("build/manifest.json: default permission profile mismatch")
    if manifest.get("legacy_setup_ids") != LEGACY_SETUP_IDS:
        errors.append("build/manifest.json: legacy setup ids mismatch")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("build/manifest.json: runtime required")
    else:
        check_runtime(runtime, "build/manifest.json", errors)
    check_builder(manifest.get("builder"), "build/manifest.json", errors)


def check_software(software: Any, label: str, errors: list[str]) -> None:
    if not isinstance(software, dict):
        errors.append(f"{label}: software_distribution required")
        return
    if software.get("manager_installs_software") is not True:
        errors.append(f"{label}: manager must install software")
    if software.get("install_mode") != "target-owned-official-artifact":
        errors.append(f"{label}: software install mode mismatch")
    if software.get("install_only_absent") is not True:
        errors.append(f"{label}: install_only_absent required")
    if software.get("update_repairs_safe_partial") is not True:
        errors.append(f"{label}: update repair contract required")
    if software.get("update_installs_absent") is not False:
        errors.append(f"{label}: absent update must be disabled")
    if software.get("absent_update_behavior") != "domain-error-install-first":
        errors.append(f"{label}: absent update behavior mismatch")
    if software.get("production_source_pins_required") is not True:
        errors.append(f"{label}: production source pins must be required")
    if software.get("source_override_arguments") != []:
        errors.append(f"{label}: source override arguments must be absent")
    if software.get("test_source_environment_switches") != []:
        errors.append(f"{label}: test source env switches must be absent")
    if software.get("manager_build_version_mismatch") != "needs-update":
        errors.append(f"{label}: manager build mismatch behavior mismatch")
    if software.get("remove_tolerates_missing_or_malformed_stamp_after_trust") is not True:
        errors.append(f"{label}: malformed stamp remove behavior mismatch")
    if software.get("status_launch_allowed_requires_clean_software") is not True:
        errors.append(f"{label}: launch_allowed software precondition missing")
    if software.get("supported_platforms") != SUPPORTED_PLATFORMS:
        errors.append(f"{label}: supported platforms mismatch")
    if software.get("unsupported_platforms") != ["windows"]:
        errors.append(f"{label}: unsupported platforms mismatch")
    if software.get("trusted_bash") not in (None, "/bin/bash"):
        errors.append(f"{label}: trusted bash mismatch")
    if software.get("trusted_system_path") not in (None, TRUSTED_SYSTEM_PATH):
        errors.append(f"{label}: trusted system PATH mismatch")
    if software.get("transaction_parent_policy") not in (
        None,
        "owner-private-or-sticky-same-filesystem",
    ):
        errors.append(f"{label}: transaction parent policy mismatch")
    manifest_pin = software.get("official_manifest")
    if not isinstance(manifest_pin, dict):
        errors.append(f"{label}: official manifest pin required")
    else:
        if manifest_pin.get("sha256") != MANIFEST_SHA256:
            errors.append(f"{label}: manifest sha256 mismatch")
        if manifest_pin.get("size") != 9313:
            errors.append(f"{label}: manifest size mismatch")
    installer = software.get("official_vendor_installer")
    if not isinstance(installer, dict):
        errors.append(f"{label}: official installer record required")
    else:
        if installer.get("sha256") != INSTALLER_SHA256:
            errors.append(f"{label}: installer sha256 mismatch")
        if installer.get("target_owned") is not False or installer.get("used_by_manager") is not False:
            errors.append(f"{label}: installer limitation mismatch")


def check_contract(contract: dict[str, Any], errors: list[str]) -> None:
    if contract.get("contract_version") != 2:
        errors.append("config/nddev-contract.json: contract_version mismatch")
    if "skeleton" in contract:
        errors.append("config/nddev-contract.json: skeleton status is not allowed")
    if contract.get("manifest_ref") != "build/manifest.json":
        errors.append("config/nddev-contract.json: manifest_ref mismatch")
    managed_state = contract.get("managed_state", {})
    if managed_state.get("target_model") != "isolated-kiro-home":
        errors.append("config/nddev-contract.json: isolated-kiro-home target required")
    if managed_state.get("stamp_schema") != 2:
        errors.append("config/nddev-contract.json: stamp_schema mismatch")
    if managed_state.get("legacy_stamp_schema") != 1:
        errors.append("config/nddev-contract.json: legacy stamp schema mismatch")
    if managed_state.get("existing_target_mode") != "0700":
        errors.append("config/nddev-contract.json: existing target mode mismatch")
    if managed_state.get("runtime_state_root") != ".nddev-runtime":
        errors.append("config/nddev-contract.json: runtime state root mismatch")
    if managed_state.get("lock_root") != "target/.nddev-runtime/locks/setup-manager.lock":
        errors.append("config/nddev-contract.json: lock root mismatch")
    if managed_state.get("backup_root") != "target/.nddev-runtime/backups/setup":
        errors.append("config/nddev-contract.json: backup root mismatch")
    if managed_state.get("managed_files") != MANAGED_FILES:
        errors.append("config/nddev-contract.json: managed_files mismatch")
    if managed_state.get("managed_content_files") != BUILDER_FILES:
        errors.append("config/nddev-contract.json: managed_content_files mismatch")
    if managed_state.get("legacy_managed_files") != LEGACY_MANAGED_FILES:
        errors.append("config/nddev-contract.json: legacy_managed_files mismatch")
    setup_system = contract.get("setup_system", {})
    if setup_system.get("content_setup_ids") != SETUP_IDS:
        errors.append("config/nddev-contract.json: content setup ids mismatch")
    if setup_system.get("default_setup_id") != "nddev-builder":
        errors.append("config/nddev-contract.json: default setup mismatch")
    if setup_system.get("permission_profile_ids") != PROFILE_IDS:
        errors.append("config/nddev-contract.json: permission profile ids mismatch")
    if setup_system.get("default_permission_profile_id") != DEFAULT_PROFILE_ID:
        errors.append("config/nddev-contract.json: default permission profile mismatch")
    if setup_system.get("legacy_setup_ids") != LEGACY_SETUP_IDS:
        errors.append("config/nddev-contract.json: legacy setup ids mismatch")
    if "migrate_command" not in setup_system:
        errors.append("config/nddev-contract.json: migrate_command required")
    profiles = contract.get("permission_profiles", {})
    if profiles.get("default") != DEFAULT_PROFILE_ID:
        errors.append("config/nddev-contract.json: profile default mismatch")
    if profiles.get("profile_ids") != PROFILE_IDS:
        errors.append("config/nddev-contract.json: profile ids mismatch")
    if profiles.get("vendor_named_profiles") != []:
        errors.append("config/nddev-contract.json: vendor profile names must be empty")
    runtime_launch = contract.get("runtime_launch")
    if not isinstance(runtime_launch, dict):
        errors.append("config/nddev-contract.json: runtime_launch required")
    else:
        check_runtime(runtime_launch, "config/nddev-contract.json", errors)
        if runtime_launch.get("credential_env_inherited") is not False:
            errors.append("config/nddev-contract.json: credential env boundary mismatch")
        if runtime_launch.get("ambient_path_inherited") is not False:
            errors.append("config/nddev-contract.json: ambient PATH boundary mismatch")
        if runtime_launch.get("trusted_system_path") != TRUSTED_SYSTEM_PATH:
            errors.append("config/nddev-contract.json: trusted system PATH mismatch")
        target_env = runtime_launch.get("target_environment_scope", {})
        if target_env.get("PATH") != TRUSTED_SYSTEM_PATH:
            errors.append("config/nddev-contract.json: launch PATH mismatch")
        if runtime_launch.get("denies_legacy_managed_target") is not True:
            errors.append("config/nddev-contract.json: legacy launch denial required")
    check_builder(contract.get("builder"), "config/nddev-contract.json", errors)
    builder = contract.get("builder")
    if isinstance(builder, dict):
        agent_schema = builder.get("agent_schema", {})
        if agent_schema.get("tools") != ["*"]:
            errors.append("config/nddev-contract.json: agent schema tools must be ['*']")
        if agent_schema.get("resources") != [
            "skill://~/.kiro/skills/nddev-builder/SKILL.md",
            "file://~/.kiro/skills/nddev-builder/references/**/*.md",
            "file://~/.kiro/steering/nddev-builder.md",
        ]:
            errors.append("config/nddev-contract.json: agent resources mismatch")
        if agent_schema.get("inline_permissions") is not False:
            errors.append("config/nddev-contract.json: inline permissions must be false")
        native_surfaces = builder.get("native_surfaces", {})
        if not isinstance(native_surfaces, dict):
            errors.append("config/nddev-contract.json: native surfaces required")
        elif "workspace .kiro/hooks/<name>.json" not in native_surfaces.get("hooks", ""):
            errors.append("config/nddev-contract.json: workspace hook discovery mismatch")
    check_software(contract.get("software_distribution"), "config/nddev-contract.json", errors)
    safety = contract.get("safety", {})
    for key in (
        "existing_target_owner_private_mode_required",
        "nddev_runtime_state_owner_private",
        "lock_state_under_target",
        "backup_state_under_target",
        "attacker_sibling_lock_backup_ignored",
    ):
        if safety.get(key) is not True:
            errors.append(f"config/nddev-contract.json: safety.{key} required")


def check_baseline(
    baseline: dict[str, Any],
    version: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if baseline.get("verified_on") != "2026-07-27":
        errors.append("references/kiro-cli-baseline.json: verified_on mismatch")
    if version is not None and baseline.get("release", {}).get("version") != version.get(
        "kiro_cli_current"
    ):
        errors.append("references/kiro-cli-baseline.json: version mismatch")
    runtime = baseline.get("runtime", {})
    if runtime.get("engine_argument") != "--v3":
        errors.append("references/kiro-cli-baseline.json: engine argument mismatch")
    if runtime.get("engine_status") != "early-access-required":
        errors.append("references/kiro-cli-baseline.json: engine status mismatch")
    if runtime.get("trusted_system_path") != TRUSTED_SYSTEM_PATH:
        errors.append("references/kiro-cli-baseline.json: trusted system PATH mismatch")
    configuration = baseline.get("configuration", {})
    if configuration.get("marketplace") is not None:
        errors.append("references/kiro-cli-baseline.json: marketplace must be null")
    if configuration.get("settings_file") != "~/.kiro/settings/cli.json":
        errors.append("references/kiro-cli-baseline.json: settings path mismatch")
    if configuration.get("global_hooks") is not None:
        errors.append("references/kiro-cli-baseline.json: global hooks must be null")
    if configuration.get("workspace_hooks") != ".kiro/hooks/<name>.json":
        errors.append("references/kiro-cli-baseline.json: workspace hooks mismatch")
    if configuration.get("mcp_files") != [
        "~/.kiro/settings/mcp.json",
        ".kiro/settings/mcp.json",
    ]:
        errors.append("references/kiro-cli-baseline.json: MCP paths mismatch")
    if configuration.get("agent_tools") != ["*"]:
        errors.append("references/kiro-cli-baseline.json: agent tools mismatch")
    if baseline.get("runtime", {}).get("executable") != "kiro-cli":
        errors.append("references/kiro-cli-baseline.json: executable must be kiro-cli")
    authentication = baseline.get("authentication", {})
    if authentication.get("manager_launch_inherits_path") is not False:
        errors.append("references/kiro-cli-baseline.json: launch PATH boundary mismatch")
    release = baseline.get("release", {})
    if release.get("install_script_sha256") != INSTALLER_SHA256:
        errors.append("references/kiro-cli-baseline.json: install script sha256 mismatch")
    if release.get("install_manifest_sha256") != MANIFEST_SHA256:
        errors.append("references/kiro-cli-baseline.json: install manifest sha256 mismatch")
    if release.get("install_manifest_size") != 9313:
        errors.append("references/kiro-cli-baseline.json: install manifest size mismatch")
    software = baseline.get("software_installation")
    if not isinstance(software, dict):
        errors.append("references/kiro-cli-baseline.json: software installation missing")
    else:
        if software.get("manager_install_mode") != "target-owned-official-artifact":
            errors.append("references/kiro-cli-baseline.json: install mode mismatch")
        if software.get("lock_root") != "target/.nddev-runtime/locks/setup-manager.lock":
            errors.append("references/kiro-cli-baseline.json: lock root mismatch")
        if software.get("backup_root") != "target/.nddev-runtime/backups/setup":
            errors.append("references/kiro-cli-baseline.json: backup root mismatch")
        if software.get("trusted_bash") != "/bin/bash":
            errors.append("references/kiro-cli-baseline.json: trusted bash mismatch")
        if software.get("trusted_system_path") != TRUSTED_SYSTEM_PATH:
            errors.append("references/kiro-cli-baseline.json: trusted system PATH mismatch")
        if software.get("official_vendor_installer_supported") is not False:
            errors.append("references/kiro-cli-baseline.json: installer limitation missing")
        if software.get("supported_platforms") != SUPPORTED_PLATFORMS:
            errors.append("references/kiro-cli-baseline.json: supported platforms mismatch")
        if software.get("unsupported_platforms") != ["windows"]:
            errors.append("references/kiro-cli-baseline.json: unsupported platforms mismatch")
        if software.get("update_installs_absent") is not False:
            errors.append("references/kiro-cli-baseline.json: absent update must be disabled")
        if software.get("absent_update_behavior") != "domain-error-install-first":
            errors.append("references/kiro-cli-baseline.json: absent update behavior mismatch")
        if software.get("production_source_pins_required") is not True:
            errors.append("references/kiro-cli-baseline.json: production source pins missing")
        if software.get("source_override_arguments") != []:
            errors.append("references/kiro-cli-baseline.json: source overrides must be absent")
        if software.get("test_source_environment_switches") != []:
            errors.append("references/kiro-cli-baseline.json: test source env switches must be absent")
        if software.get("manager_build_version_mismatch") != "needs-update":
            errors.append("references/kiro-cli-baseline.json: manager build mismatch behavior mismatch")
        if software.get("remove_tolerates_missing_or_malformed_stamp_after_trust") is not True:
            errors.append("references/kiro-cli-baseline.json: malformed stamp remove behavior mismatch")
        if software.get("status_launch_allowed_requires_clean_software") is not True:
            errors.append("references/kiro-cli-baseline.json: launch_allowed software precondition missing")
    packages = baseline.get("install_manifest", {}).get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append("references/kiro-cli-baseline.json: install packages missing")
    elif not all(isinstance(item, dict) and item.get("sha256") for item in packages):
        errors.append("references/kiro-cli-baseline.json: package sha256 missing")


def check_manager_source(text: str, errors: list[str]) -> None:
    for token in DISALLOWED_MANAGER_SOURCE_TOKENS:
        if token in text:
            errors.append(f"cli-tools/nddev_kiro_cli.py: disallowed test/source switch {token!r}")


def main() -> int:
    errors: list[str] = []
    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    changelog_text = check_text("CHANGELOG.md", errors)
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/kiro-cli-baseline.json", errors)

    if not BUILD_VERSION_PATTERN.fullmatch(version_text):
        errors.append("VERSION must be a MAJOR.MINOR.PATCH build version")
    if f"## {version_text}\n" not in changelog_text:
        errors.append("CHANGELOG.md: missing current VERSION heading")
    if version is not None:
        if version.get("build_version") != version_text:
            errors.append("VERSION disagrees with build/version.json:build_version")
        if version.get("kiro_cli_current") != "2.14.2":
            errors.append("build/version.json: kiro_cli_current must be 2.14.2")
    if manifest is not None:
        check_manifest(manifest, version_text, errors)
    if contract is not None:
        check_contract(contract, errors)
    if baseline is not None:
        check_baseline(baseline, version, errors)

    check_setup(errors)
    for profile_id in PROFILE_IDS:
        check_profile(profile_id, errors)
    manager_source = ""
    for relative in (
        "README.md",
        "AGENTS.md",
        "SECURITY.md",
        "cli-tools/nddev_kiro_cli.py",
    ):
        text = check_text(relative, errors)
        if relative == "cli-tools/nddev_kiro_cli.py":
            manager_source = text
    check_manager_source(manager_source, errors)
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
