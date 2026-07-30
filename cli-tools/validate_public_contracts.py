#!/usr/bin/env python3
"""Validate public nddev-kiro-cli-app contracts without private inputs."""

from __future__ import annotations

import ast
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETUP_IDS = ["nddev-builder"]
PROFILE_IDS = ["safe", "full-auto"]
DEFAULT_PROFILE_ID = "full-auto"
LEGACY_SETUP_IDS = ["safe", "balanced", "full-auto"]
BUILD_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
PYTHON_REQUIRES = ">=3.9"
PYTHON_SYNTAX_FEATURE_VERSION = (3, 9)
PORTABLE_PYTHON_SOURCES = (
    "cli-tools/nddev_kiro_cli.py",
    "cli-tools/validate_public_contracts.py",
)
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
FOCUSED_SKILL_ROUTES = {
    "kiro-module-creator": [
        "creator-checker-release.md",
        "configuration-profiles.md",
        "installation-lifecycle.md",
    ],
    "kiro-module-checker": [
        "creator-checker-release.md",
        "installation-lifecycle.md",
        "plugins-marketplace.md",
    ],
    "kiro-release-checker": [
        "creator-checker-release.md",
        "installation-lifecycle.md",
    ],
    "kiro-config-profile-creator": [
        "configuration-profiles.md",
        "creator-checker-release.md",
    ],
    "kiro-config-profile-checker": [
        "configuration-profiles.md",
        "permissions-sandbox.md",
    ],
    "kiro-permissions-creator": [
        "permissions-sandbox.md",
        "configuration-profiles.md",
    ],
    "kiro-permissions-checker": [
        "permissions-sandbox.md",
        "installation-lifecycle.md",
    ],
    "kiro-agent-creator": [
        "agents-subagents.md",
        "skills-instructions.md",
    ],
    "kiro-agent-checker": [
        "agents-subagents.md",
        "permissions-sandbox.md",
    ],
    "kiro-skill-creator": [
        "skills-instructions.md",
        "creator-checker-release.md",
    ],
    "kiro-skill-checker": [
        "skills-instructions.md",
        "creator-checker-release.md",
    ],
    "kiro-hook-checker": [
        "hooks.md",
        "creator-checker-release.md",
    ],
    "kiro-mcp-checker": [
        "mcp.md",
        "permissions-sandbox.md",
        "installation-lifecycle.md",
    ],
    "kiro-plugin-marketplace-checker": [
        "plugins-marketplace.md",
        "creator-checker-release.md",
    ],
    "kiro-lifecycle-checker": [
        "installation-lifecycle.md",
        "permissions-sandbox.md",
        "creator-checker-release.md",
    ],
}
FOCUSED_SKILL_FILES = [f"skills/{name}/SKILL.md" for name in FOCUSED_SKILL_ROUTES]
BUILDER_FILES = [
    "agents/nddev-builder.md",
    "skills/nddev-builder/SKILL.md",
    *FOCUSED_SKILL_FILES,
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
EXPECTED_FULL_AUTO_PERMISSIONS = "rules:\n  - capability: all\n    effect: allow\n"
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
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
]
VENDOR_OBSERVED_PLATFORMS = [
    "universal-apple-darwin",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
    "x86_64-pc-windows-msvc",
]
UNSUPPORTED_PLATFORMS = [
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
]
OFFICIAL_UBUNTU_GLIBC_FLOOR = {
    "ubuntu-glibc-arm64": "2.39",
    "ubuntu-glibc-x64": "2.34",
}
PLATFORM_DETECTION = "platform.system + platform.machine + platform.freedesktop_os_release or /etc/os-release + platform.libc_ver"
TRUSTED_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
LOCK_ROOT_REF = "target/.nddev-runtime/locks/setup-manager.lock"
LOCK_MECHANISM = "fcntl-flock-persistent-file"
EXTERNAL_LOCK_MECHANISM = "fixed-system-temp-fcntl-flock-persistent-file"
EXTERNAL_LOCK_ROOT_REF = "fixed-system-temp/nddev-kiro-cli-app-uid"
EXTERNAL_PRODUCT_LOCK_FILENAME_REF = "global.lock"
EXTERNAL_LOCK_FILENAME_REF = "sha256(product namespace + canonical absolute target).lock"
EXTERNAL_LOCK_PUBLICATION_REF = "atomic-hardlink-no-replace"
CLEANUP_PENDING_ROOT_REF = "target/.nddev-runtime/cleanup-pending"
CLEANUP_INTENT_NAME_REF = "NDDEV-KIRO-CLI-CLEANUP-INTENT.json"
CLEANUP_JOURNAL_NAME_REF = "NDDEV-KIRO-CLI-CLEANUP.json"
CLEANUP_INTENT_PUBLICATION_REF = "atomic-hardlink-no-replace"
CLEANUP_JOURNAL_PUBLICATION_REF = "atomic-hardlink-no-replace"
LOCK_FILE_MODE = "0600"
LOCK_DIRECTORY_IDLE_MODE = "0700"
LOCK_DIRECTORY_HELD_MODE = "0500"
SOFTWARE_IMMUTABLE_FILE_MODE = "0400"
SOFTWARE_IMMUTABLE_EXECUTABLE_MODE = "0500"
SOFTWARE_IMMUTABLE_DIR_MODE = "0500"
TARGET_ENVIRONMENT_SCOPE = {
    "KIRO_HOME": "target",
    "HOME": "target/.nddev-runtime/home",
    "TMPDIR": "target/.nddev-runtime/tmp",
    "XDG_CONFIG_HOME": "target/.nddev-runtime/xdg/config",
    "XDG_DATA_HOME": "target/.nddev-runtime/xdg/data",
    "XDG_STATE_HOME": "target/.nddev-runtime/xdg/state",
    "XDG_CACHE_HOME": "target/.nddev-runtime/xdg/cache",
    "KIRO_CHAT_LOG_FILE": "target/.nddev-runtime/logs/kiro-chat.log",
    "PATH": TRUSTED_SYSTEM_PATH,
}
MANIFEST_SHA256 = "94d5c7c5eeaf2538f03a2296c51d908273411a853f5003126b57d1139ab000c7"
MANIFEST_SIZE = 9313
INSTALLER_SHA256 = "91a21bfa05cd7b58601cb83e0f1f187a9d0084726e5b824d4a4cf60306250908"
EXPECTED_INSTALL_PACKAGES = [
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarXz",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.tar.xz",
        "sha256": "a29da53c08174642aed1182b275443d9bc599866c15064cab4fcf7c8275da08c",
        "size": 492741300,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarGz",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.tar.gz",
        "sha256": "ee7ff91894419b0ad9eb1e03535e32352ee938483912cc78f315648d7e4af648",
        "size": 554395785,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "deb",
        "architecture": "x86_64",
        "variant": "full",
        "download": "2.15.1/kiro-cli.deb",
        "sha256": "0e78aa84789282b58899696bb21f98194ac66182a796dd40190ac33cfeff00b9",
        "size": 585058432,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarZst",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.tar.zst",
        "sha256": "a1f89b0b66caae8fe685310c9b0dd4fb76071fa280d69b0c4c23acff6a558143",
        "size": 502845643,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "appImage",
        "architecture": "x86_64",
        "variant": "full",
        "download": "2.15.1/kiro-cli.appimage",
        "sha256": "952ed96b05cda54ccfa4ac8341b8142520720ba00c4150648173a5fdcedb165a",
        "size": 730768576,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarGz",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.tar.gz",
        "sha256": "f09d2bb0d64892ba51eb8e438b77423fa6f7e94f2f86ca1a7e66b356ae4d116c",
        "size": 509411664,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "zip",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.zip",
        "sha256": "f17d352eea8f67ed92f6585193ad6a49ef045d6400822ed9f0888021d14754ac",
        "size": 554394320,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarXz",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.tar.xz",
        "sha256": "1c28931392868e485e1d8afd0bfee9a1330a85369073dd4c59982ad3312eb3bb",
        "size": 441558164,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "tarZst",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.tar.zst",
        "sha256": "ae477a97a98dc484e4849a9599c91f05a534c7747016e3d9fac4073ee0ff9ddb",
        "size": 457317125,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "universal-apple-darwin",
        "os": "macos",
        "fileType": "dmg",
        "architecture": "universal",
        "variant": "full",
        "download": "2.15.1/Kiro CLI.dmg",
        "sha256": "e01f2a54389a75b47636671b58fe2cd4b204749e7a3391778ab9eb76ba59a13b",
        "size": 682140633,
        "cliPath": "Contents/MacOS/kiro-cli",
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "zip",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.zip",
        "sha256": "83346f95bc8a986d4ba9270720082c36535d652350afd3799bedb9b0f15617cb",
        "size": 509410555,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarGz",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux-musl.tar.gz",
        "sha256": "57f43591487f2952cc0c96d025ad23d2d1daf4c229f7db2e8fdfb4b88e0a9156",
        "size": 511391862,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarXz",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux-musl.tar.xz",
        "sha256": "ac05eb26af3ed47958105e1960e21fe3a7b95fc531d29f9f504593967ec6a6bc",
        "size": 448460316,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "fileType": "zip",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux-musl.zip",
        "sha256": "472462588f7205d116f505f1bf1ac0ec8d58b6e5562e8047abbc7623987af245",
        "size": 511375428,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarZst",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux-musl.tar.zst",
        "sha256": "10036b30567f700ac26922912cae55e24af85f08503213d13f20db60d2a1ca02",
        "size": 458945159,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarGz",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux-musl.tar.gz",
        "sha256": "967683562a712b1881e6bc070f77e1a8c97f621862bb8b26ed81676879d1c8a1",
        "size": 508287841,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarXz",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux-musl.tar.xz",
        "sha256": "c8a44871a7fc7cf68cbb60a0f244748a60be332739d99829849a841a39427481",
        "size": 440625336,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "fileType": "tarZst",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux-musl.tar.zst",
        "sha256": "946ee888f3132cef3cd41a02d65ac5abb702c2908585e2664bb505632ad42d6a",
        "size": 456147380,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "fileType": "zip",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux-musl.zip",
        "sha256": "a71bd0540739bb5211188dbe11b432d5b2589f7acc14d550a4731f98a717b61c",
        "size": 508272955,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "rpm",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.rpm",
        "sha256": "ddcb8d55080d4aa30b28545df56369e9c1817f93a5cd1fbce036752f9aee5d01",
        "size": 553254751,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-gnu",
        "os": "linux",
        "fileType": "rpm",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.rpm",
        "sha256": "b60084550651d5e6b1ee3e2df466c34ef27daf6ca8e4b2a4fc6d3fb267385aff",
        "size": 508443736,
        "channel": "stable",
    },
    {
        "kind": "msi",
        "targetTriple": "x86_64-pc-windows-msvc",
        "os": "windows",
        "fileType": "msi",
        "architecture": "x86_64",
        "variant": "full",
        "download": "2.15.1/kiro-cli-x86_64-pc-windows-msvc.msi",
        "sha256": "aba54c18aa500d1daac90931c91c0d078d87be0adf197337b78a433d319c3d2b",
        "size": 250236928,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "fileType": "rpm",
        "architecture": "aarch64",
        "variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux-musl.rpm",
        "sha256": "d671bad4cc6279697082266a17e09a4bf7f2dd8408e569941c68d25e367aab5d",
        "size": 507308528,
        "channel": "stable",
    },
    {
        "kind": "deb",
        "targetTriple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "fileType": "rpm",
        "architecture": "x86_64",
        "variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux-musl.rpm",
        "sha256": "26dafe2ac0bf499e0b79205690d72c49745e2d8422a628cfcb56a966061f259c",
        "size": 510209086,
        "channel": "stable",
    },
]
PRODUCT_HOST_PACKAGE_MAP = {
    "macos-arm64": {
        "vendor_target_triple": "universal-apple-darwin",
        "vendor_os": "macos",
        "vendor_architecture": "universal",
        "vendor_file_type": "dmg",
        "vendor_variant": "full",
        "download": "2.15.1/Kiro CLI.dmg",
    },
    "macos-x64": {
        "vendor_target_triple": "universal-apple-darwin",
        "vendor_os": "macos",
        "vendor_architecture": "universal",
        "vendor_file_type": "dmg",
        "vendor_variant": "full",
        "download": "2.15.1/Kiro CLI.dmg",
    },
    "ubuntu-glibc-arm64": {
        "vendor_target_triple": "aarch64-unknown-linux-gnu",
        "vendor_os": "linux",
        "vendor_architecture": "aarch64",
        "vendor_file_type": "zip",
        "vendor_variant": "headless",
        "download": "2.15.1/kirocli-aarch64-linux.zip",
    },
    "ubuntu-glibc-x64": {
        "vendor_target_triple": "x86_64-unknown-linux-gnu",
        "vendor_os": "linux",
        "vendor_architecture": "x86_64",
        "vendor_file_type": "zip",
        "vendor_variant": "headless",
        "download": "2.15.1/kirocli-x86_64-linux.zip",
    },
}
CLAUDE_BRIDGE_BYTES = b"@../AGENTS.md\n"
RELEASE_WORKFLOW_USES = (
    "NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml"
    "@2ccb80e96f5771b6a6b4eae63a4f47e232906dc7"
)
RELEASE_WORKFLOW_VERSION = "0.12.0"
RELEASE_PACKAGE_NAME = "nddev-kiro-cli-app"
RELEASE_VERSION_INPUT = "${{ github.ref_name }}"
RELEASE_JOB_PERMISSIONS = {
    "contents": "write",
    "id-token": "write",
    "attestations": "write",
    "artifact-metadata": "write",
}
FORBIDDEN_RELEASE_PATH_PARTS = {
    ".agents",
    ".serena",
    "__pycache__",
    "benchmarks",
    "fixtures",
    "private",
    "validation",
}
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
    "NDDEV_KIRO_BOOTSTRAP_ROOT",
    "NDDEV_KIRO_CLI_BOOTSTRAP_ROOT",
    "KIRO_BOOTSTRAP_ROOT",
    "BOOTSTRAP_ROOT_OVERRIDE",
    "bootstrap_root_override",
    'os.environ.get("TMPDIR"',
    "os.environ.get('TMPDIR'",
    "tempfile.gettempdir(",
]
BOOTSTRAP_SNAPSHOT_MAX_FILES = 200
BOOTSTRAP_SNAPSHOT_MAX_BYTES = 1024 * 1024


def load_json(relative: str, errors: list[str]) -> dict[str, Any] | None:
    path = ROOT / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing required JSON file: {relative}")
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        errors.append(f"{relative}: must be a regular file")
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
    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing required text file: {relative}")
        return ""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        errors.append(f"{relative}: must be a regular file")
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


def check_focused_skill(
    skill_name: str,
    references: list[str],
    text: str,
    errors: list[str],
) -> None:
    relative = f"setups/nddev-builder/skills/{skill_name}/SKILL.md"
    metadata = frontmatter(text, relative, errors)
    if f"name: {skill_name}\n" not in metadata:
        errors.append(f"{relative}: frontmatter name mismatch")
    if "description: " not in metadata:
        errors.append(f"{relative}: description required")
    if "validation/" in text or "private/" in text or ".agents/" in text:
        errors.append(f"{relative}: public skill must not route to private roots")
    for reference in references:
        owner = f"../nddev-builder/references/{reference}"
        if f"`{owner}`" not in text:
            errors.append(f"{relative}: missing route to {owner}")
        if f"skills/nddev-builder/references/{reference}" not in REFERENCE_FILES:
            errors.append(f"{relative}: unknown reference owner {reference}")
    if "python3 cli-tools/validate_public_contracts.py" not in text:
        errors.append(f"{relative}: missing public validation workflow")


def check_skill_file_closure(setup_id: str, errors: list[str]) -> None:
    root = ROOT / "setups" / setup_id / "skills"
    expected = sorted(
        [
            "skills/nddev-builder/SKILL.md",
            *FOCUSED_SKILL_FILES,
            *REFERENCE_FILES,
        ]
    )
    actual: list[str] = []
    for path in root.rglob("*"):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        relative = f"skills/{path.relative_to(root).as_posix()}"
        actual.append(relative)
    if sorted(actual) != expected:
        errors.append(
            f"setups/{setup_id}/skills: skill file closure mismatch "
            f"(actual={sorted(actual)}, expected={expected})"
        )


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


def check_monotonic_external_lock_fields(
    surface: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    if surface.get("external_product_lock_filename") != EXTERNAL_PRODUCT_LOCK_FILENAME_REF:
        errors.append(f"{label}: external product lock filename mismatch")
    if surface.get("external_lock_publication") != EXTERNAL_LOCK_PUBLICATION_REF:
        errors.append(f"{label}: external lock publication primitive mismatch")
    if surface.get("external_lock_final_path_publication_commit_point") is not True:
        errors.append(f"{label}: external lock commit point mismatch")
    if surface.get("external_lock_parent_fsync_after_final_path_publication") is not True:
        errors.append(f"{label}: external lock parent fsync phase mismatch")
    if surface.get("external_lock_hardlink_alias_recovery") is not True:
        errors.append(f"{label}: external lock hardlink alias recovery missing")
    if surface.get("read_only_external_lock_no_create") is not True:
        errors.append(f"{label}: read-only external lock no-create contract missing")
    if surface.get("target_lock_published_by_mutation_only") is not True:
        errors.append(f"{label}: target lock publication boundary mismatch")


def check_cleanup_pending_fields(
    surface: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    expected = {
        "cleanup_pending_root": CLEANUP_PENDING_ROOT_REF,
        "cleanup_intent_name": CLEANUP_INTENT_NAME_REF,
        "cleanup_intent_schema": 1,
        "cleanup_intent_publication": CLEANUP_INTENT_PUBLICATION_REF,
        "cleanup_intent_precedes_source_moves": True,
        "cleanup_intent_alias_recovery_mutation_only": True,
        "cleanup_journal_name": CLEANUP_JOURNAL_NAME_REF,
        "cleanup_journal_schema": 1,
        "cleanup_journal_publication": CLEANUP_JOURNAL_PUBLICATION_REF,
        "cleanup_journal_final_path_publication_commit_point": True,
        "cleanup_journal_immutable": True,
        "cleanup_journal_alias_recovery_mutation_only": True,
        "cleanup_pending_bound": 1,
        "cleanup_tombstone_max_roots": 4,
        "cleanup_pending_status_plan_exposed": True,
        "cleanup_pending_top_level_result": True,
        "cleanup_pending_malformed_fail_closed": True,
        "read_only_cleanup_pending_no_recovery": True,
        "next_mutation_drains_cleanup_pending": True,
    }
    for key, value in expected.items():
        if surface.get(key) != value:
            errors.append(f"{label}: {key} mismatch")


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
                f"setups/{setup_id}/skills/nddev-builder/SKILL.md: missing route to {routed}"
            )
    for skill_name, references in FOCUSED_SKILL_ROUTES.items():
        skill_uri = f"skill://~/.kiro/skills/{skill_name}/SKILL.md"
        if f"`{skill_uri}`" not in entry_skill:
            errors.append(
                f"setups/{setup_id}/skills/nddev-builder/SKILL.md: missing route to {skill_uri}"
            )
        text = check_text(f"setups/{setup_id}/skills/{skill_name}/SKILL.md", errors)
        check_focused_skill(skill_name, references, text, errors)
    check_skill_file_closure(setup_id, errors)
    if not root.is_dir():
        errors.append(f"setups/{setup_id}: setup directory missing")


def check_runtime(runtime: dict[str, Any], label: str, errors: list[str]) -> None:
    if runtime.get("engine_argument") != "--v3":
        errors.append(f"{label}: launch must force --v3")
    if runtime.get("engine_status") != "early-access-required":
        errors.append(f"{label}: engine_status mismatch")
    expected_launch_scope = {
        "target_role": "managed-configuration-runtime-home",
        "workspace_source": "captured-caller-current-directory",
        "child_working_directory_policy": "strict-resolved-caller-workspace",
        "native_workspace_argument": None,
    }
    for key, value in expected_launch_scope.items():
        if runtime.get(key) != value:
            errors.append(f"{label}: {key} mismatch")
    if runtime.get("managed_launch_blocked_commands") != MANAGED_LAUNCH_BLOCKED_COMMANDS:
        errors.append(f"{label}: managed launch command guard mismatch")
    if runtime.get("managed_launch_blocked_options") != MANAGED_LAUNCH_BLOCKED_OPTIONS:
        errors.append(f"{label}: managed launch option guard mismatch")
    if runtime.get("trusted_system_path") not in (None, TRUSTED_SYSTEM_PATH):
        errors.append(f"{label}: trusted system PATH mismatch")
    if runtime.get("launch_lock_held_until_child_exit") is not True:
        errors.append(f"{label}: launch lock lifetime mismatch")
    if runtime.get("lock_mechanism") != LOCK_MECHANISM:
        errors.append(f"{label}: launch lock mechanism mismatch")
    if runtime.get("external_lock_mechanism") != EXTERNAL_LOCK_MECHANISM:
        errors.append(f"{label}: external bootstrap lock mechanism mismatch")
    if runtime.get("external_lock_root") != EXTERNAL_LOCK_ROOT_REF:
        errors.append(f"{label}: external bootstrap lock root mismatch")
    if runtime.get("external_lock_filename") != EXTERNAL_LOCK_FILENAME_REF:
        errors.append(f"{label}: external bootstrap lock filename mismatch")
    if runtime.get("external_lock_file_persistent") is not True:
        errors.append(f"{label}: persistent external lock file contract missing")
    if runtime.get("external_lock_file_mode") != LOCK_FILE_MODE:
        errors.append(f"{label}: external lock file mode mismatch")
    if runtime.get("external_lock_binding_schema") != 1:
        errors.append(f"{label}: external lock binding schema mismatch")
    if runtime.get("external_lock_acquired_before_target_inspection") is not True:
        errors.append(f"{label}: external lock preflight ordering mismatch")
    if runtime.get("external_lock_never_unlinked") is not True:
        errors.append(f"{label}: external lock unlink policy mismatch")
    check_monotonic_external_lock_fields(runtime, label, errors)
    check_cleanup_pending_fields(runtime, label, errors)
    if runtime.get("external_lock_not_exposed_to_child") is not True:
        errors.append(f"{label}: external lock child boundary mismatch")
    if runtime.get("fixed_system_temp_root_for_external_lock") is not True:
        errors.append(f"{label}: fixed system temp root contract missing")
    if runtime.get("lock_acquisition_order") != ["external", "internal"]:
        errors.append(f"{label}: lock acquisition order mismatch")
    if runtime.get("lock_release_order") != ["internal", "external"]:
        errors.append(f"{label}: lock release order mismatch")
    if runtime.get("lock_file_persistent") is not True:
        errors.append(f"{label}: persistent lock file contract missing")
    if runtime.get("lock_file_mode") != LOCK_FILE_MODE:
        errors.append(f"{label}: lock file mode mismatch")
    if runtime.get("lock_directory_idle_mode") != LOCK_DIRECTORY_IDLE_MODE:
        errors.append(f"{label}: idle lock directory mode mismatch")
    if runtime.get("lock_directory_held_mode") != LOCK_DIRECTORY_HELD_MODE:
        errors.append(f"{label}: held lock directory mode mismatch")
    if runtime.get("directory_lock_used") is not False:
        errors.append(f"{label}: removable directory lock must not be used")
    if runtime.get("ordinary_child_lock_cleanup_denied") is not True:
        errors.append(f"{label}: child lock cleanup guard missing")
    if runtime.get("runtime_mutable_directories_remain_writable") is not True:
        errors.append(f"{label}: writable runtime state contract missing")
    if runtime.get("mutable_runtime_ancestors_not_chmod_read_only") is not True:
        errors.append(f"{label}: mutable runtime ancestor guard missing")
    if runtime.get("software_launcher_artifact_immutable") is not True:
        errors.append(f"{label}: immutable launcher artifact contract missing")
    if runtime.get("software_immutable_file_mode") != SOFTWARE_IMMUTABLE_FILE_MODE:
        errors.append(f"{label}: immutable software file mode mismatch")
    if runtime.get("software_immutable_executable_mode") != SOFTWARE_IMMUTABLE_EXECUTABLE_MODE:
        errors.append(f"{label}: immutable software executable mode mismatch")
    if runtime.get("software_immutable_directory_mode") != SOFTWARE_IMMUTABLE_DIR_MODE:
        errors.append(f"{label}: immutable software directory mode mismatch")
    if runtime.get("launch_executable_revalidated_before_handoff") is not True:
        errors.append(f"{label}: executable revalidation contract missing")
    if runtime.get("launch_runtime_directories_target_relative_owner_private") is not True:
        errors.append(f"{label}: launch runtime directory trust mismatch")


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


def check_product_platform_scope(scope: Any, label: str, errors: list[str]) -> None:
    if not isinstance(scope, dict):
        errors.append(f"{label}: software platform scope required")
        return
    if scope.get("supported_platforms") != SUPPORTED_PLATFORMS:
        errors.append(f"{label}: supported platforms mismatch")
    if scope.get("vendor_observed_platforms") != VENDOR_OBSERVED_PLATFORMS:
        errors.append(f"{label}: vendor observed platforms mismatch")
    if scope.get("unsupported_platforms") != UNSUPPORTED_PLATFORMS:
        errors.append(f"{label}: unsupported platforms mismatch")
    if scope.get("platform_detection") != PLATFORM_DETECTION:
        errors.append(f"{label}: platform detection mismatch")
    if scope.get("public_platform_override_arguments") != []:
        errors.append(f"{label}: public platform override arguments must be absent")
    if scope.get("official_ubuntu_version_floor") is not None:
        errors.append(f"{label}: Ubuntu version floor must be null")
    if scope.get("official_ubuntu_glibc_floor") != OFFICIAL_UBUNTU_GLIBC_FLOOR:
        errors.append(f"{label}: Ubuntu glibc floors mismatch")
    if scope.get("product_host_package_map") != PRODUCT_HOST_PACKAGE_MAP:
        errors.append(f"{label}: product host package map mismatch")


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
    check_product_platform_scope(
        manifest.get("software_distribution"),
        "build/manifest.json",
        errors,
    )
    check_builder(manifest.get("builder"), "build/manifest.json", errors)


def release_path_roots_from_ref(value: Any) -> set[str]:
    if not isinstance(value, str) or not value.strip():
        return set()
    cleaned = value.split(":", 1)[0]
    if cleaned in {"target", "/absolute/kiro-home"} or cleaned.startswith("target/"):
        return set()
    path = Path(cleaned)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return set()
    if not path.parts:
        return set()
    return {path.parts[0]}


def contract_required_runtime_roots(
    contract: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> set[str]:
    roots = {"VERSION", "build", "cli-tools", "config"}
    if isinstance(manifest, dict):
        manager = manifest.get("manager", {})
        if isinstance(manager, dict):
            roots.update(release_path_roots_from_ref(manager.get("path")))
        runtime = manifest.get("runtime", {})
        if isinstance(runtime, dict):
            roots.update(release_path_roots_from_ref(runtime.get("baseline")))
        roots.update(release_path_roots_from_ref(manifest.get("public_validator")))
    if not isinstance(contract, dict):
        return roots
    roots.update(release_path_roots_from_ref(contract.get("manifest_ref")))
    roots.update(release_path_roots_from_ref(contract.get("version_ref")))
    setup_system = contract.get("setup_system", {})
    if isinstance(setup_system, dict):
        roots.update(release_path_roots_from_ref(setup_system.get("catalog_root")))
        roots.update(release_path_roots_from_ref(setup_system.get("profile_root")))
    runtime_compatibility = contract.get("runtime_compatibility", {})
    if isinstance(runtime_compatibility, dict):
        roots.update(release_path_roots_from_ref(runtime_compatibility.get("version_ref")))
        roots.update(release_path_roots_from_ref(runtime_compatibility.get("baseline_ref")))
    software_distribution = contract.get("software_distribution", {})
    if isinstance(software_distribution, dict):
        roots.update(
            release_path_roots_from_ref(software_distribution.get("current_artifacts_ref"))
        )
    profiles = contract.get("permission_profiles", {}).get("profiles", {})
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if isinstance(profile, dict):
                roots.update(release_path_roots_from_ref(profile.get("file")))
    return roots


def parse_release_path_list(text: str, key: str, errors: list[str]) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^(\s*){re.escape(key)}:\s*>-\s*$", line)
        if match is None:
            continue
        indent = len(match.group(1))
        result: list[str] = []
        for item in lines[index + 1 :]:
            if not item.strip():
                continue
            item_indent = len(item) - len(item.lstrip(" "))
            if item_indent <= indent:
                break
            result.extend(item.strip().split())
        if not result:
            errors.append(f".github/workflows/release.yml: {key} must not be empty")
        return result
    errors.append(f".github/workflows/release.yml: missing {key}")
    return []


def check_release_path_entry(relative: str, label: str, errors: list[str]) -> None:
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        errors.append(f".github/workflows/release.yml: {label} path is unsafe: {relative}")
        return
    forbidden = set(path.parts) & FORBIDDEN_RELEASE_PATH_PARTS
    if forbidden:
        errors.append(
            ".github/workflows/release.yml: "
            f"{label} path contains private marker {sorted(forbidden)}: {relative}"
        )
    if not (ROOT / path).exists():
        errors.append(f".github/workflows/release.yml: {label} path does not exist: {relative}")


def tracked_paths() -> set[str] | None:
    return set(extracted_artifact_files())


def check_release_path_tracked(
    relative: str,
    label: str,
    tracked: set[str] | None,
    errors: list[str],
) -> None:
    if tracked is None:
        return
    prefix = relative.rstrip("/") + "/"
    if relative not in tracked and not any(path.startswith(prefix) for path in tracked):
        errors.append(f".github/workflows/release.yml: {label} path is not tracked: {relative}")


def release_path_covers(relative: str, roots: set[str]) -> bool:
    return relative in roots or any(relative.startswith(root.rstrip("/") + "/") for root in roots)


def check_release_path_private_markers(relative: str, label: str, errors: list[str]) -> None:
    forbidden = set(Path(relative).parts) & FORBIDDEN_RELEASE_PATH_PARTS
    if forbidden:
        errors.append(
            ".github/workflows/release.yml: "
            f"{label} contains private marker {sorted(forbidden)}: {relative}"
        )


def check_tracked_archive_closure(
    tracked: set[str],
    archive_set: set[str],
    errors: list[str],
) -> None:
    for relative in sorted(tracked):
        check_release_path_private_markers(relative, "tracked path", errors)
        if not release_path_covers(relative, archive_set):
            errors.append(
                ".github/workflows/release.yml: "
                f"tracked path is not covered by archive_paths: {relative}"
            )


def extracted_artifact_files() -> list[str]:
    result: list[str] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT).as_posix()
        parts = Path(relative).parts
        if ".git" in parts or "__pycache__" in parts:
            continue
        if path.is_file():
            result.append(relative)
    return sorted(result)


def check_extracted_artifact_closure(
    archive_set: set[str],
    errors: list[str],
) -> None:
    for relative in extracted_artifact_files():
        check_release_path_private_markers(relative, "extracted artifact path", errors)
        if not release_path_covers(relative, archive_set):
            errors.append(
                ".github/workflows/release.yml: "
                f"extracted artifact path is not covered by archive_paths: {relative}"
            )


def parse_mapping_block(
    text: str,
    key: str,
    *,
    indent: int,
    child_indent: int,
    errors: list[str],
) -> dict[str, str]:
    lines = text.splitlines()
    key_prefix = " " * indent + f"{key}:"
    for index, line in enumerate(lines):
        if line != key_prefix:
            continue
        result: dict[str, str] = {}
        for item in lines[index + 1 :]:
            if not item.strip():
                continue
            item_indent = len(item) - len(item.lstrip(" "))
            if item_indent <= indent:
                break
            match = re.match(rf"^ {{{child_indent}}}([^:]+):\s+(.+?)\s*$", item)
            if match is None:
                errors.append(
                    f".github/workflows/release.yml: malformed {key} entry: {item.strip()}"
                )
                continue
            result[match.group(1)] = match.group(2)
        if not result:
            errors.append(f".github/workflows/release.yml: {key} block must not be empty")
        return result
    errors.append(f".github/workflows/release.yml: missing {key} block")
    return {}


def check_release_workflow_static(text: str, errors: list[str]) -> None:
    uses_line = f"    uses: {RELEASE_WORKFLOW_USES} # {RELEASE_WORKFLOW_VERSION}"
    if uses_line not in text.splitlines():
        errors.append(".github/workflows/release.yml: reusable workflow pin/version mismatch")
    expected_scalars = {
        "      version": RELEASE_VERSION_INPUT,
        "      package_name": RELEASE_PACKAGE_NAME,
    }
    for key, expected in expected_scalars.items():
        if f"{key}: {expected}" not in text.splitlines():
            errors.append(f".github/workflows/release.yml: {key.strip()} mismatch")
    if "permissions: {}" not in text.splitlines():
        errors.append(".github/workflows/release.yml: top-level permissions must be empty")
    job_permissions = parse_mapping_block(
        text,
        "permissions",
        indent=4,
        child_indent=6,
        errors=errors,
    )
    if job_permissions != RELEASE_JOB_PERMISSIONS:
        errors.append(".github/workflows/release.yml: publish job permissions mismatch")


def check_release_workflow(
    contract: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    errors: list[str],
) -> None:
    text = check_text(".github/workflows/release.yml", errors)
    check_release_workflow_static(text, errors)
    archive_paths = parse_release_path_list(text, "archive_paths", errors)
    runtime_paths = parse_release_path_list(text, "runtime_paths", errors)
    tracked = tracked_paths()
    for label, paths in (("archive_paths", archive_paths), ("runtime_paths", runtime_paths)):
        for relative in paths:
            check_release_path_entry(relative, label, errors)
            check_release_path_tracked(relative, label, tracked, errors)
    archive_set = set(archive_paths)
    runtime_set = set(runtime_paths)
    if not runtime_set.issubset(archive_set):
        missing = sorted(runtime_set - archive_set)
        errors.append(
            f".github/workflows/release.yml: runtime_paths not in archive_paths: {missing}"
        )
    if tracked is None:
        check_extracted_artifact_closure(archive_set, errors)
    else:
        check_tracked_archive_closure(tracked, archive_set, errors)
    required_roots = contract_required_runtime_roots(contract, manifest)
    for root in sorted(required_roots):
        if root not in archive_set:
            errors.append(f".github/workflows/release.yml: archive_paths missing {root}")
        if root not in runtime_set:
            errors.append(f".github/workflows/release.yml: runtime_paths missing {root}")


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
    if software.get("stamp_provenance_bound_to_current_baseline") is not True:
        errors.append(f"{label}: software stamp provenance baseline binding missing")
    if software.get("external_lock_mechanism") != EXTERNAL_LOCK_MECHANISM:
        errors.append(f"{label}: external lock mechanism mismatch")
    if software.get("external_lock_root") != EXTERNAL_LOCK_ROOT_REF:
        errors.append(f"{label}: external lock root mismatch")
    if software.get("external_lock_filename") != EXTERNAL_LOCK_FILENAME_REF:
        errors.append(f"{label}: external lock filename mismatch")
    if software.get("external_lock_file_persistent") is not True:
        errors.append(f"{label}: persistent external lock file missing")
    if software.get("external_lock_file_mode") != LOCK_FILE_MODE:
        errors.append(f"{label}: external lock file mode mismatch")
    if software.get("external_lock_binding_schema") != 1:
        errors.append(f"{label}: external lock binding schema mismatch")
    if software.get("external_lock_acquired_before_target_inspection") is not True:
        errors.append(f"{label}: external lock preflight ordering mismatch")
    if software.get("external_lock_never_unlinked") is not True:
        errors.append(f"{label}: external lock unlink policy mismatch")
    check_monotonic_external_lock_fields(software, label, errors)
    check_cleanup_pending_fields(software, label, errors)
    if software.get("lock_acquisition_order") != ["external", "internal"]:
        errors.append(f"{label}: lock acquisition order mismatch")
    if software.get("lock_release_order") != ["internal", "external"]:
        errors.append(f"{label}: lock release order mismatch")
    if software.get("software_launcher_artifact_immutable") is not True:
        errors.append(f"{label}: immutable launcher artifact contract missing")
    if software.get("software_parent_mode") != SOFTWARE_IMMUTABLE_DIR_MODE:
        errors.append(f"{label}: software parent mode mismatch")
    if software.get("software_directory_mode") != SOFTWARE_IMMUTABLE_DIR_MODE:
        errors.append(f"{label}: software directory mode mismatch")
    if software.get("software_file_mode") != SOFTWARE_IMMUTABLE_FILE_MODE:
        errors.append(f"{label}: software file mode mismatch")
    if software.get("software_executable_mode") != SOFTWARE_IMMUTABLE_EXECUTABLE_MODE:
        errors.append(f"{label}: software executable mode mismatch")
    check_product_platform_scope(software, label, errors)
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
        if manifest_pin.get("version") != "2.15.1":
            errors.append(f"{label}: manifest version mismatch")
        if manifest_pin.get("sha256") != MANIFEST_SHA256:
            errors.append(f"{label}: manifest sha256 mismatch")
        if manifest_pin.get("size") != MANIFEST_SIZE:
            errors.append(f"{label}: manifest size mismatch")
    installer = software.get("official_vendor_installer")
    if not isinstance(installer, dict):
        errors.append(f"{label}: official installer record required")
    else:
        if installer.get("sha256") != INSTALLER_SHA256:
            errors.append(f"{label}: installer sha256 mismatch")
        if (
            installer.get("target_owned") is not False
            or installer.get("used_by_manager") is not False
        ):
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
    if managed_state.get("backup_schema") != 3:
        errors.append("config/nddev-contract.json: backup schema mismatch")
    if managed_state.get("legacy_backup_schema") != 1:
        errors.append("config/nddev-contract.json: legacy backup schema mismatch")
    if managed_state.get("existing_target_mode") != "0700":
        errors.append("config/nddev-contract.json: existing target mode mismatch")
    if managed_state.get("runtime_state_root") != ".nddev-runtime":
        errors.append("config/nddev-contract.json: runtime state root mismatch")
    if managed_state.get("lock_root") != LOCK_ROOT_REF:
        errors.append("config/nddev-contract.json: lock root mismatch")
    if managed_state.get("lock_mechanism") != LOCK_MECHANISM:
        errors.append("config/nddev-contract.json: lock mechanism mismatch")
    if managed_state.get("external_lock_mechanism") != EXTERNAL_LOCK_MECHANISM:
        errors.append("config/nddev-contract.json: external lock mechanism mismatch")
    if managed_state.get("external_lock_root") != EXTERNAL_LOCK_ROOT_REF:
        errors.append("config/nddev-contract.json: external lock root mismatch")
    if managed_state.get("external_lock_filename") != EXTERNAL_LOCK_FILENAME_REF:
        errors.append("config/nddev-contract.json: external lock filename mismatch")
    if managed_state.get("external_lock_file_persistent") is not True:
        errors.append("config/nddev-contract.json: persistent external lock file missing")
    if managed_state.get("external_lock_file_mode") != LOCK_FILE_MODE:
        errors.append("config/nddev-contract.json: external lock file mode mismatch")
    if managed_state.get("external_lock_binding_schema") != 1:
        errors.append("config/nddev-contract.json: external lock binding schema mismatch")
    if managed_state.get("external_lock_acquired_before_target_inspection") is not True:
        errors.append("config/nddev-contract.json: external lock preflight ordering mismatch")
    if managed_state.get("external_lock_never_unlinked") is not True:
        errors.append("config/nddev-contract.json: external lock unlink policy mismatch")
    check_monotonic_external_lock_fields(
        managed_state,
        "config/nddev-contract.json",
        errors,
    )
    check_cleanup_pending_fields(
        managed_state,
        "config/nddev-contract.json",
        errors,
    )
    if managed_state.get("lock_acquisition_order") != ["external", "internal"]:
        errors.append("config/nddev-contract.json: lock acquisition order mismatch")
    if managed_state.get("lock_release_order") != ["internal", "external"]:
        errors.append("config/nddev-contract.json: lock release order mismatch")
    if managed_state.get("lock_file_persistent") is not True:
        errors.append("config/nddev-contract.json: persistent lock file missing")
    if managed_state.get("lock_file_mode") != LOCK_FILE_MODE:
        errors.append("config/nddev-contract.json: lock file mode mismatch")
    if managed_state.get("lock_directory_idle_mode") != LOCK_DIRECTORY_IDLE_MODE:
        errors.append("config/nddev-contract.json: idle lock directory mode mismatch")
    if managed_state.get("lock_directory_held_mode") != LOCK_DIRECTORY_HELD_MODE:
        errors.append("config/nddev-contract.json: held lock directory mode mismatch")
    if managed_state.get("directory_lock_used") is not False:
        errors.append("config/nddev-contract.json: directory lock must be disabled")
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
        if target_env != TARGET_ENVIRONMENT_SCOPE:
            errors.append("config/nddev-contract.json: launch environment scope mismatch")
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
        "launch_runtime_directories_target_relative_owner_private",
        "reject_symlink_runtime_directories",
        "launch_lock_held_until_child_exit",
        "persistent_kernel_lock_file",
        "lock_parent_not_writable_while_held",
        "ordinary_child_lock_cleanup_denied",
        "external_bootstrap_lock_outside_target_parent",
        "external_lock_acquired_before_target_inspection",
        "external_lock_never_unlinked",
        "external_lock_not_exposed_to_child",
        "fixed_system_temp_root_for_external_lock",
        "runtime_mutable_directories_remain_writable",
        "mutable_runtime_ancestors_not_chmod_read_only",
        "software_launcher_artifact_immutable",
        "same_uid_malicious_process_not_sandboxed",
        "launch_executable_revalidated_before_handoff",
    ):
        if safety.get(key) is not True:
            errors.append(f"config/nddev-contract.json: safety.{key} required")
    check_monotonic_external_lock_fields(
        safety,
        "config/nddev-contract.json: safety",
        errors,
    )
    check_cleanup_pending_fields(
        safety,
        "config/nddev-contract.json: safety",
        errors,
    )
    if safety.get("directory_lock_used") is not False:
        errors.append("config/nddev-contract.json: removable directory lock must be disabled")


def check_baseline(
    baseline: dict[str, Any],
    version: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if baseline.get("verified_on") != "2026-07-28":
        errors.append("references/kiro-cli-baseline.json: verified_on mismatch")
    if version is not None and baseline.get("release", {}).get("version") != version.get(
        "kiro_cli_current"
    ):
        errors.append("references/kiro-cli-baseline.json: version mismatch")
    observation_only_headers = {
        "install_manifest_last_modified",
        "install_manifest_etag",
        "install_script_last_modified",
    }
    if observation_only_headers.intersection(baseline.get("release", {})):
        errors.append("references/kiro-cli-baseline.json: observation-only HTTP metadata is public")
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
    if authentication.get("launch_lock_held_until_child_exit") is not True:
        errors.append("references/kiro-cli-baseline.json: launch lock lifetime mismatch")
    if authentication.get("lock_mechanism") != LOCK_MECHANISM:
        errors.append("references/kiro-cli-baseline.json: launch lock mechanism mismatch")
    if authentication.get("external_lock_mechanism") != EXTERNAL_LOCK_MECHANISM:
        errors.append("references/kiro-cli-baseline.json: external lock mechanism mismatch")
    if authentication.get("external_lock_root") != EXTERNAL_LOCK_ROOT_REF:
        errors.append("references/kiro-cli-baseline.json: external lock root mismatch")
    if authentication.get("external_lock_acquired_before_target_inspection") is not True:
        errors.append("references/kiro-cli-baseline.json: external lock preflight ordering missing")
    if authentication.get("external_lock_never_unlinked") is not True:
        errors.append("references/kiro-cli-baseline.json: external lock unlink policy missing")
    check_monotonic_external_lock_fields(
        authentication,
        "references/kiro-cli-baseline.json",
        errors,
    )
    check_cleanup_pending_fields(
        authentication,
        "references/kiro-cli-baseline.json",
        errors,
    )
    if authentication.get("external_lock_not_exposed_to_child") is not True:
        errors.append("references/kiro-cli-baseline.json: external lock child boundary missing")
    if authentication.get("lock_file_persistent") is not True:
        errors.append("references/kiro-cli-baseline.json: persistent lock file missing")
    if authentication.get("ordinary_child_lock_cleanup_denied") is not True:
        errors.append("references/kiro-cli-baseline.json: child lock cleanup guard missing")
    if authentication.get("runtime_mutable_directories_remain_writable") is not True:
        errors.append("references/kiro-cli-baseline.json: writable runtime state guard missing")
    if authentication.get("mutable_runtime_ancestors_not_chmod_read_only") is not True:
        errors.append("references/kiro-cli-baseline.json: mutable runtime ancestor guard missing")
    if authentication.get("software_launcher_artifact_immutable") is not True:
        errors.append("references/kiro-cli-baseline.json: immutable launcher artifact missing")
    if authentication.get("same_uid_malicious_process_not_sandboxed") is not True:
        errors.append("references/kiro-cli-baseline.json: same-UID sandbox caveat missing")
    if authentication.get("launch_executable_revalidated_before_handoff") is not True:
        errors.append("references/kiro-cli-baseline.json: executable revalidation missing")
    if authentication.get("launch_runtime_directories_target_relative_owner_private") is not True:
        errors.append("references/kiro-cli-baseline.json: launch runtime directory trust missing")
    release = baseline.get("release", {})
    if release.get("install_script_sha256") != INSTALLER_SHA256:
        errors.append("references/kiro-cli-baseline.json: install script sha256 mismatch")
    if release.get("install_manifest_sha256") != MANIFEST_SHA256:
        errors.append("references/kiro-cli-baseline.json: install manifest sha256 mismatch")
    if release.get("install_manifest_size") != MANIFEST_SIZE:
        errors.append("references/kiro-cli-baseline.json: install manifest size mismatch")
    if baseline.get("install_manifest", {}).get("version") != "2.15.1":
        errors.append("references/kiro-cli-baseline.json: install manifest version mismatch")
    software = baseline.get("software_installation")
    if not isinstance(software, dict):
        errors.append("references/kiro-cli-baseline.json: software installation missing")
    else:
        if software.get("manager_install_mode") != "target-owned-official-artifact":
            errors.append("references/kiro-cli-baseline.json: install mode mismatch")
        if software.get("lock_root") != LOCK_ROOT_REF:
            errors.append("references/kiro-cli-baseline.json: lock root mismatch")
        if software.get("lock_mechanism") != LOCK_MECHANISM:
            errors.append("references/kiro-cli-baseline.json: lock mechanism mismatch")
        if software.get("external_lock_mechanism") != EXTERNAL_LOCK_MECHANISM:
            errors.append("references/kiro-cli-baseline.json: external lock mechanism mismatch")
        if software.get("external_lock_root") != EXTERNAL_LOCK_ROOT_REF:
            errors.append("references/kiro-cli-baseline.json: external lock root mismatch")
        if software.get("external_lock_filename") != EXTERNAL_LOCK_FILENAME_REF:
            errors.append("references/kiro-cli-baseline.json: external lock filename mismatch")
        if software.get("external_lock_file_persistent") is not True:
            errors.append(
                "references/kiro-cli-baseline.json: persistent external lock file missing"
            )
        if software.get("external_lock_file_mode") != LOCK_FILE_MODE:
            errors.append("references/kiro-cli-baseline.json: external lock file mode mismatch")
        if software.get("external_lock_binding_schema") != 1:
            errors.append(
                "references/kiro-cli-baseline.json: external lock binding schema mismatch"
            )
        if software.get("external_lock_acquired_before_target_inspection") is not True:
            errors.append(
                "references/kiro-cli-baseline.json: external lock preflight ordering mismatch"
            )
        if software.get("external_lock_never_unlinked") is not True:
            errors.append("references/kiro-cli-baseline.json: external lock unlink policy mismatch")
        check_monotonic_external_lock_fields(
            software,
            "references/kiro-cli-baseline.json",
            errors,
        )
        check_cleanup_pending_fields(
            software,
            "references/kiro-cli-baseline.json",
            errors,
        )
        if software.get("lock_acquisition_order") != ["external", "internal"]:
            errors.append("references/kiro-cli-baseline.json: lock acquisition order mismatch")
        if software.get("lock_release_order") != ["internal", "external"]:
            errors.append("references/kiro-cli-baseline.json: lock release order mismatch")
        if software.get("lock_file_persistent") is not True:
            errors.append("references/kiro-cli-baseline.json: persistent lock file missing")
        if software.get("lock_file_mode") != LOCK_FILE_MODE:
            errors.append("references/kiro-cli-baseline.json: lock file mode mismatch")
        if software.get("lock_directory_idle_mode") != LOCK_DIRECTORY_IDLE_MODE:
            errors.append("references/kiro-cli-baseline.json: idle lock directory mode mismatch")
        if software.get("lock_directory_held_mode") != LOCK_DIRECTORY_HELD_MODE:
            errors.append("references/kiro-cli-baseline.json: held lock directory mode mismatch")
        if software.get("directory_lock_used") is not False:
            errors.append("references/kiro-cli-baseline.json: directory lock must be disabled")
        if software.get("backup_root") != "target/.nddev-runtime/backups/setup":
            errors.append("references/kiro-cli-baseline.json: backup root mismatch")
        if software.get("trusted_bash") != "/bin/bash":
            errors.append("references/kiro-cli-baseline.json: trusted bash mismatch")
        if software.get("trusted_system_path") != TRUSTED_SYSTEM_PATH:
            errors.append("references/kiro-cli-baseline.json: trusted system PATH mismatch")
        if software.get("official_vendor_installer_supported") is not False:
            errors.append("references/kiro-cli-baseline.json: installer limitation missing")
        check_product_platform_scope(
            software,
            "references/kiro-cli-baseline.json",
            errors,
        )
        if software.get("update_installs_absent") is not False:
            errors.append("references/kiro-cli-baseline.json: absent update must be disabled")
        if software.get("absent_update_behavior") != "domain-error-install-first":
            errors.append("references/kiro-cli-baseline.json: absent update behavior mismatch")
        if software.get("production_source_pins_required") is not True:
            errors.append("references/kiro-cli-baseline.json: production source pins missing")
        if software.get("source_override_arguments") != []:
            errors.append("references/kiro-cli-baseline.json: source overrides must be absent")
        if software.get("test_source_environment_switches") != []:
            errors.append(
                "references/kiro-cli-baseline.json: test source env switches must be absent"
            )
        if software.get("manager_build_version_mismatch") != "needs-update":
            errors.append(
                "references/kiro-cli-baseline.json: manager build mismatch behavior mismatch"
            )
        if software.get("remove_tolerates_missing_or_malformed_stamp_after_trust") is not True:
            errors.append(
                "references/kiro-cli-baseline.json: malformed stamp remove behavior mismatch"
            )
        if software.get("status_launch_allowed_requires_clean_software") is not True:
            errors.append(
                "references/kiro-cli-baseline.json: launch_allowed software precondition missing"
            )
        if software.get("stamp_provenance_bound_to_current_baseline") is not True:
            errors.append(
                "references/kiro-cli-baseline.json: software stamp provenance binding missing"
            )
        if software.get("software_launcher_artifact_immutable") is not True:
            errors.append("references/kiro-cli-baseline.json: immutable launcher artifact missing")
        if software.get("software_parent_mode") != SOFTWARE_IMMUTABLE_DIR_MODE:
            errors.append("references/kiro-cli-baseline.json: software parent mode mismatch")
        if software.get("software_directory_mode") != SOFTWARE_IMMUTABLE_DIR_MODE:
            errors.append("references/kiro-cli-baseline.json: software directory mode mismatch")
        if software.get("software_file_mode") != SOFTWARE_IMMUTABLE_FILE_MODE:
            errors.append("references/kiro-cli-baseline.json: software file mode mismatch")
        if software.get("software_executable_mode") != SOFTWARE_IMMUTABLE_EXECUTABLE_MODE:
            errors.append("references/kiro-cli-baseline.json: software executable mode mismatch")
    packages = baseline.get("install_manifest", {}).get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append("references/kiro-cli-baseline.json: install packages missing")
    elif not all(isinstance(item, dict) and item.get("sha256") for item in packages):
        errors.append("references/kiro-cli-baseline.json: package sha256 missing")
    elif packages != EXPECTED_INSTALL_PACKAGES:
        errors.append("references/kiro-cli-baseline.json: install package catalog mismatch")


def check_manager_source(text: str, errors: list[str]) -> None:
    for token in DISALLOWED_MANAGER_SOURCE_TOKENS:
        if token in text:
            errors.append(f"cli-tools/nddev_kiro_cli.py: disallowed test/source switch {token!r}")
    if "def write_complete(" not in text or "written <= 0" not in text:
        errors.append(
            "cli-tools/nddev_kiro_cli.py: complete write loop must reject no-progress writes"
        )
    required_launch_fragments = (
        "caller_workspace = resolve_caller_workspace()",
        "cwd=str(workspace)",
        '"launch_scope": launch_scope_status()',
    )
    for fragment in required_launch_fragments:
        if fragment not in text:
            errors.append(f"cli-tools/nddev_kiro_cli.py: launch scope missing {fragment}")


def check_claude_bridge(errors: list[str]) -> None:
    directory = ROOT / ".claude"
    try:
        directory_info = directory.lstat()
    except FileNotFoundError:
        errors.append(".claude bridge directory must exist")
        return
    if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
        errors.append(".claude bridge directory must be a real directory")
        return
    try:
        entries = sorted(path.name for path in directory.iterdir())
    except OSError as exc:
        errors.append(f".claude bridge directory is unreadable: {exc}")
        return
    if entries != ["CLAUDE.md"]:
        errors.append(".claude bridge directory must contain only CLAUDE.md")
    relative = ".claude/CLAUDE.md"
    path = ROOT / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        errors.append(".claude/CLAUDE.md bridge must exist")
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        errors.append(".claude/CLAUDE.md bridge must be a regular file")
        return
    try:
        content = path.read_bytes()
    except OSError as exc:
        errors.append(f".claude/CLAUDE.md bridge is unreadable: {exc}")
        return
    if content != CLAUDE_BRIDGE_BYTES:
        errors.append(".claude/CLAUDE.md bridge must exactly import ../AGENTS.md")


def check_python_portability(errors: list[str]) -> None:
    for relative in PORTABLE_PYTHON_SOURCES:
        path = ROOT / relative
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{relative}: cannot read for Python syntax validation: {exc}")
            continue
        try:
            ast.parse(source, filename=str(path), feature_version=PYTHON_SYNTAX_FEATURE_VERSION)
        except SyntaxError as exc:
            errors.append(
                f"{relative}: must parse under Python 3.9 syntax: line {exc.lineno}: {exc.msg}"
            )


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
        if version.get("kiro_cli_current") != "2.15.1":
            errors.append("build/version.json: kiro_cli_current must be 2.15.1")
        if version.get("python_requires") != PYTHON_REQUIRES:
            errors.append(f"build/version.json: python_requires must be {PYTHON_REQUIRES}")
    if manifest is not None:
        check_manifest(manifest, version_text, errors)
    if contract is not None:
        check_contract(contract, errors)
    if baseline is not None:
        check_baseline(baseline, version, errors)
    check_release_workflow(contract, manifest, errors)

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
    check_python_portability(errors)
    check_claude_bridge(errors)
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
