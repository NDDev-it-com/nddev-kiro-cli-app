#!/usr/bin/env python3
"""Target-explicit Kiro CLI setup manager for NDDev.

The manager writes one selected setup into an explicit isolated ``KIRO_HOME``
target. It never infers or mutates the caller's live ``~/.kiro`` state. Only
selected Kiro settings keys, the permission profile, the native NDDev builder
projection, and the target-bound stamp are owned; sibling settings keys and
unrelated files are preserved.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, Optional

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-kiro-cli-app"
STAMP_NAME = "NDDEV-KIRO-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-KIRO-CLI-BACKUP.json"
STAMP_SCHEMA = 2
LEGACY_STAMP_SCHEMA = 1
BACKUP_SCHEMA = 3
LEGACY_BACKUP_SCHEMA = 1
MAX_BACKUPS = 10
ROLLBACK_RETRY_ATTEMPTS = 3
OWNER_FILE_MODE = 0o600
OWNER_DIR_MODE = 0o700
LOCK_HELD_DIR_MODE = 0o500
SOFTWARE_IMMUTABLE_FILE_MODE = 0o400
SOFTWARE_IMMUTABLE_EXECUTABLE_MODE = 0o500
SOFTWARE_IMMUTABLE_DIR_MODE = 0o500
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 1024 * 1024
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
GLIBC_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)*\Z")
OFFICIAL_UBUNTU_GLIBC_FLOORS = {
    "x86_64": "2.34",
    "aarch64": "2.39",
}
PRODUCT_HOST_GATED_COMMANDS = {
    "status",
    "plan",
    "install",
    "apply",
    "update",
    "switch",
    "migrate",
    "restore",
    "remove",
    "launch",
    "software-status",
    "software-probe",
    "software-install",
    "software-update",
    "software-remove",
}
CONTENT_SETUP_ID = "nddev-builder"
DEFAULT_PERMISSION_PROFILE_ID = "full-auto"
PERMISSION_PROFILE_IDS = ("safe", "full-auto")
LEGACY_SETUP_IDS = ("safe", "balanced", "full-auto")
SETTINGS = "settings/cli.json"
PERMISSIONS = "settings/permissions.yaml"
BUILDER_AGENT = "agents/nddev-builder.md"
BUILDER_SKILL = "skills/nddev-builder/SKILL.md"
BUILDER_FOCUSED_SKILLS = (
    "skills/kiro-module-creator/SKILL.md",
    "skills/kiro-module-checker/SKILL.md",
    "skills/kiro-release-checker/SKILL.md",
    "skills/kiro-config-profile-creator/SKILL.md",
    "skills/kiro-config-profile-checker/SKILL.md",
    "skills/kiro-permissions-creator/SKILL.md",
    "skills/kiro-permissions-checker/SKILL.md",
    "skills/kiro-agent-creator/SKILL.md",
    "skills/kiro-agent-checker/SKILL.md",
    "skills/kiro-skill-creator/SKILL.md",
    "skills/kiro-skill-checker/SKILL.md",
    "skills/kiro-hook-checker/SKILL.md",
    "skills/kiro-mcp-checker/SKILL.md",
    "skills/kiro-plugin-marketplace-checker/SKILL.md",
    "skills/kiro-lifecycle-checker/SKILL.md",
)
BUILDER_SKILL_REFERENCES = (
    "skills/nddev-builder/references/agents-subagents.md",
    "skills/nddev-builder/references/configuration-profiles.md",
    "skills/nddev-builder/references/creator-checker-release.md",
    "skills/nddev-builder/references/hooks.md",
    "skills/nddev-builder/references/installation-lifecycle.md",
    "skills/nddev-builder/references/mcp.md",
    "skills/nddev-builder/references/permissions-sandbox.md",
    "skills/nddev-builder/references/plugins-marketplace.md",
    "skills/nddev-builder/references/skills-instructions.md",
)
BUILDER_STEERING = "steering/nddev-builder.md"
BUILDER_HOOK = "hooks/nddev-builder.json"
BUILDER_FILES = (
    BUILDER_AGENT,
    BUILDER_SKILL,
    *BUILDER_FOCUSED_SKILLS,
    *BUILDER_SKILL_REFERENCES,
    BUILDER_STEERING,
)
LEGACY_BUILDER_FILES = (BUILDER_AGENT, BUILDER_SKILL, BUILDER_STEERING, BUILDER_HOOK)
MANAGED_FILES = (SETTINGS, PERMISSIONS, *BUILDER_FILES)
LEGACY_MANAGED_FILES = (SETTINGS, PERMISSIONS, *LEGACY_BUILDER_FILES)
BASELINE_PATH = ROOT / "references" / "kiro-cli-baseline.json"
OFFICIAL_INSTALL_MANIFEST_URL = "https://prod.download.cli.kiro.dev/stable/latest/manifest.json"
NDDEV_RUNTIME_DIR = ".nddev-runtime"
SOFTWARE_RUNTIME_DIR = ".nddev-runtime/software"
SOFTWARE_DIR_NAME = "kiro-cli"
SOFTWARE_STAMP_NAME = "NDDEV-KIRO-CLI-SOFTWARE.json"
SOFTWARE_STAMP_SCHEMA = 1
LOCK_RUNTIME_DIR = ".nddev-runtime/locks"
LOCK_DIR_NAME = "setup-manager.lock"
EXTERNAL_LOCK_SCHEMA = 1
EXTERNAL_BOOTSTRAP_LOCK_NAME = "global.lock"
EXTERNAL_LOCK_NAME_SUFFIX = ".lock"
EXTERNAL_LOCK_ALIAS_SCAN_MAX = 128
BACKUP_RUNTIME_DIR = ".nddev-runtime/backups/setup"
CLEANUP_PENDING_RUNTIME_DIR = ".nddev-runtime/cleanup-pending"
CLEANUP_INTENT_NAME = "NDDEV-KIRO-CLI-CLEANUP-INTENT.json"
CLEANUP_INTENT_SCHEMA = 1
CLEANUP_JOURNAL_NAME = "NDDEV-KIRO-CLI-CLEANUP.json"
CLEANUP_JOURNAL_SCHEMA = 1
CLEANUP_JOURNAL_MAX_BYTES = 16 * 1024 * 1024
CLEANUP_INTENT_MAX_BYTES = 16 * 1024 * 1024
CLEANUP_TOMBSTONE_NAME = "tombstone"
CLEANUP_JOURNAL_ALIAS_SCAN_MAX = 8
CLEANUP_TOMBSTONE_MAX_FILES = 20000
CLEANUP_TOMBSTONE_MAX_BYTES = 3 * 1024 * 1024 * 1024
TRUSTED_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
TRUSTED_BASH = "/bin/bash"
TRUSTED_HDIUTIL = "/usr/bin/hdiutil"
SOFTWARE_TREE_MAX_FILES = 20000
SOFTWARE_TREE_MAX_BYTES = 3 * 1024 * 1024 * 1024
SOFTWARE_METADATA_MAX_BYTES = 1024 * 1024
DOWNLOAD_METADATA_MAX_BYTES = 4 * 1024 * 1024
BACKUP_TREE_MAX_FILES = 256
MANAGED_LAUNCH_ENGINE_ARGUMENT = "--v3"
MANAGED_LAUNCH_ENGINE_STATUS = "early-access-required"
MANAGED_LAUNCH_BLOCKED_OPTIONS = (
    "--agent",
    "--classic",
    "--no-interactive",
    "--require-mcp-startup",
    "--trust-all-tools",
    "--trust-tools",
    "--v3",
)
MANAGED_LAUNCH_BLOCKED_COMMANDS = (
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
)
SETTINGS_MANAGED_KEYS = (
    "app.disableAutoupdates",
    "chat.defaultAgent",
    "chat.ui",
    "telemetry.enabled",
)
BUILDER_PROJECTION = "native-agent-skill-steering"
LEGACY_BUILDER_PROJECTION = "native-agent-skill-steering-hook"
STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "permission_profile_id",
    "canonical_target",
    "managed_files",
    "builder",
    "engine",
}
LEGACY_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder",
}
BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "source_permission_profile_id",
    "stamp_schema",
    "managed_files",
    "stamp_sha256",
}
BACKUP_RECORD_KEYS = {"path", "size", "sha256"}
CLEANUP_JOURNAL_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "cleanup_parent",
    "journal_name",
    "tombstone_name",
    "kind",
    "bounds",
    "object_count",
    "byte_count",
    "objects",
}
CLEANUP_JOURNAL_BOUNDS_KEYS = {"max_files", "max_bytes"}
CLEANUP_INTENT_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "cleanup_parent",
    "intent_name",
    "journal_name",
    "tombstone_name",
    "kind",
    "bounds",
    "source_count",
    "sources",
}
CLEANUP_INTENT_SOURCE_KEYS = {
    "index",
    "source_kind",
    "source_anchor",
    "source_name",
    "source_parent",
    "destination_relative",
    "objects",
}
CLEANUP_INTENT_PARENT_KEYS = {
    "uid",
    "mode",
    "nlink",
    "dev",
    "inode",
    "size",
    "mtime_ns",
}
CLEANUP_JOURNAL_OBJECT_KEYS = {
    "relative",
    "kind",
    "uid",
    "mode",
    "nlink",
    "dev",
    "inode",
    "size",
    "mtime_ns",
    "sha256",
}
LEGACY_BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "managed_files",
    "stamp_sha256",
}
SOFTWARE_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "runtime_product",
    "version",
    "canonical_target",
    "install_mode",
    "package",
    "executable",
    "tree",
    "official_vendor_installer",
}
SECRET_ENV_PREFIXES = (
    "AWS_",
    "AMAZON_",
    "CODEWHISPERER_",
    "Q_",
    "GOOGLE_",
    "ANTHROPIC_",
    "OPENAI_",
    "AZURE_",
)
SECRET_ENV_NAMES = {
    "KIRO_API_KEY",
    "KIRO_AUTH_TOKEN",
    "KIRO_ACCESS_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
}


class ManagerError(Exception):
    """A structured user-facing lifecycle failure."""


class ConcurrentTargetChange(ManagerError):
    """A fail-closed target race or identity change."""


@dataclass(frozen=True)
class Setup:
    setup_id: str
    description: str
    managed_settings: dict[str, Any]
    managed_content_files: tuple[str, ...]
    builder_enabled: bool
    files: dict[str, bytes]


@dataclass(frozen=True)
class PermissionProfile:
    profile_id: str
    description: str
    permissions: bytes


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes | None
    digest: str | None
    mode: int | None
    inode: int | None = None
    mtime_ns: int | None = None


@dataclass(frozen=True)
class DirectorySnapshot:
    existed: bool
    mode: int | None
    inode: int | None
    mtime_ns: int | None


@dataclass(frozen=True)
class TreeSnapshotEntry:
    kind: str
    mode: int
    content: bytes | None
    size: int | None
    sha256: str | None
    dev: int
    inode: int
    mtime_ns: int
    link_target: str | None = None


@dataclass
class ExternalLockFile:
    lock: Path
    descriptor: int
    created: bool
    parent_snapshot: dict[str, TreeSnapshotEntry] | None
    created_identity: tuple[int, int] | None
    committed: bool = False


@dataclass(frozen=True)
class ProductRootCreation:
    root: Path
    created: bool
    parent_snapshot: DirectorySnapshot | None


@dataclass(frozen=True)
class TreeManifestEntry:
    kind: str
    mode: int
    size: int | None
    sha256: str | None
    inode: int
    mtime_ns: int


@dataclass(frozen=True)
class CleanupJournalEntry:
    relative: str
    kind: str
    uid: int | None
    mode: int
    nlink: int
    dev: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str | None


@dataclass(frozen=True)
class CleanupPendingState:
    parent: Path
    journal: Path
    journal_content: bytes
    tombstone: Path
    kind: str
    object_count: int
    byte_count: int
    objects: dict[str, CleanupJournalEntry]
    children: dict[str, set[str]]
    journal_alias: Path | None = None
    intent: Path | None = None
    intent_alias: Path | None = None


@dataclass(frozen=True)
class BackupTransaction:
    slot: int
    pool: Path
    slot_dir: Path
    stage_dir: Path
    backup_managed_files: tuple[str, ...]


@dataclass(frozen=True)
class BackupCommitResult:
    slot: int
    cleanup_pending: bool
    retirement_dir: Path | None = None


@dataclass(frozen=True)
class ManagedStateTransaction:
    target: Path
    rollback_dir: Path | None
    before: dict[str, FileSnapshot]
    desired: dict[str, bytes | None]
    managed_files: tuple[str, ...]
    directories: dict[str, DirectorySnapshot]
    remove_empty_parents: bool
    changed: tuple[str, ...]


@dataclass(frozen=True)
class SoftwarePackage:
    os_name: str
    architecture: str
    libc: str | None
    file_type: str
    variant: str
    download: str
    sha256: str
    size: int
    cli_path: str | None


@dataclass(frozen=True)
class SoftwareTree:
    digest: str
    file_count: int
    byte_count: int
    executable_sha256: str


def fail(message: str) -> NoReturn:
    raise ManagerError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_complete(descriptor: int, content: bytes, label: str) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            fail(f"{label} write made no progress")
        remaining = remaining[written:]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def current_user_owns(info: os.stat_result) -> bool:
    return not hasattr(os, "geteuid") or owner_of(info) == os.geteuid()


def is_owner_only_file(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    if not current_user_owns(info):
        return False
    return True


def require_current_user_owned(info: os.stat_result, label: str) -> None:
    if not current_user_owns(info):
        fail(f"{label} must be owned by the current user")


def require_exact_mode(info: os.stat_result, label: str, expected: int) -> None:
    actual = stat.S_IMODE(info.st_mode)
    if actual != expected:
        fail(f"{label} must have mode {expected:04o}, got {actual:04o}")


def require_owner_private_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    require_current_user_owned(info, label)
    require_exact_mode(info, label, OWNER_DIR_MODE)
    return info


def require_owner_private_file(path: Path, label: str) -> os.stat_result:
    info = require_regular_file(path, label, owner_only=True)
    require_exact_mode(info, label, OWNER_FILE_MODE)
    return info


def ensure_target_private_directory(target: Path, relative: str, label: str) -> Path:
    relative_path = safe_relative_path(relative)
    require_owner_private_directory(target, "target")
    target_root = target.resolve(strict=True)
    current = target
    for part in relative_path.parts:
        current = current / part
        component_label = f"{label} component {current}"
        info = lstat_optional(current)
        if info is None:
            try:
                current.mkdir(mode=OWNER_DIR_MODE)
            except FileExistsError as exc:
                raise ConcurrentTargetChange(f"{component_label} appeared during creation") from exc
            info = require_directory(current, component_label)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{component_label} must be a real directory")
        require_current_user_owned(info, component_label)
        require_exact_mode(info, component_label, OWNER_DIR_MODE)
    try:
        current.resolve(strict=True).relative_to(target_root)
    except ValueError:
        fail(f"{label} must remain under the target")
    return current


def safe_relative_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        fail(f"managed path is not safe: {relative}")
    return path


def reject_symlink_ancestors(root: Path, relative: str) -> None:
    current = root
    for part in safe_relative_path(relative).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent must be a real directory: {current}")
        ensure_not_group_world_writable(info, f"managed parent {current}")


def require_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    return info


def require_regular_file(path: Path, label: str, *, owner_only: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    if owner_only and not is_owner_only_file(info):
        fail(f"{label} must be owned by the current user with mode 0600")
    return info


def read_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> tuple[bytes, os.stat_result]:
    before = require_regular_file(path, label, owner_only=owner_only)
    if before.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} changed while it was opened")
        if opened.st_size > max_bytes:
            fail(f"{label} exceeds the {max_bytes}-byte size limit")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            blocks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, owner_only=owner_only)
    if identity_of(final) != identity_of(before) or identity_of(after) != identity_of(before):
        raise ConcurrentTargetChange(f"{label} changed while it was read")
    return b"".join(blocks), final


def digest_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> tuple[str, os.stat_result]:
    before = require_regular_file(path, label, owner_only=owner_only)
    if before.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    total = 0
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} changed while it was opened")
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            digest.update(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, owner_only=owner_only)
    if identity_of(final) != identity_of(before) or identity_of(after) != identity_of(before):
        raise ConcurrentTargetChange(f"{label} changed while it was read")
    return digest.hexdigest(), final


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def read_json_file(path: Path, label: str, *, owner_only: bool = False) -> dict[str, Any]:
    content, _ = read_regular_file(
        path,
        label,
        owner_only=owner_only,
        max_bytes=METADATA_MAX_BYTES,
    )
    return parse_json_object(content, label)


def lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None


def load_baseline() -> dict[str, Any]:
    return read_json_file(BASELINE_PATH, "Kiro CLI runtime baseline")


def expected_runtime_version() -> str:
    baseline = load_baseline()
    version = baseline.get("release", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        fail("Kiro CLI baseline release.version is missing")
    return version


def official_vendor_installer_record() -> dict[str, Any]:
    baseline = load_baseline()
    script = baseline.get("release", {})
    limitations = baseline.get("software_installation", {}).get(
        "official_vendor_installer_limitations",
        [],
    )
    return {
        "url": script.get("install_script_url"),
        "sha256": script.get("install_script_sha256"),
        "target_owned": False,
        "limitations": limitations,
        "used_by_manager": False,
    }


def parse_os_release_content(content: str) -> dict[str, str]:
    release: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        release[key] = value
    return release


def freedesktop_os_release() -> Mapping[str, str]:
    reader = getattr(platform, "freedesktop_os_release", None)
    if reader is not None:
        return reader()
    try:
        return parse_os_release_content(Path("/etc/os-release").read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManagerError(
            "Ubuntu software installs require structured os-release detection"
        ) from exc


def require_ubuntu_os_release(os_release: Mapping[str, str] | None = None) -> None:
    try:
        release = freedesktop_os_release() if os_release is None else os_release
    except OSError:
        fail("Ubuntu software installs require structured os-release detection")
    distro_id = str(release.get("ID", "")).strip().lower()
    if distro_id != "ubuntu":
        fail("unsupported Linux distribution: Ubuntu is required")


def normalize_platform_name(value: str | None) -> str:
    if value not in {None, ""}:
        raw = value.strip()
        normalized = raw.lower()
        if normalized in {"darwin", "mac", "macos"}:
            return "macos"
        if normalized == "ubuntu":
            return "ubuntu"
        if normalized == "linux":
            fail("unsupported software platform: Linux distribution must be Ubuntu")
        fail(f"unsupported software platform: {raw}")

    raw = platform.system().lower()
    normalized = raw.lower()
    if normalized in {"darwin", "mac", "macos"}:
        return "macos"
    if normalized == "linux":
        require_ubuntu_os_release()
        return "ubuntu"
    fail(f"unsupported software platform: {raw}")


def normalize_architecture(value: str | None, os_name: str) -> str:
    if os_name == "macos":
        if value in {None, "", "universal"}:
            return "universal"
        if value in {"x86_64", "amd64", "arm64", "aarch64"}:
            return "universal"
        fail(f"unsupported macOS architecture: {value}")
    if os_name != "ubuntu":
        fail(f"unsupported software platform: {os_name}")
    raw = value or platform.machine().lower()
    if raw in {"x86_64", "amd64"}:
        return "x86_64"
    if raw in {"arm64", "aarch64"}:
        return "aarch64"
    fail(f"unsupported Ubuntu architecture: {raw}")


def parse_glibc_version(value: str) -> tuple[int, ...]:
    raw = value.strip()
    if not raw:
        fail("Ubuntu glibc version is required")
    if not GLIBC_VERSION_PATTERN.fullmatch(raw):
        fail(f"Ubuntu glibc version is malformed: {value!r}")
    return tuple(int(part) for part in raw.split("."))


def require_ubuntu_glibc_floor(architecture: str, version: str) -> None:
    minimum = OFFICIAL_UBUNTU_GLIBC_FLOORS.get(architecture)
    if minimum is None:
        fail(f"unsupported Ubuntu architecture: {architecture}")
    actual_parts = parse_glibc_version(version)
    minimum_parts = parse_glibc_version(minimum)
    width = max(len(actual_parts), len(minimum_parts))
    padded_actual = actual_parts + (0,) * (width - len(actual_parts))
    padded_minimum = minimum_parts + (0,) * (width - len(minimum_parts))
    if padded_actual < padded_minimum:
        fail(f"Ubuntu {architecture} requires glibc >= {minimum}; detected {version!r}")


def detect_ubuntu_libc(architecture: str) -> str:
    if platform.system().lower() != "linux":
        fail("Ubuntu libc detection requires a Linux host")
    libc_name, libc_version = platform.libc_ver()
    if libc_name.lower() in {"glibc", "gnu"}:
        require_ubuntu_glibc_floor(architecture, libc_version)
        return "glibc"
    fail("unsupported Ubuntu libc variant: glibc is required")


def normalize_libc(value: str | None, os_name: str, architecture: str | None = None) -> str | None:
    if os_name != "ubuntu":
        if value not in {None, ""}:
            fail("--libc is only valid for Ubuntu software installs")
        return None
    if value in {None, ""}:
        if architecture is None:
            fail("Ubuntu architecture is required before libc detection")
        return detect_ubuntu_libc(architecture)
    if value in {"glibc", "gnu"}:
        return "glibc"
    if value == "musl":
        fail("unsupported Ubuntu libc variant: musl is not supported")
    fail(f"unsupported Ubuntu libc variant: {value}")


def validate_supported_product_host() -> str:
    os_name = normalize_platform_name(None)
    if os_name == "macos":
        raw = platform.machine().lower()
        if raw in {"arm64", "aarch64"}:
            return "macos-arm64"
        if raw in {"x86_64", "amd64"}:
            return "macos-x64"
        fail(f"unsupported macOS architecture: {raw}")
    architecture = normalize_architecture(None, os_name)
    libc = normalize_libc(None, os_name, architecture)
    if libc != "glibc":
        fail("unsupported Ubuntu libc variant: glibc is required")
    if architecture == "x86_64":
        return "ubuntu-glibc-x64"
    if architecture == "aarch64":
        return "ubuntu-glibc-arm64"
    fail(f"unsupported Ubuntu architecture: {architecture}")


def require_supported_host_preflight() -> None:
    validate_supported_product_host()


def command_requires_supported_host(command: str | None) -> bool:
    return command in PRODUCT_HOST_GATED_COMMANDS


def baseline_packages() -> list[dict[str, Any]]:
    baseline = load_baseline()
    packages = baseline.get("install_manifest", {}).get("packages")
    if not isinstance(packages, list) or not packages:
        fail("Kiro CLI baseline packages are missing")
    result: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict):
            fail("Kiro CLI baseline package entry must be an object")
        result.append(package)
    return result


def package_matches(
    package: dict[str, Any],
    product_platform: str,
    architecture: str,
    libc: str | None,
) -> bool:
    if product_platform == "macos":
        if package.get("os") != "macos" or package.get("architecture") != architecture:
            return False
        return package.get("fileType") == "dmg" and package.get("variant") == "full"
    if (
        product_platform != "ubuntu"
        or package.get("os") != "linux"
        or package.get("architecture") != architecture
    ):
        return False
    if package.get("fileType") != "zip" or package.get("variant") != "headless":
        return False
    download = str(package.get("download", ""))
    target_triple = str(package.get("targetTriple", ""))
    return (
        libc == "glibc"
        and "-musl." not in download
        and target_triple.endswith(
            "unknown-linux-gnu",
        )
    )


def select_baseline_package(os_name: str, architecture: str, libc: str | None) -> SoftwarePackage:
    product_platform = normalize_platform_name(os_name)
    normalized_architecture = normalize_architecture(architecture, product_platform)
    normalized_libc = normalize_libc(libc, product_platform, normalized_architecture)
    matches = [
        package
        for package in baseline_packages()
        if package_matches(package, product_platform, normalized_architecture, normalized_libc)
    ]
    if len(matches) != 1:
        fail(
            "cannot select exact Kiro CLI package for "
            f"{product_platform}/{normalized_architecture}/{normalized_libc}",
        )
    package = matches[0]
    sha256 = package.get("sha256")
    download = package.get("download")
    size = package.get("size")
    if (
        not isinstance(sha256, str)
        or not SHA256_PATTERN.fullmatch(sha256)
        or not isinstance(download, str)
        or not isinstance(size, int)
        or size <= 0
    ):
        fail("selected Kiro CLI package is missing download, size, or sha256")
    return SoftwarePackage(
        os_name=str(package.get("os")),
        architecture=normalized_architecture,
        libc=normalized_libc,
        file_type=str(package.get("fileType")),
        variant=str(package.get("variant")),
        download=download,
        sha256=sha256,
        size=size,
        cli_path=package.get("cliPath") if isinstance(package.get("cliPath"), str) else None,
    )


def parse_content_length(value: str | None, max_bytes: int, label: str) -> int | None:
    if value is None:
        return None
    try:
        expected = int(value)
    except ValueError:
        fail(f"{label} Content-Length is not an integer")
    if expected < 0:
        fail(f"{label} Content-Length is negative")
    if expected > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    return expected


def verify_content_length(expected: int | None, actual: int, label: str) -> None:
    if expected is not None and actual != expected:
        fail(f"{label} Content-Length mismatch")


def read_bounded_url(url: str, max_bytes: int, label: str) -> bytes:
    if not url.startswith("https://"):
        fail(f"{label} must use https")
    request = urllib.request.Request(url, headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"})
    expected_length: int | None = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            expected_length = parse_content_length(
                response.headers.get("Content-Length"),
                max_bytes,
                label,
            )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fail(f"{label} exceeds the {max_bytes}-byte size limit")
                chunks.append(chunk)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        fail(f"failed to download {label}: {exc}")
    content = b"".join(chunks)
    verify_content_length(expected_length, len(content), label)
    return content


def download_bounded_url(url: str, destination: Path, max_bytes: int, label: str) -> str:
    if not url.startswith("https://"):
        fail(f"{label} must use https")
    make_parent_directories(destination)
    request = urllib.request.Request(url, headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"})
    digest = hashlib.sha256()
    total = 0
    expected_length: int | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            expected_length = parse_content_length(
                response.headers.get("Content-Length"),
                max_bytes,
                label,
            )
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        fail(f"{label} exceeds the {max_bytes}-byte size limit")
                    digest.update(chunk)
                    handle.write(chunk)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        destination.unlink(missing_ok=True)
        fail(f"failed to download {label}: {exc}")
    try:
        verify_content_length(expected_length, total, label)
    except ManagerError:
        destination.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def read_manifest_source() -> dict[str, Any]:
    content = read_bounded_url(
        OFFICIAL_INSTALL_MANIFEST_URL,
        DOWNLOAD_METADATA_MAX_BYTES,
        "Kiro CLI install manifest",
    )
    baseline = load_baseline()
    release = baseline.get("release", {})
    expected_digest = release.get("install_manifest_sha256")
    expected_size = release.get("install_manifest_size")
    if (
        not isinstance(expected_digest, str)
        or not SHA256_PATTERN.fullmatch(expected_digest)
        or not isinstance(expected_size, int)
        or expected_size <= 0
    ):
        fail("Kiro CLI baseline install manifest pin is missing")
    if len(content) != expected_size:
        fail("Kiro CLI install manifest size changed")
    if sha256_bytes(content) != expected_digest:
        fail("Kiro CLI install manifest digest changed")
    return parse_json_object(content, "Kiro CLI install manifest")


def verify_manifest_package(manifest: dict[str, Any], package: SoftwarePackage) -> None:
    version = manifest.get("version")
    expected = expected_runtime_version()
    if version != expected:
        fail(f"Kiro CLI install manifest version must be {expected}, got {version!r}")
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        fail("Kiro CLI install manifest packages must be a list")
    matches = [
        item
        for item in packages
        if isinstance(item, dict) and item.get("download") == package.download
    ]
    if len(matches) != 1:
        fail(f"Kiro CLI install manifest is missing {package.download}")
    actual = matches[0]
    if actual.get("sha256") != package.sha256 or actual.get("size") != package.size:
        fail(f"Kiro CLI install manifest package identity changed for {package.download}")


def artifact_download_url(base_url: str, download: str) -> str:
    parsed = urllib.parse.urlsplit(base_url.rstrip("/") + "/")
    if parsed.scheme != "https" or not parsed.netloc:
        fail("Kiro CLI artifact base URL must use https")
    if parsed.query or parsed.fragment:
        fail("Kiro CLI artifact base URL must not include query or fragment")
    encoded_download = urllib.parse.quote(download, safe="/")
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/{encoded_download}" if base_path else f"/{encoded_download}"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def stage_artifact(stage: Path, package: SoftwarePackage) -> Path:
    artifact = stage / "download" / Path(package.download).name
    url = artifact_download_url("https://prod.download.cli.kiro.dev/stable", package.download)
    digest = download_bounded_url(
        url,
        artifact,
        package.size,
        "Kiro CLI software artifact",
    )
    if artifact.stat().st_size != package.size:
        artifact.unlink(missing_ok=True)
        fail("Kiro CLI software artifact size mismatch")
    if digest != package.sha256:
        artifact.unlink(missing_ok=True)
        fail("Kiro CLI software artifact digest mismatch")
    return artifact


def software_root(target: Path) -> Path:
    return target / SOFTWARE_RUNTIME_DIR / SOFTWARE_DIR_NAME


def software_parent(target: Path) -> Path:
    return target / SOFTWARE_RUNTIME_DIR


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def software_executable_from_stamp(target: Path, stamp: dict[str, Any]) -> Path:
    executable = stamp.get("executable")
    if not isinstance(executable, dict):
        fail("software stamp executable is invalid")
    relative = executable.get("relative_path")
    if not isinstance(relative, str):
        fail("software stamp executable relative_path is invalid")
    return software_root(target) / safe_relative_path(relative)


def ensure_not_group_world_writable(info: os.stat_result, label: str) -> None:
    if stat.S_IMODE(info.st_mode) & 0o022:
        fail(f"{label} must not be group/world writable")
    require_current_user_owned(info, label)


def require_private_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    ensure_not_group_world_writable(info, label)
    return info


def optional_private_directory(path: Path, label: str) -> os.stat_result | None:
    info = lstat_optional(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    ensure_not_group_world_writable(info, label)
    return info


def optional_owner_private_directory(path: Path, label: str) -> os.stat_result | None:
    info = lstat_optional(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    require_current_user_owned(info, label)
    require_exact_mode(info, label, OWNER_DIR_MODE)
    return info


def require_owned_directory_modes(
    path: Path,
    label: str,
    allowed_modes: set[int],
) -> os.stat_result:
    info = require_directory(path, label)
    require_current_user_owned(info, label)
    mode = stat.S_IMODE(info.st_mode)
    if mode not in allowed_modes:
        expected = " or ".join(f"{item:04o}" for item in sorted(allowed_modes))
        fail(f"{label} must have mode {expected}, got {mode:04o}")
    return info


def optional_owned_directory_modes(
    path: Path,
    label: str,
    allowed_modes: set[int],
) -> os.stat_result | None:
    info = lstat_optional(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    require_current_user_owned(info, label)
    mode = stat.S_IMODE(info.st_mode)
    if mode not in allowed_modes:
        expected = " or ".join(f"{item:04o}" for item in sorted(allowed_modes))
        fail(f"{label} must have mode {expected}, got {mode:04o}")
    return info


def require_regular_stamp_if_present(path: Path, label: str) -> os.stat_result | None:
    info = lstat_optional(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    return info


def software_ancestor_paths(target: Path) -> tuple[tuple[Path, str], ...]:
    return (
        (target / ".nddev-runtime", "software runtime directory"),
        (software_parent(target), "software parent"),
    )


def software_root_presence(target: Path) -> str:
    if optional_owner_private_directory(target, "--target") is None:
        return "missing"
    if (
        optional_owner_private_directory(target / NDDEV_RUNTIME_DIR, "software runtime directory")
        is None
    ):
        return "absent"
    software_modes = {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE}
    if (
        optional_owned_directory_modes(software_parent(target), "software parent", software_modes)
        is None
    ):
        return "absent"
    if (
        optional_owned_directory_modes(software_root(target), "software root", software_modes)
        is None
    ):
        return "absent"
    return "present"


def scan_software_tree(root: Path, executable_relative: str) -> SoftwareTree:
    require_private_directory(root, "software root")
    executable_path = root / safe_relative_path(executable_relative)
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative == SOFTWARE_STAMP_NAME:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree must not contain symlinks: {relative}")
        ensure_not_group_world_writable(info, f"software path {relative}")
        if stat.S_ISREG(info.st_mode):
            files.append(path)
        elif not stat.S_ISDIR(info.st_mode):
            fail(f"software tree path must be regular file or directory: {relative}")
        if len(files) > SOFTWARE_TREE_MAX_FILES:
            fail(f"software tree exceeds the {SOFTWARE_TREE_MAX_FILES}-file limit")
    tree_hash = hashlib.sha256()
    byte_count = 0
    executable_digest: str | None = None
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        content, _ = read_regular_file(
            path,
            f"software file {relative}",
            owner_only=False,
            max_bytes=SOFTWARE_TREE_MAX_BYTES,
        )
        byte_count += len(content)
        if byte_count > SOFTWARE_TREE_MAX_BYTES:
            fail(f"software tree exceeds the {SOFTWARE_TREE_MAX_BYTES}-byte limit")
        digest = sha256_bytes(content)
        tree_hash.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\0")
        if path == executable_path:
            executable_digest = digest
    if executable_digest is None:
        fail("software executable is missing from tree")
    executable_info = require_regular_file(
        executable_path,
        f"software executable {executable_path}",
        owner_only=False,
    )
    if not stat.S_IMODE(executable_info.st_mode) & stat.S_IXUSR:
        fail("software executable must be owner-executable")
    return SoftwareTree(
        digest=tree_hash.hexdigest(),
        file_count=len(files),
        byte_count=byte_count,
        executable_sha256=executable_digest,
    )


def software_file_hardened_mode(path: Path, executable_path: Path, info: os.stat_result) -> int:
    if path == executable_path or stat.S_IMODE(info.st_mode) & stat.S_IXUSR:
        return SOFTWARE_IMMUTABLE_EXECUTABLE_MODE
    return SOFTWARE_IMMUTABLE_FILE_MODE


def harden_software_tree(
    root: Path,
    executable_relative: str,
    *,
    harden_root: bool = True,
) -> None:
    require_private_directory(root, "software root")
    executable_path = root / safe_relative_path(executable_relative)
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree must not contain symlinks: {relative}")
        require_current_user_owned(info, f"software path {relative}")
        if stat.S_ISDIR(info.st_mode):
            os.chmod(path, SOFTWARE_IMMUTABLE_DIR_MODE)
            continue
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                fail(f"software path must not have hard-link aliases: {relative}")
            os.chmod(path, software_file_hardened_mode(path, executable_path, info))
            continue
        fail(f"software tree path must be regular file or directory: {relative}")
    if harden_root:
        os.chmod(root, SOFTWARE_IMMUTABLE_DIR_MODE)
        require_owned_directory_modes(root, "software root", {SOFTWARE_IMMUTABLE_DIR_MODE})


def harden_installed_software(target: Path, executable_relative: str) -> None:
    harden_software_tree(software_root(target), executable_relative)
    os.chmod(software_parent(target), SOFTWARE_IMMUTABLE_DIR_MODE)
    require_owned_directory_modes(
        software_parent(target),
        "software parent",
        {SOFTWARE_IMMUTABLE_DIR_MODE},
    )


def make_software_tree_mutable(root: Path) -> None:
    info = lstat_optional(root)
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("software root must be a real directory")
    require_current_user_owned(info, "software root")
    os.chmod(root, OWNER_DIR_MODE)
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        child = path.lstat()
        if stat.S_ISLNK(child.st_mode):
            fail(f"software tree must not contain symlinks: {relative}")
        require_current_user_owned(child, f"software path {relative}")
        if stat.S_ISDIR(child.st_mode):
            os.chmod(path, OWNER_DIR_MODE)
        elif stat.S_ISREG(child.st_mode):
            if child.st_nlink != 1:
                fail(f"software path must not have hard-link aliases: {relative}")
            mode = OWNER_DIR_MODE if stat.S_IMODE(child.st_mode) & stat.S_IXUSR else OWNER_FILE_MODE
            os.chmod(path, mode)
        else:
            fail(f"software tree path must be regular file or directory: {relative}")


def make_software_parent_mutable(target: Path) -> None:
    parent = software_parent(target)
    info = lstat_optional(parent)
    if info is None:
        return
    require_owned_directory_modes(
        parent,
        "software parent",
        {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
    )
    os.chmod(parent, OWNER_DIR_MODE)
    require_owner_private_directory(parent, "software parent")


def snapshot_tree_modes(root: Path) -> dict[str, int]:
    require_directory(root, "software tree mode snapshot root")
    modes: dict[str, int] = {}
    for path in sorted(
        [root, *root.rglob("*")], key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = "." if path == root else path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree mode snapshot path must not be a symlink: {relative}")
        if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
            modes[relative] = stat.S_IMODE(info.st_mode)
            continue
        fail(f"software tree mode snapshot path is unsupported: {relative}")
    return modes


def restore_tree_modes(root: Path, modes: dict[str, int]) -> None:
    for relative, mode in sorted(
        modes.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        path = root if relative == "." else root / safe_relative_path(relative)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
        ):
            fail(f"software tree restore path is unsupported: {relative}")
        os.chmod(path, mode)


def restore_tree_manifest_metadata(
    root: Path,
    manifest: dict[str, TreeManifestEntry] | None,
) -> None:
    if manifest is None:
        return
    for relative, entry in sorted(
        manifest.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        path = root if relative == "." else root / safe_relative_path(relative)
        info = path.lstat()
        if info.st_ino != entry.inode:
            fail(f"software manifest path identity changed: {relative}")
        if entry.kind == "dir":
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"software manifest directory changed kind: {relative}")
        elif entry.kind == "file":
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                fail(f"software manifest file changed kind: {relative}")
        else:
            fail(f"software manifest entry kind is invalid: {relative}")
        os.chmod(path, entry.mode)
        refreshed = path.lstat()
        os.utime(path, ns=(refreshed.st_atime_ns, entry.mtime_ns), follow_symlinks=False)
        fsync_existing_path(path, directory=entry.kind == "dir")
        fsync_directory(path.parent)


def tree_relative(path: Path, root: Path) -> str:
    return "." if path == root else path.relative_to(root).as_posix()


def sorted_tree_paths(root: Path) -> list[Path]:
    return sorted([root, *root.rglob("*")], key=lambda item: tree_relative(item, root))


def snapshot_tree_exact(
    root: Path,
    *,
    allow_symlinks: bool = False,
) -> dict[str, TreeSnapshotEntry] | None:
    info = lstat_optional(root)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"snapshot root must not be a symlink: {root}")
    paths = sorted_tree_paths(root) if stat.S_ISDIR(info.st_mode) else [root]
    snapshot: dict[str, TreeSnapshotEntry] = {}
    total = 0
    for index, path in enumerate(paths, start=1):
        if index > BACKUP_TREE_MAX_FILES:
            fail(f"snapshot root has too many entries: {root}")
        relative = tree_relative(path, root)
        child = path.lstat()
        mode = stat.S_IMODE(child.st_mode)
        if stat.S_ISLNK(child.st_mode):
            if allow_symlinks:
                snapshot[relative] = TreeSnapshotEntry(
                    kind="symlink",
                    mode=mode,
                    content=None,
                    size=child.st_size,
                    sha256=None,
                    dev=child.st_dev,
                    inode=child.st_ino,
                    mtime_ns=child.st_mtime_ns,
                    link_target=os.readlink(path),
                )
                continue
            fail(f"snapshot path must not be a symlink: {relative}")
        if stat.S_ISDIR(child.st_mode):
            require_current_user_owned(child, f"snapshot directory {relative}")
            snapshot[relative] = TreeSnapshotEntry(
                kind="dir",
                mode=mode,
                content=None,
                size=child.st_size,
                sha256=None,
                dev=child.st_dev,
                inode=child.st_ino,
                mtime_ns=child.st_mtime_ns,
            )
            continue
        if stat.S_ISREG(child.st_mode):
            if child.st_nlink != 1:
                fail(f"snapshot file must not have hard-link aliases: {relative}")
            require_current_user_owned(child, f"snapshot file {relative}")
            total += child.st_size
            if total > MANAGED_PAYLOAD_MAX_BYTES:
                fail(f"snapshot root is too large: {root}")
            content = path.read_bytes()
            snapshot[relative] = TreeSnapshotEntry(
                kind="file",
                mode=mode,
                content=content,
                size=child.st_size,
                sha256=sha256_bytes(content),
                dev=child.st_dev,
                inode=child.st_ino,
                mtime_ns=child.st_mtime_ns,
            )
            continue
        fail(f"snapshot path must be a regular file or directory: {relative}")
    return snapshot


def snapshot_tree_manifest(
    root: Path,
    *,
    max_files: int = SOFTWARE_TREE_MAX_FILES,
    max_bytes: int = SOFTWARE_TREE_MAX_BYTES,
) -> dict[str, TreeManifestEntry] | None:
    info = lstat_optional(root)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"manifest root must not be a symlink: {root}")
    paths = sorted_tree_paths(root) if stat.S_ISDIR(info.st_mode) else [root]
    manifest: dict[str, TreeManifestEntry] = {}
    total = 0
    for index, path in enumerate(paths, start=1):
        if index > max_files:
            fail(f"manifest root has too many entries: {root}")
        relative = tree_relative(path, root)
        child = path.lstat()
        mode = stat.S_IMODE(child.st_mode)
        if stat.S_ISLNK(child.st_mode):
            fail(f"manifest path must not be a symlink: {relative}")
        if stat.S_ISDIR(child.st_mode):
            require_current_user_owned(child, f"manifest directory {relative}")
            manifest[relative] = TreeManifestEntry(
                kind="dir",
                mode=mode,
                size=None,
                sha256=None,
                inode=child.st_ino,
                mtime_ns=child.st_mtime_ns,
            )
            continue
        if stat.S_ISREG(child.st_mode):
            if child.st_nlink != 1:
                fail(f"manifest file must not have hard-link aliases: {relative}")
            require_current_user_owned(child, f"manifest file {relative}")
            total += child.st_size
            if total > max_bytes:
                fail(f"manifest root is too large: {root}")
            manifest[relative] = TreeManifestEntry(
                kind="file",
                mode=mode,
                size=child.st_size,
                sha256=digest_regular_file(
                    path,
                    f"manifest file {relative}",
                    owner_only=False,
                    max_bytes=max_bytes,
                )[0],
                inode=child.st_ino,
                mtime_ns=child.st_mtime_ns,
            )
            continue
        fail(f"manifest path must be a regular file or directory: {relative}")
    return manifest


def tree_matches_manifest(
    root: Path,
    manifest: dict[str, TreeManifestEntry] | None,
    *,
    max_bytes: int = SOFTWARE_TREE_MAX_BYTES,
) -> bool:
    if manifest is None:
        return lstat_optional(root) is None
    try:
        current = snapshot_tree_manifest(root, max_bytes=max_bytes)
    except ManagerError:
        return False
    return current == manifest


def make_private_tree_mutable(root: Path) -> None:
    info = lstat_optional(root)
    if info is None or not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return
    for path in sorted_tree_paths(root):
        child = path.lstat()
        if stat.S_ISLNK(child.st_mode):
            continue
        if stat.S_ISDIR(child.st_mode):
            with contextlib.suppress(OSError):
                os.chmod(path, OWNER_DIR_MODE)
        elif stat.S_ISREG(child.st_mode):
            with contextlib.suppress(OSError):
                os.chmod(path, OWNER_FILE_MODE)


def remove_tree_exact(root: Path) -> None:
    info = lstat_optional(root)
    if info is None:
        if lstat_optional(root.parent) is not None:
            fsync_directory(root.parent)
        return
    if stat.S_ISLNK(info.st_mode) or stat.S_ISREG(info.st_mode):
        root.unlink()
        fsync_directory(root.parent)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"tree root is unsupported: {root}")
    make_private_tree_mutable(root)
    shutil.rmtree(root)
    fsync_directory(root.parent)


def remove_tree_exact_retry(root: Path, label: str) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            remove_tree_exact(root)
        except BaseException as exc:
            last_error = exc
        if lstat_optional(root) is None:
            return
    raise ManagerError(f"{label} cleanup did not reach an absent postcondition") from last_error


def tree_matches_snapshot(root: Path, snapshot: dict[str, TreeSnapshotEntry] | None) -> bool:
    if snapshot is None:
        return lstat_optional(root) is None
    try:
        return snapshot_tree_exact(root) == snapshot
    except ManagerError:
        return False


def tree_snapshot_path(root: Path, relative: str) -> Path:
    return root if relative == "." else root / safe_relative_path(relative)


def fsync_existing_path(path: Path, *, directory: bool) -> None:
    flags = os.O_RDONLY
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot_directory_identity(path: Path, label: str) -> DirectorySnapshot:
    info = require_directory(path, label)
    return DirectorySnapshot(
        existed=True,
        mode=stat.S_IMODE(info.st_mode),
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
    )


def directory_identity_matches(path: Path, expected: DirectorySnapshot) -> bool:
    try:
        info = lstat_optional(path)
        if not expected.existed:
            return info is None
        return (
            info is not None
            and not stat.S_ISLNK(info.st_mode)
            and stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == expected.mode
            and info.st_ino == expected.inode
            and info.st_mtime_ns == expected.mtime_ns
        )
    except ManagerError:
        return False


def restore_directory_identity(path: Path, expected: DirectorySnapshot, label: str) -> None:
    if not expected.existed:
        if lstat_optional(path) is not None:
            remove_tree_exact(path)
        return
    info = require_directory(path, label)
    if info.st_ino != expected.inode:
        fail(f"{label} identity changed")
    if expected.mode is None or expected.mtime_ns is None:
        fail(f"{label} snapshot is invalid")
    if stat.S_IMODE(info.st_mode) != expected.mode or info.st_mtime_ns != expected.mtime_ns:
        require_current_user_owned(info, label)
        os.chmod(path, expected.mode)
        refreshed = path.lstat()
        os.utime(path, ns=(refreshed.st_atime_ns, expected.mtime_ns), follow_symlinks=False)
    fsync_existing_path(path, directory=True)
    fsync_directory(path.parent)


def restore_tree_entry_metadata(path: Path, entry: TreeSnapshotEntry) -> None:
    if entry.kind == "symlink":
        refreshed = path.lstat()
        os.utime(path, ns=(refreshed.st_atime_ns, entry.mtime_ns), follow_symlinks=False)
        fsync_directory(path.parent)
        return
    os.chmod(path, entry.mode)
    refreshed = path.lstat()
    os.utime(path, ns=(refreshed.st_atime_ns, entry.mtime_ns), follow_symlinks=False)
    fsync_existing_path(path, directory=entry.kind == "dir")
    fsync_directory(path.parent)


def rewrite_tree_snapshot_file(path: Path, entry: TreeSnapshotEntry, relative: str) -> None:
    if entry.content is None:
        fail(f"tree snapshot file has no content: {relative}")
    os.chmod(path, OWNER_FILE_MODE)
    descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC)
    try:
        write_complete(descriptor, entry.content, f"tree restore {relative}")
        os.fchmod(descriptor, entry.mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    refreshed = path.lstat()
    os.utime(path, ns=(refreshed.st_atime_ns, entry.mtime_ns), follow_symlinks=False)
    fsync_existing_path(path, directory=False)
    fsync_directory(path.parent)


def restore_tree_snapshot_entry(root: Path, relative: str, entry: TreeSnapshotEntry) -> None:
    path = tree_snapshot_path(root, relative)
    info = lstat_optional(path)
    if info is None:
        fail(f"tree snapshot object is missing: {relative}")
    if identity_of(info) != (entry.dev, entry.inode):
        fail(f"tree snapshot object identity changed: {relative}")
    if entry.kind == "dir":
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"tree snapshot directory changed kind: {relative}")
        restore_tree_entry_metadata(path, entry)
        return
    if entry.kind == "file":
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail(f"tree snapshot file changed kind: {relative}")
        current_content = path.read_bytes()
        if len(current_content) != entry.size or sha256_bytes(current_content) != entry.sha256:
            rewrite_tree_snapshot_file(path, entry, relative)
            return
        restore_tree_entry_metadata(path, entry)
        return
    if entry.kind == "symlink":
        if not stat.S_ISLNK(info.st_mode):
            fail(f"tree snapshot symlink changed kind: {relative}")
        if os.readlink(path) != entry.link_target:
            fail(f"tree snapshot symlink target changed: {relative}")
        restore_tree_entry_metadata(path, entry)
        return
    fail(f"tree snapshot entry kind is invalid: {relative}")


def restore_tree_exact(root: Path, snapshot: dict[str, TreeSnapshotEntry] | None) -> None:
    if snapshot is None:
        remove_tree_exact(root)
        return
    root_entry = snapshot.get(".")
    if root_entry is None or root_entry.kind != "dir":
        fail("tree snapshot root is invalid")
    root_info = lstat_optional(root)
    if root_info is None:
        fail(f"tree snapshot root is missing: {root}")
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        fail(f"tree snapshot root must still be a real directory: {root}")
    expected_paths = set(snapshot)
    for path in sorted_tree_paths(root)[::-1]:
        relative = tree_relative(path, root)
        if relative in expected_paths:
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            remove_tree_exact(path)
        elif stat.S_ISREG(info.st_mode):
            path.unlink()
            fsync_directory(path.parent)
        else:
            fail(f"tree restore found unsupported residue: {relative}")
    for relative, entry in sorted(
        snapshot.items(),
        key=lambda item: (len(Path(item[0]).parts), item[0]),
    ):
        restore_tree_snapshot_entry(root, relative, entry)
    for relative, entry in sorted(
        snapshot.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        if entry.kind == "dir":
            restore_tree_entry_metadata(tree_snapshot_path(root, relative), entry)
    fsync_directory(root.parent)


def restore_tree_exact_retry(
    root: Path,
    snapshot: dict[str, TreeSnapshotEntry] | None,
    label: str,
) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            restore_tree_exact(root, snapshot)
        except BaseException as exc:
            last_error = exc
        if tree_matches_snapshot(root, snapshot):
            return
    raise ManagerError(f"{label} rollback did not restore exact pre-state") from last_error


def cleanup_transaction_tree(path: Path, label: str) -> None:
    remove_tree_exact_retry(path, label)


def cleanup_pending_parent(target: Path) -> Path:
    return target / CLEANUP_PENDING_RUNTIME_DIR


def cleanup_intent_path(target: Path) -> Path:
    return cleanup_pending_parent(target) / CLEANUP_INTENT_NAME


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_pending_parent(target) / CLEANUP_JOURNAL_NAME


def cleanup_tombstone_path(target: Path) -> Path:
    return cleanup_pending_parent(target) / CLEANUP_TOMBSTONE_NAME


def cleanup_intent_alias_prefix(intent: Path) -> str:
    return f".{intent.name}."


def cleanup_journal_alias_prefix(journal: Path) -> str:
    return f".{journal.name}."


def cleanup_metadata_alias_prefix(final: Path) -> str:
    if final.name == CLEANUP_INTENT_NAME:
        return cleanup_intent_alias_prefix(final)
    if final.name == CLEANUP_JOURNAL_NAME:
        return cleanup_journal_alias_prefix(final)
    fail("cleanup metadata final path is invalid")


def cleanup_entry_path(tombstone: Path, relative: str) -> Path:
    return tombstone if relative == "." else tombstone / safe_relative_path(relative)


def cleanup_source_parent_payload(path: Path, label: str) -> dict[str, int]:
    info = require_directory(path, label)
    require_current_user_owned(info, label)
    return {
        "uid": owner_of(info),
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "dev": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def validate_cleanup_parent_payload(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != CLEANUP_INTENT_PARENT_KEYS:
        fail(f"{label} cleanup source parent has invalid keys")
    result: dict[str, int] = {}
    for key in CLEANUP_INTENT_PARENT_KEYS:
        item = value[key]
        if not isinstance(item, int) or item < 0:
            fail(f"{label} cleanup source parent {key} is invalid")
        result[key] = item
    return result


def cleanup_parent_stable_identity_matches(path: Path, payload: Mapping[str, int]) -> bool:
    info = lstat_optional(path)
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    return (
        owner_of(info) == payload["uid"]
        and stat.S_IMODE(info.st_mode) == payload["mode"]
        and info.st_dev == payload["dev"]
        and info.st_ino == payload["inode"]
    )


def cleanup_parent_exact_identity_matches(path: Path, payload: Mapping[str, int]) -> bool:
    info = lstat_optional(path)
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    return cleanup_parent_stable_identity_matches(path, payload) and (
        info.st_nlink == payload["nlink"]
        and info.st_size == payload["size"]
        and info.st_mtime_ns == payload["mtime_ns"]
    )


def cleanup_source_name_pattern(target: Path, source_kind: str) -> re.Pattern[str]:
    escaped_target = re.escape(target.name)
    if source_kind == "managed-rollback-retirement":
        return re.compile(rf"\A\.{escaped_target}\.nddev-kiro-cli-setup-rollback-[A-Za-z0-9_]+\Z")
    if source_kind == "software-rollback-retirement":
        return re.compile(
            rf"\A\.{escaped_target}\.nddev-kiro-cli-software-rollback-[A-Za-z0-9_]+\Z"
        )
    if source_kind == "software-stage-retirement":
        return re.compile(rf"\A\.{escaped_target}\.nddev-kiro-cli-software-stage-[A-Za-z0-9_]+\Z")
    if source_kind == "backup-slot-retirement":
        return re.compile(r"\A\.[0-9]+\.rollback\.[A-Za-z0-9_]+\Z")
    fail("cleanup retirement kind is invalid")


def cleanup_source_anchor(target: Path, source: Path, source_kind: str) -> tuple[str, Path]:
    if source.parent == target.parent and source_kind in {
        "managed-rollback-retirement",
        "software-rollback-retirement",
        "software-stage-retirement",
    }:
        return "target-parent", target.parent
    if source.parent == backup_pool(target) and source_kind == "backup-slot-retirement":
        return "backup-pool", backup_pool(target)
    fail("cleanup source parent is outside the declared manager anchors")


def cleanup_anchor_parent(target: Path, anchor: str) -> Path:
    if anchor == "target-parent":
        return target.parent
    if anchor == "backup-pool":
        return backup_pool(target)
    fail("cleanup source anchor is invalid")


def validate_cleanup_source_name(target: Path, source_name: str, source_kind: str) -> None:
    if "/" in source_name or source_name in {"", ".", ".."}:
        fail("cleanup source name is invalid")
    if not cleanup_source_name_pattern(target, source_kind).fullmatch(source_name):
        fail("cleanup source name is not a declared manager-generated name")


def cleanup_destination_relative(source_kind: str, index: int) -> str:
    return cleanup_retirement_name(source_kind, index)


def cleanup_entry_from_path(path: Path, tombstone: Path, total: list[int]) -> CleanupJournalEntry:
    relative = tree_relative(path, tombstone)
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    uid = owner_of(info)
    if stat.S_ISLNK(info.st_mode):
        fail(f"cleanup tombstone must not contain symlinks: {relative}")
    if stat.S_ISDIR(info.st_mode):
        require_current_user_owned(info, f"cleanup tombstone directory {relative}")
        return CleanupJournalEntry(
            relative=relative,
            kind="dir",
            uid=uid,
            mode=mode,
            nlink=info.st_nlink,
            dev=info.st_dev,
            inode=info.st_ino,
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            sha256=None,
        )
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            fail(f"cleanup tombstone file must not have hard-link aliases: {relative}")
        require_current_user_owned(info, f"cleanup tombstone file {relative}")
        total[0] += info.st_size
        if total[0] > CLEANUP_TOMBSTONE_MAX_BYTES:
            fail("cleanup tombstone exceeds the byte bound")
        digest, refreshed = digest_regular_file(
            path,
            f"cleanup tombstone file {relative}",
            owner_only=False,
            max_bytes=CLEANUP_TOMBSTONE_MAX_BYTES,
        )
        return CleanupJournalEntry(
            relative=relative,
            kind="file",
            uid=uid,
            mode=mode,
            nlink=refreshed.st_nlink,
            dev=refreshed.st_dev,
            inode=refreshed.st_ino,
            size=refreshed.st_size,
            mtime_ns=refreshed.st_mtime_ns,
            sha256=digest,
        )
    fail(f"cleanup tombstone path must be a regular file or directory: {relative}")


def snapshot_cleanup_tree(root: Path, label: str) -> dict[str, CleanupJournalEntry]:
    info = require_directory(root, label)
    require_current_user_owned(info, label)
    paths = sorted_tree_paths(root)
    if len(paths) > CLEANUP_TOMBSTONE_MAX_FILES:
        fail(f"{label} exceeds the object bound")
    total = [0]
    entries = {
        tree_relative(path, root): cleanup_entry_from_path(path, root, total) for path in paths
    }
    if "." not in entries:
        fail(f"{label} root is missing")
    return entries


def snapshot_cleanup_tombstone(tombstone: Path) -> dict[str, CleanupJournalEntry]:
    return snapshot_cleanup_tree(tombstone, "cleanup tombstone")


def cleanup_entries_for_destination(
    source_entries: Mapping[str, CleanupJournalEntry],
    destination_relative: str,
) -> dict[str, CleanupJournalEntry]:
    transformed: dict[str, CleanupJournalEntry] = {}
    safe_relative_path(destination_relative)
    for relative, entry in source_entries.items():
        if relative == ".":
            target_relative = destination_relative
        else:
            target_relative = f"{destination_relative}/{relative}"
        transformed[target_relative] = replace(entry, relative=target_relative)
    return transformed


def cleanup_entries_match_root(
    root: Path,
    entries: Mapping[str, CleanupJournalEntry],
    *,
    allow_directory_drain_drift: bool,
) -> bool:
    try:
        actual_paths = {tree_relative(path, root): path for path in sorted_tree_paths(root)}
    except (FileNotFoundError, NotADirectoryError, ManagerError):
        return False
    if set(actual_paths) != set(entries):
        return False
    for relative, entry in entries.items():
        if not cleanup_entry_matches_path(
            actual_paths[relative],
            entry,
            allow_directory_drain_drift=allow_directory_drain_drift,
        ):
            return False
    return True


def cleanup_entry_to_json(entry: CleanupJournalEntry) -> dict[str, Any]:
    return {
        "relative": entry.relative,
        "kind": entry.kind,
        "uid": entry.uid,
        "mode": entry.mode,
        "nlink": entry.nlink,
        "dev": entry.dev,
        "inode": entry.inode,
        "size": entry.size,
        "mtime_ns": entry.mtime_ns,
        "sha256": entry.sha256,
    }


def cleanup_entry_from_json(item: Any, label: str) -> CleanupJournalEntry:
    if not isinstance(item, dict) or set(item) != CLEANUP_JOURNAL_OBJECT_KEYS:
        fail(f"{label} cleanup object has invalid keys")
    relative = item["relative"]
    if not isinstance(relative, str):
        fail(f"{label} cleanup object relative path is invalid")
    if relative != ".":
        safe_relative_path(relative)
    kind = item["kind"]
    if kind not in {"dir", "file"}:
        fail(f"{label} cleanup object kind is invalid")
    uid = item["uid"]
    if uid is not None and (not isinstance(uid, int) or uid < 0):
        fail(f"{label} cleanup object uid is invalid")
    int_fields = ("mode", "nlink", "dev", "inode", "size", "mtime_ns")
    for field in int_fields:
        if not isinstance(item[field], int) or item[field] < 0:
            fail(f"{label} cleanup object {field} is invalid")
    digest = item["sha256"]
    if kind == "dir":
        if digest is not None:
            fail(f"{label} cleanup directory digest must be null")
    elif not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        fail(f"{label} cleanup file digest is invalid")
    return CleanupJournalEntry(
        relative=relative,
        kind=kind,
        uid=uid,
        mode=item["mode"],
        nlink=item["nlink"],
        dev=item["dev"],
        inode=item["inode"],
        size=item["size"],
        mtime_ns=item["mtime_ns"],
        sha256=digest,
    )


def cleanup_journal_payload(
    target: Path,
    kind: str,
    objects: dict[str, CleanupJournalEntry],
) -> dict[str, Any]:
    byte_count = sum(entry.size for entry in objects.values() if entry.kind == "file")
    return {
        "schema_version": CLEANUP_JOURNAL_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
        "cleanup_parent": CLEANUP_PENDING_RUNTIME_DIR,
        "journal_name": CLEANUP_JOURNAL_NAME,
        "tombstone_name": CLEANUP_TOMBSTONE_NAME,
        "kind": kind,
        "bounds": {
            "max_files": CLEANUP_TOMBSTONE_MAX_FILES,
            "max_bytes": CLEANUP_TOMBSTONE_MAX_BYTES,
        },
        "object_count": len(objects),
        "byte_count": byte_count,
        "objects": [
            cleanup_entry_to_json(objects[relative])
            for relative in sorted(objects, key=lambda item: (len(Path(item).parts), item))
        ],
    }


def cleanup_intent_payload(
    target: Path,
    kind: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_INTENT_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
        "cleanup_parent": CLEANUP_PENDING_RUNTIME_DIR,
        "intent_name": CLEANUP_INTENT_NAME,
        "journal_name": CLEANUP_JOURNAL_NAME,
        "tombstone_name": CLEANUP_TOMBSTONE_NAME,
        "kind": kind,
        "bounds": {
            "max_files": CLEANUP_TOMBSTONE_MAX_FILES,
            "max_bytes": CLEANUP_TOMBSTONE_MAX_BYTES,
        },
        "source_count": len(sources),
        "sources": sources,
    }


def cleanup_source_to_json(
    *,
    target: Path,
    source: Path,
    source_kind: str,
    index: int,
    entries: Mapping[str, CleanupJournalEntry],
) -> dict[str, Any]:
    anchor, parent = cleanup_source_anchor(target, source, source_kind)
    validate_cleanup_source_name(target, source.name, source_kind)
    return {
        "index": index,
        "source_kind": source_kind,
        "source_anchor": anchor,
        "source_name": source.name,
        "source_parent": cleanup_source_parent_payload(parent, "cleanup source parent"),
        "destination_relative": cleanup_destination_relative(source_kind, index),
        "objects": [
            cleanup_entry_to_json(entries[relative])
            for relative in sorted(entries, key=lambda item: (len(Path(item).parts), item))
        ],
    }


def cleanup_kind_for_retirements(retirements: list[tuple[Path, str]]) -> str:
    return retirements[0][1] if len(retirements) == 1 else "multi-retirement"


def cleanup_intent_source_entries(
    item: Mapping[str, Any], label: str
) -> dict[str, CleanupJournalEntry]:
    objects_value = item["objects"]
    if not isinstance(objects_value, list):
        fail(f"{label} cleanup source objects are invalid")
    entries: dict[str, CleanupJournalEntry] = {}
    for object_item in objects_value:
        entry = cleanup_entry_from_json(object_item, label)
        if entry.relative in entries:
            fail(f"{label} cleanup source contains duplicate object: {entry.relative}")
        entries[entry.relative] = entry
    if "." not in entries:
        fail(f"{label} cleanup source does not bind its root")
    return entries


def cleanup_intent_sources_from_payload(
    target: Path,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sources_value = payload["sources"]
    source_count = payload["source_count"]
    if not isinstance(sources_value, list) or not isinstance(source_count, int):
        fail("cleanup intent source list is invalid")
    if source_count != len(sources_value) or source_count < 1 or source_count > 4:
        fail("cleanup intent source count is invalid")
    sources: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    seen_destinations: set[str] = set()
    for raw in sources_value:
        if not isinstance(raw, dict) or set(raw) != CLEANUP_INTENT_SOURCE_KEYS:
            fail("cleanup intent source has invalid keys")
        index = raw["index"]
        if (
            not isinstance(index, int)
            or index < 0
            or index >= source_count
            or index in seen_indexes
        ):
            fail("cleanup intent source index is invalid")
        seen_indexes.add(index)
        source_kind = raw["source_kind"]
        if source_kind not in {
            "managed-rollback-retirement",
            "backup-slot-retirement",
            "software-rollback-retirement",
            "software-stage-retirement",
        }:
            fail("cleanup intent source kind is invalid")
        source_anchor = raw["source_anchor"]
        if source_anchor not in {"target-parent", "backup-pool"}:
            fail("cleanup intent source anchor is invalid")
        source_name = raw["source_name"]
        if not isinstance(source_name, str):
            fail("cleanup intent source name is invalid")
        validate_cleanup_source_name(target, source_name, source_kind)
        source_parent = validate_cleanup_parent_payload(
            raw["source_parent"],
            "cleanup intent",
        )
        destination_relative = raw["destination_relative"]
        if not isinstance(destination_relative, str):
            fail("cleanup intent destination is invalid")
        safe_relative_path(destination_relative)
        if destination_relative != cleanup_destination_relative(source_kind, index):
            fail("cleanup intent destination does not match the source kind")
        if destination_relative in seen_destinations:
            fail("cleanup intent contains duplicate destination")
        seen_destinations.add(destination_relative)
        entries = cleanup_intent_source_entries(raw, "cleanup intent")
        source_parent_path = cleanup_anchor_parent(target, source_anchor)
        if not cleanup_parent_stable_identity_matches(source_parent_path, source_parent):
            fail("cleanup intent source parent identity changed")
        sources.append(
            {
                "index": index,
                "source_kind": source_kind,
                "source_anchor": source_anchor,
                "source_name": source_name,
                "source_parent": source_parent,
                "destination_relative": destination_relative,
                "objects": entries,
            }
        )
    sources.sort(key=lambda item: item["index"])
    if [source["index"] for source in sources] != list(range(source_count)):
        fail("cleanup intent source indexes are not contiguous")
    return sources


def validate_cleanup_intent_payload(
    target: Path,
    payload: Any,
) -> tuple[str, list[dict[str, Any]], dict[str, CleanupJournalEntry], bytes]:
    if not isinstance(payload, dict) or set(payload) != CLEANUP_INTENT_KEYS:
        fail("cleanup intent has invalid keys")
    if (
        payload["schema_version"] != CLEANUP_INTENT_SCHEMA
        or payload["product_name"] != PRODUCT_NAME
    ):
        fail("cleanup intent identity or schema is invalid")
    if payload["build_version"] != VERSION or payload["canonical_target"] != str(target):
        fail("cleanup intent target or build binding is invalid")
    if payload["cleanup_parent"] != CLEANUP_PENDING_RUNTIME_DIR:
        fail("cleanup intent parent binding is invalid")
    if payload["intent_name"] != CLEANUP_INTENT_NAME:
        fail("cleanup intent name binding is invalid")
    if payload["journal_name"] != CLEANUP_JOURNAL_NAME:
        fail("cleanup intent journal binding is invalid")
    if payload["tombstone_name"] != CLEANUP_TOMBSTONE_NAME:
        fail("cleanup intent tombstone binding is invalid")
    kind = payload["kind"]
    if kind not in {
        "managed-rollback-retirement",
        "backup-slot-retirement",
        "software-rollback-retirement",
        "software-stage-retirement",
        "multi-retirement",
    }:
        fail("cleanup intent kind is invalid")
    bounds = payload["bounds"]
    if not isinstance(bounds, dict) or set(bounds) != CLEANUP_JOURNAL_BOUNDS_KEYS:
        fail("cleanup intent bounds are invalid")
    if (
        bounds["max_files"] != CLEANUP_TOMBSTONE_MAX_FILES
        or bounds["max_bytes"] != CLEANUP_TOMBSTONE_MAX_BYTES
    ):
        fail("cleanup intent bounds do not match the contract")
    sources = cleanup_intent_sources_from_payload(target, payload)
    journal_objects: dict[str, CleanupJournalEntry] = {}
    tombstone = cleanup_tombstone_path(target)
    if lstat_optional(tombstone) is not None:
        total = [0]
        journal_objects["."] = cleanup_entry_from_path(tombstone, tombstone, total)
    for source in sources:
        transformed = cleanup_entries_for_destination(
            source["objects"],
            source["destination_relative"],
        )
        overlap = set(journal_objects) & set(transformed)
        if overlap:
            fail(f"cleanup intent destination objects overlap: {sorted(overlap)}")
        journal_objects.update(transformed)
    journal_content = canonical_json(cleanup_journal_payload(target, kind, journal_objects))
    if len(journal_content) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds the byte bound")
    return kind, sources, journal_objects, journal_content


def cleanup_declared_children(objects: dict[str, CleanupJournalEntry]) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for relative in objects:
        if relative == ".":
            continue
        parent = Path(relative).parent.as_posix()
        if parent == "":
            parent = "."
        children.setdefault(parent, set()).add(Path(relative).name)
    return children


def cleanup_entry_matches_path(
    path: Path,
    entry: CleanupJournalEntry,
    *,
    allow_directory_drain_drift: bool = False,
) -> bool:
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    if identity_of(info) != (entry.dev, entry.inode):
        return False
    if owner_of(info) != entry.uid:
        return False
    if stat.S_IMODE(info.st_mode) != entry.mode:
        return False
    if entry.kind == "dir":
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return False
        return allow_directory_drain_drift or (
            info.st_nlink == entry.nlink
            and info.st_size == entry.size
            and info.st_mtime_ns == entry.mtime_ns
        )
    if info.st_nlink != entry.nlink or info.st_size != entry.size:
        return False
    if info.st_mtime_ns != entry.mtime_ns:
        return False
    if entry.kind != "file" or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    try:
        digest, refreshed = digest_regular_file(
            path,
            f"cleanup tombstone file {entry.relative}",
            owner_only=False,
            max_bytes=CLEANUP_TOMBSTONE_MAX_BYTES,
        )
    except ManagerError:
        return False
    return identity_of(refreshed) == (entry.dev, entry.inode) and digest == entry.sha256


def path_child_names(path: Path) -> set[str]:
    info = lstat_optional(path)
    if info is None:
        return set()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"cleanup tombstone directory changed kind: {path}")
    return {child.name for child in path.iterdir()}


def remaining_declared_child_names(
    state: CleanupPendingState,
    relative: str,
) -> set[str]:
    expected: set[str] = set()
    for name in state.children.get(relative, set()):
        child_relative = name if relative == "." else f"{relative}/{name}"
        if lstat_optional(cleanup_entry_path(state.tombstone, child_relative)) is not None:
            expected.add(name)
    return expected


def validate_cleanup_directory_for_drain(
    state: CleanupPendingState,
    entry: CleanupJournalEntry,
) -> None:
    path = cleanup_entry_path(state.tombstone, entry.relative)
    info = lstat_optional(path)
    if info is None:
        return
    if not cleanup_entry_matches_path(path, entry, allow_directory_drain_drift=True):
        fail(f"cleanup tombstone directory identity changed: {entry.relative}")
    actual_children = path_child_names(path)
    expected_children = remaining_declared_child_names(state, entry.relative)
    if actual_children != expected_children:
        fail(f"cleanup tombstone directory child set changed: {entry.relative}")


def read_cleanup_journal_file(
    journal: Path,
    *,
    allow_publication_alias: bool,
) -> tuple[bytes, os.stat_result, Path | None]:
    try:
        before = journal.lstat()
    except FileNotFoundError:
        fail("cleanup journal is missing")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        fail("cleanup journal must be a regular non-symlink file")
    require_current_user_owned(before, "cleanup journal")
    require_exact_mode(before, "cleanup journal", OWNER_FILE_MODE)
    if before.st_size > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds the byte bound")
    alias: Path | None = None
    if before.st_nlink == 2:
        if not allow_publication_alias:
            fail("cleanup journal publication is incomplete")
        alias = find_cleanup_journal_publication_alias(journal, before)
    elif before.st_nlink != 1:
        fail("cleanup journal has an unsupported link count")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(journal, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange("cleanup journal changed while it was opened")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > CLEANUP_JOURNAL_MAX_BYTES:
                fail("cleanup journal exceeds the byte bound")
            blocks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = journal.lstat()
    if identity_of(final) != identity_of(before) or identity_of(after) != identity_of(before):
        raise ConcurrentTargetChange("cleanup journal changed while it was read")
    return b"".join(blocks), final, alias


def find_cleanup_journal_publication_alias(journal: Path, info: os.stat_result) -> Path:
    prefix = cleanup_journal_alias_prefix(journal)
    matches: list[Path] = []
    scanned = 0
    for path in journal.parent.iterdir():
        if not path.name.startswith(prefix):
            continue
        scanned += 1
        if scanned > CLEANUP_JOURNAL_ALIAS_SCAN_MAX:
            fail("cleanup journal has too many publication aliases")
        alias_info = path.lstat()
        if stat.S_ISLNK(alias_info.st_mode) or not stat.S_ISREG(alias_info.st_mode):
            fail("cleanup journal publication alias is invalid")
        if identity_of(alias_info) != identity_of(info):
            fail("cleanup journal publication alias does not match the final journal")
        matches.append(path)
    if len(matches) != 1:
        fail("cleanup journal hard-link alias state is invalid")
    return matches[0]


def cleanup_unpublished_metadata_aliases(final: Path) -> list[Path]:
    if lstat_optional(final) is not None:
        return []
    parent = final.parent
    if not parent.exists() or parent.is_symlink():
        return []
    prefix = cleanup_metadata_alias_prefix(final)
    matches: list[Path] = []
    scanned = 0
    for path in parent.iterdir():
        if not path.name.startswith(prefix):
            continue
        scanned += 1
        if scanned > CLEANUP_JOURNAL_ALIAS_SCAN_MAX:
            fail("cleanup metadata has too many temporary aliases")
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail("cleanup metadata temporary alias is invalid")
        require_current_user_owned(info, "cleanup metadata temporary alias")
        if info.st_nlink != 1:
            fail("cleanup metadata temporary alias has an unsupported link count")
        matches.append(path)
    return sorted(matches)


def remove_unpublished_cleanup_metadata_alias(alias: Path) -> None:
    info = alias.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail("cleanup metadata temporary alias is invalid")
    require_current_user_owned(info, "cleanup metadata temporary alias")
    if info.st_nlink != 1:
        fail("cleanup metadata temporary alias has an unsupported link count")
    alias.unlink()
    fsync_directory(alias.parent)


def find_cleanup_intent_publication_alias(intent: Path, info: os.stat_result) -> Path:
    prefix = cleanup_intent_alias_prefix(intent)
    matches: list[Path] = []
    scanned = 0
    for path in intent.parent.iterdir():
        if not path.name.startswith(prefix):
            continue
        scanned += 1
        if scanned > CLEANUP_JOURNAL_ALIAS_SCAN_MAX:
            fail("cleanup intent has too many publication aliases")
        alias_info = path.lstat()
        if stat.S_ISLNK(alias_info.st_mode) or not stat.S_ISREG(alias_info.st_mode):
            fail("cleanup intent publication alias is invalid")
        if identity_of(alias_info) != identity_of(info):
            fail("cleanup intent publication alias does not match the final intent")
        matches.append(path)
    if len(matches) != 1:
        fail("cleanup intent hard-link alias state is invalid")
    return matches[0]


def read_cleanup_intent_file(
    intent: Path,
    *,
    allow_publication_alias: bool,
) -> tuple[bytes, os.stat_result, Path | None]:
    try:
        before = intent.lstat()
    except FileNotFoundError:
        fail("cleanup intent is missing")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        fail("cleanup intent must be a regular non-symlink file")
    require_current_user_owned(before, "cleanup intent")
    require_exact_mode(before, "cleanup intent", OWNER_FILE_MODE)
    if before.st_size > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent exceeds the byte bound")
    alias: Path | None = None
    if before.st_nlink == 2:
        if not allow_publication_alias:
            fail("cleanup intent publication is incomplete")
        alias = find_cleanup_intent_publication_alias(intent, before)
    elif before.st_nlink != 1:
        fail("cleanup intent has an unsupported link count")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(intent, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange("cleanup intent changed while it was opened")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > CLEANUP_INTENT_MAX_BYTES:
                fail("cleanup intent exceeds the byte bound")
            blocks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = intent.lstat()
    if identity_of(final) != identity_of(before) or identity_of(after) != identity_of(before):
        raise ConcurrentTargetChange("cleanup intent changed while it was read")
    return b"".join(blocks), final, alias


def validate_cleanup_intent_state(
    target: Path,
    *,
    allow_publication_alias: bool,
) -> tuple[dict[str, Any], Path | None, bytes] | None:
    intent = cleanup_intent_path(target)
    if lstat_optional(intent) is None:
        return None
    content, _intent_stat, alias = read_cleanup_intent_file(
        intent,
        allow_publication_alias=allow_publication_alias,
    )
    payload = parse_json_object(content, "cleanup intent")
    _kind, _sources, _objects, journal_content = validate_cleanup_intent_payload(target, payload)
    return payload, alias, journal_content


def validate_cleanup_pending_state(
    target: Path,
    *,
    allow_publication_alias: bool = False,
) -> CleanupPendingState | None:
    parent = cleanup_pending_parent(target)
    parent_info = lstat_optional(parent)
    if parent_info is None:
        return None
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        fail("cleanup pending parent must be a real directory")
    require_current_user_owned(parent_info, "cleanup pending parent")
    require_exact_mode(parent_info, "cleanup pending parent", OWNER_DIR_MODE)
    journal = cleanup_journal_path(target)
    intent = cleanup_intent_path(target)
    tombstone = cleanup_tombstone_path(target)
    journal_info = lstat_optional(journal)
    intent_info = lstat_optional(intent)
    entries = sorted(parent.iterdir())
    if journal_info is None:
        if intent_info is not None:
            validate_cleanup_intent_state(
                target,
                allow_publication_alias=allow_publication_alias,
            )
            fail("cleanup transition is incomplete")
        if entries:
            fail("cleanup pending parent contains unjournaled state")
        fail("cleanup pending parent exists without a cleanup journal")
    content, _journal_stat, alias = read_cleanup_journal_file(
        journal,
        allow_publication_alias=allow_publication_alias,
    )
    allowed = {journal.name}
    if lstat_optional(tombstone) is not None:
        allowed.add(tombstone.name)
    if alias is not None:
        allowed.add(alias.name)
    intent_alias: Path | None = None
    if intent_info is not None:
        intent_state = validate_cleanup_intent_state(
            target,
            allow_publication_alias=allow_publication_alias,
        )
        if intent_state is None:
            fail("cleanup intent disappeared during validation")
        _intent_payload, intent_alias, expected_journal_content = intent_state
        if expected_journal_content != content:
            fail("cleanup intent and journal disagree")
        allowed.add(intent.name)
        if intent_alias is not None:
            allowed.add(intent_alias.name)
    for path in entries:
        if path.name not in allowed:
            fail(f"cleanup pending parent contains unknown path: {path.name}")
    payload = parse_json_object(content, "cleanup journal")
    if set(payload) != CLEANUP_JOURNAL_KEYS:
        fail("cleanup journal has invalid keys")
    if (
        payload["schema_version"] != CLEANUP_JOURNAL_SCHEMA
        or payload["product_name"] != PRODUCT_NAME
    ):
        fail("cleanup journal identity or schema is invalid")
    if payload["build_version"] != VERSION or payload["canonical_target"] != str(target):
        fail("cleanup journal target or build binding is invalid")
    if payload["cleanup_parent"] != CLEANUP_PENDING_RUNTIME_DIR:
        fail("cleanup journal parent binding is invalid")
    if payload["journal_name"] != CLEANUP_JOURNAL_NAME:
        fail("cleanup journal name binding is invalid")
    if payload["tombstone_name"] != CLEANUP_TOMBSTONE_NAME:
        fail("cleanup tombstone name binding is invalid")
    kind = payload["kind"]
    if kind not in {
        "managed-rollback-retirement",
        "backup-slot-retirement",
        "software-rollback-retirement",
        "software-stage-retirement",
        "multi-retirement",
    }:
        fail("cleanup journal kind is invalid")
    bounds = payload["bounds"]
    if not isinstance(bounds, dict) or set(bounds) != CLEANUP_JOURNAL_BOUNDS_KEYS:
        fail("cleanup journal bounds are invalid")
    if (
        bounds["max_files"] != CLEANUP_TOMBSTONE_MAX_FILES
        or bounds["max_bytes"] != CLEANUP_TOMBSTONE_MAX_BYTES
    ):
        fail("cleanup journal bounds do not match the contract")
    objects_value = payload["objects"]
    object_count = payload["object_count"]
    byte_count = payload["byte_count"]
    if not isinstance(objects_value, list) or not isinstance(object_count, int):
        fail("cleanup journal object list is invalid")
    if not isinstance(byte_count, int) or byte_count < 0:
        fail("cleanup journal byte count is invalid")
    if object_count != len(objects_value) or object_count > CLEANUP_TOMBSTONE_MAX_FILES:
        fail("cleanup journal object count is invalid")
    objects: dict[str, CleanupJournalEntry] = {}
    for item in objects_value:
        entry = cleanup_entry_from_json(item, "cleanup journal")
        if entry.relative in objects:
            fail(f"cleanup journal contains duplicate object: {entry.relative}")
        objects[entry.relative] = entry
    if objects and "." not in objects:
        fail("cleanup journal does not bind the tombstone root")
    if sum(entry.size for entry in objects.values() if entry.kind == "file") != byte_count:
        fail("cleanup journal byte count does not match objects")
    if byte_count > CLEANUP_TOMBSTONE_MAX_BYTES:
        fail("cleanup journal byte count exceeds the bound")
    children = cleanup_declared_children(objects)
    tombstone_info = lstat_optional(tombstone)
    if tombstone_info is not None:
        if stat.S_ISLNK(tombstone_info.st_mode) or not stat.S_ISDIR(tombstone_info.st_mode):
            fail("cleanup tombstone must be a real directory")
        actual_paths = sorted_tree_paths(tombstone)
        if len(actual_paths) > CLEANUP_TOMBSTONE_MAX_FILES:
            fail("cleanup tombstone exceeds the object bound")
        for path in actual_paths:
            relative = tree_relative(path, tombstone)
            entry = objects.get(relative)
            if entry is None:
                fail(f"cleanup tombstone contains unknown object: {relative}")
            if not cleanup_entry_matches_path(
                path,
                entry,
                allow_directory_drain_drift=True,
            ):
                fail(f"cleanup tombstone object identity changed: {relative}")
        provisional = CleanupPendingState(
            parent=parent,
            journal=journal,
            journal_content=content,
            tombstone=tombstone,
            kind=kind,
            object_count=object_count,
            byte_count=byte_count,
            objects=objects,
            children=children,
            journal_alias=alias,
            intent=intent if intent_info is not None else None,
            intent_alias=intent_alias,
        )
        for relative, entry in objects.items():
            if entry.kind == "dir":
                validate_cleanup_directory_for_drain(provisional, entry)
    return CleanupPendingState(
        parent=parent,
        journal=journal,
        journal_content=content,
        tombstone=tombstone,
        kind=kind,
        object_count=object_count,
        byte_count=byte_count,
        objects=objects,
        children=children,
        journal_alias=alias,
        intent=intent if intent_info is not None else None,
        intent_alias=intent_alias,
    )


def cleanup_pending_report(target: Path) -> dict[str, Any]:
    state = validate_cleanup_pending_state(target)
    if state is None:
        return {"cleanup_pending": False, "cleanup": None}
    return {
        "cleanup_pending": True,
        "cleanup": {
            "kind": state.kind,
            "object_count": state.object_count,
            "byte_count": state.byte_count,
            "max_files": CLEANUP_TOMBSTONE_MAX_FILES,
            "max_bytes": CLEANUP_TOMBSTONE_MAX_BYTES,
        },
    }


def add_cleanup_pending_fields(payload: dict[str, Any], target: Path) -> dict[str, Any]:
    payload.update(cleanup_pending_report(target))
    return payload


def publish_cleanup_metadata_file(
    final: Path,
    content: bytes,
    *,
    alias_prefix: Callable[[Path], str],
    max_bytes: int,
    label: str,
) -> bool:
    if len(content) > max_bytes:
        fail(f"{label} exceeds the byte bound")
    fd, temporary_name = tempfile.mkstemp(
        prefix=alias_prefix(final),
        dir=str(final.parent),
    )
    temporary = Path(temporary_name)
    final_visible = False
    try:
        write_complete(fd, content, f"{label} temporary {temporary}")
        os.fchmod(fd, OWNER_FILE_MODE)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.link(temporary, final)
        final_visible = True
        try:
            fsync_directory(final.parent)
            temporary.unlink()
            fsync_directory(final.parent)
            return True
        except BaseException:
            return False
    except FileExistsError as exc:
        raise ManagerError(f"{label} already exists") from exc
    except BaseException:
        if final_visible:
            return False
        raise
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        if not final_visible:
            temporary.unlink(missing_ok=True)


def publish_cleanup_intent_file(intent: Path, content: bytes) -> bool:
    return publish_cleanup_metadata_file(
        intent,
        content,
        alias_prefix=cleanup_intent_alias_prefix,
        max_bytes=CLEANUP_INTENT_MAX_BYTES,
        label="cleanup intent",
    )


def publish_cleanup_journal_file(journal: Path, content: bytes) -> bool:
    return publish_cleanup_metadata_file(
        journal,
        content,
        alias_prefix=cleanup_journal_alias_prefix,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        label="cleanup journal",
    )


def cleanup_retirement_name(kind: str, index: int) -> str:
    if kind not in {
        "managed-rollback-retirement",
        "backup-slot-retirement",
        "software-rollback-retirement",
        "software-stage-retirement",
    }:
        fail("cleanup retirement kind is invalid")
    return f"{index:02d}-{kind}"


def build_cleanup_transition(
    target: Path,
    retirements: list[tuple[Path, str]],
) -> tuple[bytes, bytes]:
    sources: list[dict[str, Any]] = []
    tombstone = cleanup_tombstone_path(target)
    total = [0]
    journal_objects: dict[str, CleanupJournalEntry] = {
        ".": cleanup_entry_from_path(tombstone, tombstone, total)
    }
    for index, (source, source_kind) in enumerate(retirements):
        if lstat_optional(source) is None:
            fail("cleanup source is missing")
        entries = snapshot_cleanup_tree(source, f"cleanup source {index}")
        source_payload = cleanup_source_to_json(
            target=target,
            source=source,
            source_kind=source_kind,
            index=index,
            entries=entries,
        )
        anchor_parent = cleanup_anchor_parent(target, source_payload["source_anchor"])
        if not cleanup_parent_exact_identity_matches(
            anchor_parent,
            source_payload["source_parent"],
        ):
            fail("cleanup source parent changed before intent publication")
        destination_objects = cleanup_entries_for_destination(
            entries,
            source_payload["destination_relative"],
        )
        overlap = set(journal_objects) & set(destination_objects)
        if overlap:
            fail(f"cleanup destinations overlap: {sorted(overlap)}")
        journal_objects.update(destination_objects)
        sources.append(source_payload)
    kind = cleanup_kind_for_retirements(retirements)
    journal_content = canonical_json(cleanup_journal_payload(target, kind, journal_objects))
    if len(journal_content) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds the byte bound")
    intent_content = canonical_json(cleanup_intent_payload(target, kind, sources))
    if len(intent_content) > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent exceeds the byte bound")
    return intent_content, journal_content


def cleanup_intent_source_path(target: Path, source: Mapping[str, Any]) -> Path:
    return cleanup_anchor_parent(target, source["source_anchor"]) / str(source["source_name"])


def cleanup_intent_destination_path(tombstone: Path, source: Mapping[str, Any]) -> Path:
    return tombstone / safe_relative_path(str(source["destination_relative"]))


def cleanup_transition_allowed_names(
    *,
    intent: Path,
    intent_alias: Path | None,
    tombstone: Path,
    journal: Path,
    journal_alias: Path | None,
) -> set[str]:
    allowed = {intent.name}
    if intent_alias is not None:
        allowed.add(intent_alias.name)
    if lstat_optional(tombstone) is not None:
        allowed.add(tombstone.name)
    if lstat_optional(journal) is not None:
        allowed.add(journal.name)
    if journal_alias is not None:
        allowed.add(journal_alias.name)
    return allowed


def require_cleanup_transition_parent_paths(
    parent: Path,
    *,
    intent: Path,
    intent_alias: Path | None,
    tombstone: Path,
    journal: Path,
    journal_alias: Path | None,
) -> None:
    allowed = cleanup_transition_allowed_names(
        intent=intent,
        intent_alias=intent_alias,
        tombstone=tombstone,
        journal=journal,
        journal_alias=journal_alias,
    )
    for path in parent.iterdir():
        if path.name not in allowed:
            fail(f"cleanup pending parent contains unknown path: {path.name}")


def remove_cleanup_intent_after_journal(target: Path) -> bool:
    intent = cleanup_intent_path(target)
    state = validate_cleanup_intent_state(target, allow_publication_alias=True)
    if state is None:
        return True
    _payload, alias, _journal_content = state
    try:
        if alias is not None:
            info = alias.lstat()
            intent_info = intent.lstat()
            if identity_of(info) != identity_of(intent_info):
                fail("cleanup intent publication alias changed")
            alias.unlink()
            fsync_directory(intent.parent)
        intent.unlink()
        fsync_directory(intent.parent)
        return True
    except BaseException:
        return False


def ensure_cleanup_tombstone_directory(parent: Path, tombstone: Path) -> None:
    info = lstat_optional(tombstone)
    if info is None:
        tombstone.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(tombstone, OWNER_DIR_MODE)
        fsync_directory(parent)
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("cleanup tombstone must be a real directory")
    require_current_user_owned(info, "cleanup tombstone")
    require_exact_mode(info, "cleanup tombstone", OWNER_DIR_MODE)


def complete_cleanup_transition_from_intent(target: Path) -> CleanupPendingState | None:
    intent_state = validate_cleanup_intent_state(target, allow_publication_alias=True)
    if intent_state is None:
        return validate_cleanup_pending_state(target, allow_publication_alias=True)
    payload, intent_alias, _journal_content = intent_state
    _kind, sources, _journal_objects, journal_content = validate_cleanup_intent_payload(
        target,
        payload,
    )
    parent = cleanup_pending_parent(target)
    journal = cleanup_journal_path(target)
    tombstone = cleanup_tombstone_path(target)
    journal_alias: Path | None = None
    if lstat_optional(journal) is None:
        for alias in cleanup_unpublished_metadata_aliases(journal):
            remove_unpublished_cleanup_metadata_alias(alias)
    if lstat_optional(journal) is not None:
        _content, _journal_stat, journal_alias = read_cleanup_journal_file(
            journal,
            allow_publication_alias=True,
        )
    require_cleanup_transition_parent_paths(
        parent,
        intent=cleanup_intent_path(target),
        intent_alias=intent_alias,
        tombstone=tombstone,
        journal=journal,
        journal_alias=journal_alias,
    )
    if lstat_optional(journal) is None:
        ensure_cleanup_tombstone_directory(parent, tombstone)
        _kind, sources, _journal_objects, journal_content = validate_cleanup_intent_payload(
            target,
            payload,
        )
        for source in sources:
            source_path = cleanup_intent_source_path(target, source)
            destination = cleanup_intent_destination_path(tombstone, source)
            source_entries = source["objects"]
            source_present = lstat_optional(source_path) is not None
            destination_present = lstat_optional(destination) is not None
            if source_present and destination_present:
                fail("cleanup transition has both source and destination")
            if destination_present:
                if not cleanup_entries_match_root(
                    destination,
                    source_entries,
                    allow_directory_drain_drift=False,
                ):
                    fail("cleanup transition destination identity changed")
                continue
            if not source_present:
                fail("cleanup transition source and destination are both missing")
            source_parent = cleanup_anchor_parent(target, source["source_anchor"])
            if not cleanup_parent_stable_identity_matches(source_parent, source["source_parent"]):
                fail("cleanup transition source parent identity changed")
            if not cleanup_entries_match_root(
                source_path,
                source_entries,
                allow_directory_drain_drift=False,
            ):
                fail("cleanup transition source identity changed")
            os.replace(source_path, destination)
            fsync_directory(source_parent)
            fsync_directory(destination.parent)
            if not cleanup_entries_match_root(
                destination,
                source_entries,
                allow_directory_drain_drift=False,
            ):
                fail("cleanup transition destination postcondition failed")
        _kind, _sources, _journal_objects, journal_content = validate_cleanup_intent_payload(
            target,
            payload,
        )
        publish_cleanup_journal_file(journal, journal_content)
    state = validate_cleanup_pending_state(target, allow_publication_alias=True)
    if state is None:
        fail("cleanup transition did not publish a cleanup journal")
    if state.journal_alias is None:
        remove_cleanup_intent_after_journal(target)
        state = validate_cleanup_pending_state(target, allow_publication_alias=True)
        if state is None:
            fail("cleanup journal disappeared while removing intent")
    return state


def publish_cleanup_tombstones(
    target: Path,
    retirements: list[tuple[Path, str]],
) -> CleanupPendingState:
    if not retirements:
        fail("cleanup retirement list is empty")
    if len(retirements) > 4:
        fail("cleanup retirement list exceeds the bound")
    parent = cleanup_pending_parent(target)
    intent = cleanup_intent_path(target)
    journal = cleanup_journal_path(target)
    tombstone = cleanup_tombstone_path(target)
    if validate_cleanup_pending_state(target) is not None:
        fail("cleanup pending state must be drained before a new mutation")
    ensure_owner_private_directory_chain(parent, "cleanup pending parent")
    require_owner_private_directory(parent, "cleanup pending parent")
    if list(parent.iterdir()):
        fail("cleanup pending parent must be empty before journal publication")
    try:
        ensure_cleanup_tombstone_directory(parent, tombstone)
        intent_content, journal_content = build_cleanup_transition(target, retirements)
    except BaseException:
        recover_empty_cleanup_transition_parent(target)
        raise
    publish_cleanup_intent_file(intent, intent_content)
    try:
        payload, _intent_alias, _expected_journal = validate_cleanup_intent_state(
            target, allow_publication_alias=True
        ) or fail("cleanup intent publication failed")
        _kind, sources, _journal_objects, _journal_content = validate_cleanup_intent_payload(
            target,
            payload,
        )
        for source in sources:
            source_path = cleanup_intent_source_path(target, source)
            destination = cleanup_intent_destination_path(tombstone, source)
            if lstat_optional(destination) is not None:
                fail("cleanup destination already exists")
            if not cleanup_parent_exact_identity_matches(
                cleanup_anchor_parent(target, source["source_anchor"]),
                source["source_parent"],
            ):
                fail("cleanup source parent changed before source move")
            if not cleanup_entries_match_root(
                source_path,
                source["objects"],
                allow_directory_drain_drift=False,
            ):
                fail("cleanup source identity changed before source move")
            os.replace(source_path, destination)
            fsync_directory(source_path.parent)
            fsync_directory(tombstone)
        fsync_directory(parent)
        _kind, _sources, _journal_objects, journal_content = validate_cleanup_intent_payload(
            target,
            payload,
        )
        publish_cleanup_journal_file(journal, journal_content)
        state = validate_cleanup_pending_state(
            target,
            allow_publication_alias=True,
        ) or fail("cleanup journal publication failed")
        if state.journal_alias is None:
            remove_cleanup_intent_after_journal(target)
            state = validate_cleanup_pending_state(
                target,
                allow_publication_alias=True,
            ) or fail("cleanup journal disappeared while removing intent")
        return state
    except BaseException:
        if lstat_optional(intent) is not None:
            return complete_cleanup_transition_from_intent(target) or fail(
                "cleanup transition recovery failed"
            )
        raise


def publish_cleanup_tombstone(target: Path, source: Path, kind: str) -> CleanupPendingState:
    return publish_cleanup_tombstones(target, [(source, kind)])


def unlink_cleanup_journal_alias(state: CleanupPendingState) -> None:
    alias = state.journal_alias
    if alias is None:
        return
    info = alias.lstat()
    journal_info = state.journal.lstat()
    if identity_of(info) != identity_of(journal_info):
        fail("cleanup journal publication alias changed")
    alias.unlink()
    fsync_directory(state.parent)


def delete_cleanup_tombstone_object(state: CleanupPendingState, entry: CleanupJournalEntry) -> None:
    path = cleanup_entry_path(state.tombstone, entry.relative)
    info = lstat_optional(path)
    if info is None:
        return
    if entry.kind == "dir":
        validate_cleanup_directory_for_drain(state, entry)
    else:
        parent_relative = Path(entry.relative).parent.as_posix()
        if parent_relative == "":
            parent_relative = "."
        parent_entry = state.objects.get(parent_relative)
        if parent_entry is not None and parent_entry.kind == "dir":
            validate_cleanup_directory_for_drain(state, parent_entry)
    if not cleanup_entry_matches_path(path, entry, allow_directory_drain_drift=True):
        fail(f"cleanup tombstone object changed before drain: {entry.relative}")
    if entry.kind == "file":
        path.unlink()
    elif entry.kind == "dir":
        path.rmdir()
    else:
        fail(f"cleanup tombstone object kind is invalid: {entry.relative}")
    fsync_directory(path.parent)
    fsync_directory(state.parent)


def cleanup_entries_all_absent(state: CleanupPendingState) -> bool:
    return all(
        lstat_optional(cleanup_entry_path(state.tombstone, relative)) is None
        for relative in state.objects
    )


def remove_empty_cleanup_parent(parent: Path) -> None:
    info = lstat_optional(parent)
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("cleanup pending parent must be a real directory")
    try:
        parent.rmdir()
        fsync_directory(parent.parent)
    except OSError as exc:
        if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
            raise


def recover_empty_cleanup_transition_parent(target: Path) -> bool:
    parent = cleanup_pending_parent(target)
    intent = cleanup_intent_path(target)
    journal = cleanup_journal_path(target)
    tombstone = cleanup_tombstone_path(target)
    info = lstat_optional(parent)
    if info is None:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("cleanup pending parent must be a real directory")
    require_current_user_owned(info, "cleanup pending parent")
    require_exact_mode(info, "cleanup pending parent", OWNER_DIR_MODE)
    entries = sorted(parent.iterdir())
    if not entries:
        remove_empty_cleanup_parent(parent)
        return True
    if lstat_optional(intent) is not None or lstat_optional(journal) is not None:
        return False
    aliases = [
        *cleanup_unpublished_metadata_aliases(intent),
        *cleanup_unpublished_metadata_aliases(journal),
    ]
    allowed = {tombstone.name, *(alias.name for alias in aliases)}
    if {path.name for path in entries} != allowed:
        return False
    tombstone_info = lstat_optional(tombstone)
    if (
        tombstone_info is None
        or stat.S_ISLNK(tombstone_info.st_mode)
        or not stat.S_ISDIR(tombstone_info.st_mode)
    ):
        fail("cleanup tombstone must be a real directory")
    if list(tombstone.iterdir()):
        return False
    for alias in aliases:
        remove_unpublished_cleanup_metadata_alias(alias)
    tombstone.rmdir()
    fsync_directory(parent)
    remove_empty_cleanup_parent(parent)
    return True


def drain_cleanup_pending(target: Path, *, post_commit: bool = False) -> bool:
    recovered_empty_transition = recover_empty_cleanup_transition_parent(target)
    state = complete_cleanup_transition_from_intent(target)
    if state is None:
        return recovered_empty_transition
    try:
        if state.journal_alias is not None:
            unlink_cleanup_journal_alias(state)
            state = validate_cleanup_pending_state(
                target,
                allow_publication_alias=True,
            ) or fail("cleanup journal disappeared during alias recovery")
        for relative, entry in sorted(
            state.objects.items(),
            key=lambda item: len(Path(item[0]).parts),
            reverse=True,
        ):
            delete_cleanup_tombstone_object(state, entry)
        if not cleanup_entries_all_absent(state):
            fail("cleanup tombstone drain did not remove all declared objects")
        state.journal.unlink()
        try:
            fsync_directory(state.parent)
            if not remove_cleanup_intent_after_journal(target):
                fail("cleanup intent cleanup failed")
            fsync_directory(state.parent)
        except BaseException:
            publish_cleanup_journal_file(state.journal, state.journal_content)
            if post_commit:
                return True
            raise
        remove_empty_cleanup_parent(state.parent)
        return True
    except BaseException:
        if (
            post_commit
            and validate_cleanup_pending_state(target, allow_publication_alias=True) is not None
        ):
            return True
        raise


def retire_transaction_tree_after_commit(target: Path, source: Path, kind: str) -> bool:
    return retire_transaction_trees_after_commit(target, [(source, kind)])


def retire_transaction_trees_after_commit(
    target: Path, retirements: list[tuple[Path, str]]
) -> bool:
    state = publish_cleanup_tombstones(target, retirements)
    if state.journal_alias is not None:
        return True
    drain_cleanup_pending(target, post_commit=True)
    return validate_cleanup_pending_state(target, allow_publication_alias=True) is not None


def drain_cleanup_pending_before_mutation(target: Path, *, create_target: bool) -> bool:
    if lstat_optional(cleanup_pending_parent(target)) is None:
        return False
    with internal_target_lock(target, create_target=create_target):
        return drain_cleanup_pending(target)


def require_no_cleanup_pending(target: Path, operation: str) -> None:
    if validate_cleanup_pending_state(target) is not None:
        fail(f"{operation} requires cleanup pending state to be drained by a mutation")


def software_installation_mode_drift(target: Path, executable_relative: str) -> list[str]:
    drift: list[str] = []
    parent_info = require_owned_directory_modes(
        software_parent(target),
        "software parent",
        {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
    )
    if stat.S_IMODE(parent_info.st_mode) != SOFTWARE_IMMUTABLE_DIR_MODE:
        drift.append("software parent mode")
    root = software_root(target)
    root_info = require_owned_directory_modes(
        root,
        "software root",
        {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
    )
    if stat.S_IMODE(root_info.st_mode) != SOFTWARE_IMMUTABLE_DIR_MODE:
        drift.append("software root mode")
    executable_path = root / safe_relative_path(executable_relative)
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree must not contain symlinks: {relative}")
        require_current_user_owned(info, f"software path {relative}")
        actual = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            expected = SOFTWARE_IMMUTABLE_DIR_MODE
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                fail(f"software path must not have hard-link aliases: {relative}")
            expected = software_file_hardened_mode(path, executable_path, info)
        else:
            fail(f"software tree path must be regular file or directory: {relative}")
        if actual != expected:
            drift.append(f"software mode {relative}")
    return drift


def software_stamp_payload(
    target: Path,
    package: SoftwarePackage,
    executable_relative: str,
    tree: SoftwareTree,
) -> dict[str, Any]:
    return {
        "schema_version": SOFTWARE_STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "runtime_product": "Kiro CLI",
        "version": expected_runtime_version(),
        "canonical_target": str(target),
        "install_mode": "target-owned-official-artifact",
        "package": {
            "os": package.os_name,
            "architecture": package.architecture,
            "libc": package.libc,
            "fileType": package.file_type,
            "variant": package.variant,
            "download": package.download,
            "sha256": package.sha256,
            "size": package.size,
        },
        "executable": {
            "relative_path": executable_relative,
            "sha256": tree.executable_sha256,
        },
        "tree": {
            "sha256": tree.digest,
            "file_count": tree.file_count,
            "byte_count": tree.byte_count,
            "max_files": SOFTWARE_TREE_MAX_FILES,
            "max_bytes": SOFTWARE_TREE_MAX_BYTES,
        },
        "official_vendor_installer": official_vendor_installer_record(),
    }


def validate_software_stamp(stamp: dict[str, Any], target: Path) -> None:
    if set(stamp) != SOFTWARE_STAMP_KEYS:
        fail("software stamp has invalid keys")
    if stamp["schema_version"] != SOFTWARE_STAMP_SCHEMA or stamp["product_name"] != PRODUCT_NAME:
        fail("software stamp identity or schema is invalid")
    if not isinstance(stamp["build_version"], str) or not stamp["build_version"].strip():
        fail("software stamp build version is invalid")
    if not isinstance(stamp["runtime_product"], str) or not isinstance(stamp["version"], str):
        fail("software stamp runtime identity is invalid")
    if stamp["canonical_target"] != str(target):
        fail("software stamp is bound to a different canonical target")
    if not isinstance(stamp["install_mode"], str) or not stamp["install_mode"].strip():
        fail("software stamp install mode is invalid")
    package = stamp["package"]
    if not isinstance(package, dict):
        fail("software stamp package is invalid")
    expected_package_keys = {
        "os",
        "architecture",
        "libc",
        "fileType",
        "variant",
        "download",
        "sha256",
        "size",
    }
    if set(package) != expected_package_keys:
        fail("software stamp package has invalid keys")
    for key in ("os", "architecture", "fileType", "variant", "download"):
        if not isinstance(package[key], str) or not package[key].strip():
            fail(f"software stamp package.{key} is invalid")
    if package["libc"] is not None and not isinstance(package["libc"], str):
        fail("software stamp package.libc is invalid")
    if not isinstance(package["sha256"], str) or not SHA256_PATTERN.fullmatch(package["sha256"]):
        fail("software stamp package.sha256 is invalid")
    if not isinstance(package["size"], int) or package["size"] <= 0:
        fail("software stamp package.size is invalid")
    executable = stamp["executable"]
    if (
        not isinstance(executable, dict)
        or not isinstance(executable.get("relative_path"), str)
        or not isinstance(executable.get("sha256"), str)
        or not SHA256_PATTERN.fullmatch(executable["sha256"])
    ):
        fail("software stamp executable is invalid")
    tree = stamp["tree"]
    if (
        not isinstance(tree, dict)
        or not isinstance(tree.get("sha256"), str)
        or not SHA256_PATTERN.fullmatch(tree["sha256"])
        or not isinstance(tree.get("file_count"), int)
        or not isinstance(tree.get("byte_count"), int)
        or tree.get("max_files") != SOFTWARE_TREE_MAX_FILES
        or tree.get("max_bytes") != SOFTWARE_TREE_MAX_BYTES
    ):
        fail("software stamp tree is invalid")
    installer = stamp["official_vendor_installer"]
    if not isinstance(installer, dict) or installer.get("used_by_manager") is not False:
        fail("software stamp official vendor installer record is invalid")


def load_software_stamp_for_status(target: Path) -> tuple[dict[str, Any] | None, str | None]:
    if software_root_presence(target) != "present":
        return None, None
    stamp_path = software_stamp_path(target)
    if require_regular_stamp_if_present(stamp_path, "software stamp") is None:
        return None, None
    try:
        content, info = read_regular_file(
            stamp_path,
            "software stamp",
            owner_only=False,
            max_bytes=SOFTWARE_METADATA_MAX_BYTES,
        )
        require_current_user_owned(info, "software stamp")
        ensure_not_group_world_writable(info, "software stamp")
        stamp = parse_json_object(content, "software stamp")
        validate_software_stamp(stamp, target)
    except ManagerError as exc:
        return None, str(exc)
    return stamp, None


def load_software_stamp(target: Path) -> dict[str, Any] | None:
    stamp, issue = load_software_stamp_for_status(target)
    if issue is not None:
        fail(issue)
    return stamp


def package_libc(package: dict[str, Any]) -> str | None:
    if package.get("os") != "linux":
        return None
    download = str(package.get("download", ""))
    return "musl" if "-musl." in download else "glibc"


def baseline_package_for_stamp(package: dict[str, Any]) -> dict[str, Any] | None:
    matches = [
        baseline_package
        for baseline_package in baseline_packages()
        if baseline_package.get("download") == package["download"]
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def software_stamp_provenance_drift(stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    if stamp["build_version"] != VERSION:
        drift.append("software manager build_version")
    if stamp["runtime_product"] != "Kiro CLI":
        drift.append("software runtime product")
    if stamp["version"] != expected_runtime_version():
        drift.append("software runtime version")
    if stamp["install_mode"] != "target-owned-official-artifact":
        drift.append("software install mode")
    if stamp["official_vendor_installer"] != official_vendor_installer_record():
        drift.append("software official vendor installer")
    package = stamp["package"]
    baseline_package = baseline_package_for_stamp(package)
    if baseline_package is None:
        drift.append("software package download")
        return drift
    expected_values = {
        "os": baseline_package.get("os"),
        "architecture": baseline_package.get("architecture"),
        "libc": package_libc(baseline_package),
        "fileType": baseline_package.get("fileType"),
        "variant": baseline_package.get("variant"),
        "download": baseline_package.get("download"),
        "sha256": baseline_package.get("sha256"),
        "size": baseline_package.get("size"),
    }
    for key, expected in expected_values.items():
        if package.get(key) != expected:
            drift.append(f"software package {key}")
    return drift


def software_status_body(target: Path) -> dict[str, Any]:
    presence = software_root_presence(target)
    if presence == "missing":
        return add_cleanup_pending_fields(
            {
                "state": "missing",
                "target": str(target),
                "version": expected_runtime_version(),
                "executable": None,
                "drift": [],
                "executes_binary": False,
            },
            target,
        )
    if presence == "absent":
        return add_cleanup_pending_fields(
            {
                "state": "absent",
                "target": str(target),
                "version": expected_runtime_version(),
                "executable": None,
                "drift": [],
                "executes_binary": False,
            },
            target,
        )
    root = software_root(target)
    stamp, stamp_issue = load_software_stamp_for_status(target)
    if stamp_issue is not None:
        return add_cleanup_pending_fields(
            {
                "state": "partial",
                "target": str(target),
                "version": expected_runtime_version(),
                "executable": None,
                "drift": [f"software stamp invalid: {stamp_issue}"],
                "executes_binary": False,
            },
            target,
        )
    if stamp is None:
        return add_cleanup_pending_fields(
            {
                "state": "partial",
                "target": str(target),
                "version": expected_runtime_version(),
                "executable": None,
                "drift": ["software stamp missing"],
                "executes_binary": False,
            },
            target,
        )
    executable_relative = stamp["executable"]["relative_path"]
    tree = scan_software_tree(root, executable_relative)
    provenance_drift = software_stamp_provenance_drift(stamp)
    mode_drift = software_installation_mode_drift(target, executable_relative)
    integrity_drift = []
    if tree.digest != stamp["tree"]["sha256"]:
        integrity_drift.append("software tree digest")
    if tree.executable_sha256 != stamp["executable"]["sha256"]:
        integrity_drift.append("software executable digest")
    drift = [*provenance_drift, *mode_drift, *integrity_drift]
    state = "installed"
    if integrity_drift or mode_drift:
        state = "drift"
    elif provenance_drift:
        state = "needs-update"
    return add_cleanup_pending_fields(
        {
            "state": state,
            "target": str(target),
            "version": stamp["version"],
            "package": stamp["package"],
            "executable": str(software_executable_from_stamp(target, stamp)),
            "drift": drift,
            "executes_binary": False,
        },
        target,
    )


def preflight_software_target(target: Path, *, allow_partial: bool) -> dict[str, Any]:
    validated_transaction_parent(target)
    status = software_status_body(target)
    if status["state"] in {"partial", "drift", "needs-update"} and not allow_partial:
        fail("software target needs update or repair; run software-update")
    return status


def software_status(target: Path) -> dict[str, Any]:
    require_supported_host_preflight()
    return run_read_only_target_operation(target, software_status_body)


def validated_transaction_parent(target: Path) -> Path:
    parent = target.parent
    info = require_directory(parent, "software transaction parent")
    mode = stat.S_IMODE(info.st_mode)
    if current_user_owns(info) and not mode & 0o022:
        return parent
    if mode & stat.S_ISVTX:
        return parent
    fail("software transaction parent must be private or sticky")
    return parent


def create_transaction_dir(target: Path, label: str) -> Path:
    directory = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.nddev-kiro-cli-{label}-",
            dir=str(validated_transaction_parent(target)),
        )
    )
    os.chmod(directory, OWNER_DIR_MODE)
    return directory


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def software_stage(target: Path) -> Iterator[Path]:
    parent_snapshot = snapshot_directory_identity(target.parent, "software stage parent")
    stage = create_transaction_dir(target, "software-stage")
    try:
        yield stage
    finally:
        cleanup_transaction_tree(stage, "software stage")
        restore_directory_identity(target.parent, parent_snapshot, "software stage parent")
        require_no_software_transaction_residue(target, "software stage")


def software_transaction_residue(target: Path) -> list[Path]:
    parent = target.parent
    if lstat_optional(parent) is None:
        return []
    prefixes = (
        f".{target.name}.nddev-kiro-cli-software-stage-",
        f".{target.name}.nddev-kiro-cli-software-rollback-",
    )
    return sorted(path for path in parent.iterdir() if path.name.startswith(prefixes))


def setup_transaction_residue(target: Path) -> list[Path]:
    parent = target.parent
    if lstat_optional(parent) is None:
        return []
    prefixes = (f".{target.name}.nddev-kiro-cli-setup-rollback-",)
    return sorted(path for path in parent.iterdir() if path.name.startswith(prefixes))


def require_no_setup_transaction_residue(target: Path, label: str) -> None:
    residue = setup_transaction_residue(target)
    if residue:
        names = [path.name for path in residue]
        fail(f"{label} left transaction residue: {names}")


def require_no_software_transaction_residue(target: Path, label: str) -> None:
    residue = software_transaction_residue(target)
    if residue:
        names = [path.name for path in residue]
        fail(f"{label} left transaction residue: {names}")


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, OWNER_DIR_MODE)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > SOFTWARE_TREE_MAX_FILES:
                fail("Kiro CLI zip archive has too many entries")
            total = 0
            for info in infos:
                relative = Path(info.filename)
                if relative.is_absolute() or any(
                    part in {"", ".", ".."} for part in relative.parts
                ):
                    fail(f"Kiro CLI zip archive has unsafe path: {info.filename}")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    fail(f"Kiro CLI zip archive has symlink path: {info.filename}")
                total += info.file_size
                if total > SOFTWARE_TREE_MAX_BYTES:
                    fail("Kiro CLI zip archive exceeds the software tree size limit")
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        fail(f"Kiro CLI zip archive is invalid: {exc}")
    for path in destination.rglob("*"):
        relative = path.relative_to(destination).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"Kiro CLI zip archive extracted symlink path: {relative}")
        if stat.S_ISDIR(info.st_mode):
            os.chmod(path, OWNER_DIR_MODE)
            continue
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                fail(f"Kiro CLI zip archive extracted hard-link alias: {relative}")
            # zipfile.extractall preserves the archive's external_attr mode
            # bits, which under an ambient umask (e.g. 0002) leave extracted
            # regular files group-writable. Force an owner-only mode before
            # the writability check so a hardened extraction is never
            # rejected by its own non-deterministic ambient mask.
            os.chmod(path, OWNER_FILE_MODE)
            info = path.lstat()
            ensure_not_group_world_writable(info, f"Kiro CLI zip archive path {relative}")
            continue
        fail(f"Kiro CLI zip archive extracted unsupported path: {relative}")


def installer_environment(stage: Path) -> dict[str, str]:
    home = stage / "installer-home"
    temp = stage / "tmp"
    kiro_home = stage / "kiro-home"
    for directory in (home, temp, kiro_home):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, OWNER_DIR_MODE)
    env = {
        "HOME": str(home),
        "KIRO_HOME": str(kiro_home),
        "TMPDIR": str(temp),
        "PATH": TRUSTED_SYSTEM_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "KIRO_CLI_SKIP_SETUP": "1",
    }
    for key in tuple(env):
        if key in SECRET_ENV_NAMES or key.startswith(SECRET_ENV_PREFIXES):
            env.pop(key, None)
    return env


def system_command_environment() -> dict[str, str]:
    return {
        "PATH": TRUSTED_SYSTEM_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def copy_regular_executable(source: Path, destination: Path) -> None:
    content, info = read_regular_file(
        source,
        f"Kiro CLI installed executable {source}",
        owner_only=False,
        max_bytes=SOFTWARE_TREE_MAX_BYTES,
    )
    if not stat.S_IMODE(info.st_mode) & stat.S_IXUSR:
        fail(f"Kiro CLI installed executable is not executable: {source}")
    atomic_write(destination, content)
    os.chmod(destination, 0o700)


def prepare_linux_software_root(stage: Path, artifact: Path) -> tuple[Path, str]:
    extract_dir = stage / "extract"
    safe_extract_zip(artifact, extract_dir)
    install_script = extract_dir / "kirocli" / "install.sh"
    require_regular_file(install_script, "Kiro CLI archive install script", owner_only=False)
    result = subprocess.run(
        [TRUSTED_BASH, str(install_script)],
        cwd=str(install_script.parent),
        env=installer_environment(stage),
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        fail(
            "Kiro CLI archive install script failed inside isolated staging: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    prepared = stage / "prepared" / SOFTWARE_DIR_NAME
    binary = stage / "installer-home" / ".local" / "bin" / "kiro-cli"
    chat_binary = stage / "installer-home" / ".local" / "bin" / "kiro-cli-chat"
    copy_regular_executable(binary, prepared / "bin" / "kiro-cli")
    if chat_binary.exists():
        copy_regular_executable(chat_binary, prepared / "bin" / "kiro-cli-chat")
    return prepared, "bin/kiro-cli"


def prepare_macos_software_root(
    stage: Path, artifact: Path, package: SoftwarePackage
) -> tuple[Path, str]:
    if platform.system().lower() != "darwin":
        fail("macOS Kiro CLI DMG extraction requires macOS")
    mount = stage / "mount"
    mount.mkdir(mode=OWNER_DIR_MODE)
    attached = False
    try:
        result = subprocess.run(
            [
                TRUSTED_HDIUTIL,
                "attach",
                str(artifact),
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mount),
            ],
            text=True,
            env=system_command_environment(),
            capture_output=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            fail(f"Kiro CLI DMG mount failed: {result.stderr.strip() or result.stdout.strip()}")
        attached = True
        apps = [path for path in mount.iterdir() if path.suffix == ".app" and path.is_dir()]
        if len(apps) != 1:
            fail("Kiro CLI DMG must contain exactly one .app bundle")
        prepared = stage / "prepared" / SOFTWARE_DIR_NAME
        prepared.mkdir(parents=True, mode=OWNER_DIR_MODE)
        os.chmod(prepared, OWNER_DIR_MODE)
        app_target = prepared / apps[0].name
        shutil.copytree(apps[0], app_target, symlinks=False)
        cli_path = package.cli_path or "Contents/MacOS/kiro-cli"
        source_cli = app_target / safe_relative_path(cli_path)
        require_regular_file(source_cli, "Kiro CLI app executable", owner_only=False)
        wrapper = prepared / "bin" / "kiro-cli"
        wrapper_content = (
            f'#!/bin/sh\nset -eu\nexec "$(dirname "$0")/../{apps[0].name}/{cli_path}" "$@"\n'
        ).encode("utf-8")
        atomic_write(wrapper, wrapper_content)
        os.chmod(wrapper, 0o700)
        return prepared, "bin/kiro-cli"
    finally:
        if attached:
            subprocess.run(
                [TRUSTED_HDIUTIL, "detach", str(mount), "-quiet"],
                text=True,
                env=system_command_environment(),
                capture_output=True,
                check=False,
                timeout=60,
            )


def prepare_software_root(
    stage: Path, artifact: Path, package: SoftwarePackage
) -> tuple[Path, str]:
    if package.os_name == "linux":
        return prepare_linux_software_root(stage, artifact)
    if package.os_name == "macos":
        return prepare_macos_software_root(stage, artifact, package)
    fail(f"unsupported Kiro CLI software package OS: {package.os_name}")


def finalize_prepared_software(
    prepared: Path,
    target: Path,
    package: SoftwarePackage,
    executable_relative: str,
) -> None:
    tree = scan_software_tree(prepared, executable_relative)
    stamp = software_stamp_payload(target, package, executable_relative, tree)
    atomic_write(prepared / SOFTWARE_STAMP_NAME, canonical_json(stamp))


def ensure_directory_chain(path: Path, created_dirs: list[str], label: str) -> None:
    missing: list[Path] = []
    current = path
    while lstat_optional(current) is None:
        missing.append(current)
        current = current.parent
    require_owner_private_directory(current, f"{label} existing parent")
    for directory in reversed(missing):
        directory.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(directory, OWNER_DIR_MODE)
        require_owner_private_directory(directory, f"{label} directory {directory}")
        created_dirs.append(str(directory))


def remove_created_directories(created_dirs: list[str]) -> None:
    for directory in reversed(created_dirs):
        path = Path(directory)
        info = lstat_optional(path)
        if info is None:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"created transaction path must be a real directory: {path}")
        path.rmdir()
        fsync_directory(path.parent)


def restore_software_parent_mode(target: Path, mode: int | None) -> None:
    parent = software_parent(target)
    if mode is None or lstat_optional(parent) is None:
        return
    os.chmod(parent, mode)
    fsync_directory(parent.parent)


def software_install_transaction_matches(
    target: Path,
    *,
    target_existed: bool,
    target_mode: int | None,
    target_inode: int | None,
    target_mtime_ns: int | None,
    target_parent: DirectorySnapshot,
    software_parent_manifest: dict[str, TreeManifestEntry] | None,
) -> bool:
    try:
        if not directory_identity_matches(target.parent, target_parent):
            return False
        target_info = lstat_optional(target)
        if not target_existed:
            return target_info is None
        if (
            target_info is None
            or stat.S_ISLNK(target_info.st_mode)
            or not stat.S_ISDIR(target_info.st_mode)
            or stat.S_IMODE(target_info.st_mode) != target_mode
            or target_info.st_ino != target_inode
            or target_info.st_mtime_ns != target_mtime_ns
        ):
            return False
        return tree_matches_manifest(software_parent(target), software_parent_manifest)
    except ManagerError:
        return False


def restore_software_install_transaction_once(
    target: Path,
    *,
    target_existed: bool,
    target_mode: int | None,
    target_inode: int | None,
    target_mtime_ns: int | None,
    target_parent: DirectorySnapshot,
    software_parent_manifest: dict[str, TreeManifestEntry] | None,
    software_parent_initial_mode: int | None,
    final_root: Path,
    rollback_parent: Path | None,
    rollback_root: Path | None,
    installed_new_root: bool,
    existing_root_modes: dict[str, int] | None,
    created_dirs: list[str],
) -> None:
    if lstat_optional(software_parent(target)) is not None:
        make_software_parent_mutable(target)
    if installed_new_root and lstat_optional(final_root) is not None:
        make_software_tree_mutable(final_root)
        remove_tree_exact(final_root)
    if rollback_root is not None and lstat_optional(rollback_root) is not None:
        ensure_directory_chain(final_root.parent, [], "software parent rollback restore")
        os.replace(rollback_root, final_root)
        fsync_directory(final_root.parent)
        if rollback_parent is not None and lstat_optional(rollback_parent) is not None:
            fsync_directory(rollback_parent)
        if existing_root_modes is not None:
            restore_tree_modes(final_root, existing_root_modes)
        restore_tree_manifest_metadata(software_parent(target), software_parent_manifest)
    elif existing_root_modes is not None and lstat_optional(final_root) is not None:
        restore_tree_modes(final_root, existing_root_modes)
        restore_tree_manifest_metadata(software_parent(target), software_parent_manifest)
    restore_software_parent_mode(target, software_parent_initial_mode)
    if rollback_parent is not None and lstat_optional(rollback_parent) is not None:
        cleanup_transaction_tree(rollback_parent, "software rollback")
    remove_created_directories(created_dirs)
    restore_tree_manifest_metadata(software_parent(target), software_parent_manifest)
    if (
        target_existed
        and target_mode is not None
        and target_inode is not None
        and target_mtime_ns is not None
        and lstat_optional(target) is not None
    ):
        info = target.lstat()
        if info.st_ino != target_inode:
            fail("software transaction target directory identity changed")
        os.chmod(target, target_mode)
        refreshed = target.lstat()
        os.utime(target, ns=(refreshed.st_atime_ns, target_mtime_ns))
        fsync_existing_path(target, directory=True)
        fsync_directory(target.parent)
    if software_parent_manifest is None and lstat_optional(software_parent(target)) is not None:
        remove_tree_exact(software_parent(target))
    restore_directory_identity(target.parent, target_parent, "software transaction parent")


def restore_software_install_transaction(
    target: Path,
    *,
    target_existed: bool,
    target_mode: int | None,
    target_inode: int | None,
    target_mtime_ns: int | None,
    target_parent: DirectorySnapshot,
    software_parent_manifest: dict[str, TreeManifestEntry] | None,
    software_parent_initial_mode: int | None,
    final_root: Path,
    rollback_parent: Path | None,
    rollback_root: Path | None,
    installed_new_root: bool,
    existing_root_modes: dict[str, int] | None,
    created_dirs: list[str],
) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            restore_software_install_transaction_once(
                target,
                target_existed=target_existed,
                target_mode=target_mode,
                target_inode=target_inode,
                target_mtime_ns=target_mtime_ns,
                target_parent=target_parent,
                software_parent_manifest=software_parent_manifest,
                software_parent_initial_mode=software_parent_initial_mode,
                final_root=final_root,
                rollback_parent=rollback_parent,
                rollback_root=rollback_root,
                installed_new_root=installed_new_root,
                existing_root_modes=existing_root_modes,
                created_dirs=created_dirs,
            )
        except BaseException as exc:
            last_error = exc
        if software_install_transaction_matches(
            target,
            target_existed=target_existed,
            target_mode=target_mode,
            target_inode=target_inode,
            target_mtime_ns=target_mtime_ns,
            target_parent=target_parent,
            software_parent_manifest=software_parent_manifest,
        ):
            return
    raise ManagerError("software rollback did not restore exact pre-state") from last_error


def require_installed_software_postcondition(target: Path) -> dict[str, Any]:
    status = software_status_body(target)
    if status["state"] != "installed" or status["drift"]:
        fail(f"Kiro CLI software install postcondition failed: {status['state']} {status['drift']}")
    return status


def install_prepared_software_root(
    target: Path,
    prepared: Path,
    *,
    allow_existing: bool,
    post_commit_retirements: list[tuple[Path, str]] | None = None,
) -> dict[str, Any]:
    created_dirs: list[str] = []
    rollback_parent: Path | None = None
    rollback_root: Path | None = None
    installed_new_root = False
    final_root = software_root(target)
    software_parent_initial_mode: int | None = None
    existing_root_modes: dict[str, int] | None = None
    target_info = lstat_optional(target)
    target_existed = target_info is not None
    target_mode = stat.S_IMODE(target_info.st_mode) if target_info is not None else None
    target_inode = target_info.st_ino if target_info is not None else None
    target_mtime_ns = target_info.st_mtime_ns if target_info is not None else None
    target_parent = snapshot_directory_identity(
        target.parent,
        "software transaction parent",
    )
    software_parent_manifest = snapshot_tree_manifest(software_parent(target))
    try:
        if target_info is None:
            target.mkdir(mode=OWNER_DIR_MODE)
            os.chmod(target, OWNER_DIR_MODE)
            created_dirs.append(str(target))
            fsync_directory(target.parent)
        else:
            if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
                fail("--target must be a real directory")
            require_current_user_owned(target_info, "--target")
            require_exact_mode(target_info, "--target", OWNER_DIR_MODE)
        for path, label in software_ancestor_paths(target):
            if lstat_optional(path) is not None:
                if path == software_parent(target):
                    require_owned_directory_modes(
                        path,
                        label,
                        {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
                    )
                else:
                    require_owner_private_directory(path, label)
        software_parent_path = final_root.parent
        software_parent_info = lstat_optional(software_parent_path)
        if software_parent_info is not None:
            software_parent_initial_mode = stat.S_IMODE(software_parent_info.st_mode)
        if lstat_optional(software_parent_path) is None:
            ensure_directory_chain(software_parent_path, created_dirs, "software parent")
        else:
            make_software_parent_mutable(target)
        prepared_stamp = read_json_file(
            prepared / SOFTWARE_STAMP_NAME,
            "prepared software stamp",
            owner_only=True,
        )
        validate_software_stamp(prepared_stamp, target)
        executable_relative = prepared_stamp["executable"]["relative_path"]
        harden_software_tree(prepared, executable_relative, harden_root=False)
        final_root_info = lstat_optional(final_root)
        if final_root_info is not None:
            if not allow_existing:
                fail("Kiro CLI software is already installed")
            if stat.S_ISLNK(final_root_info.st_mode) or not stat.S_ISDIR(final_root_info.st_mode):
                fail("existing software root must be a real directory")
            require_current_user_owned(final_root_info, "existing software root")
            mode = stat.S_IMODE(final_root_info.st_mode)
            if mode not in {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE}:
                fail(f"existing software root must have mode 0700 or 0500, got {mode:04o}")
            existing_root_modes = snapshot_tree_modes(final_root)
            make_software_tree_mutable(final_root)
            rollback_parent = create_transaction_dir(target, "software-rollback")
            rollback_root = rollback_parent / "previous"
            os.replace(final_root, rollback_root)
            fsync_directory(final_root.parent)
            fsync_directory(rollback_parent)
        os.replace(prepared, final_root)
        installed_new_root = True
        fsync_directory(final_root.parent)
        os.chmod(final_root, SOFTWARE_IMMUTABLE_DIR_MODE)
        require_owned_directory_modes(final_root, "software root", {SOFTWARE_IMMUTABLE_DIR_MODE})
        os.chmod(software_parent(target), SOFTWARE_IMMUTABLE_DIR_MODE)
        require_owned_directory_modes(
            software_parent(target),
            "software parent",
            {SOFTWARE_IMMUTABLE_DIR_MODE},
        )
        require_installed_software_postcondition(target)
        if rollback_parent is not None:
            if rollback_root is not None:
                make_software_tree_mutable(rollback_root)
            if post_commit_retirements is None:
                post_commit_retirements = []
            post_commit_retirements.append((rollback_parent, "software-rollback-retirement"))
            rollback_parent = None
        return {
            "target": str(target),
            "version": prepared_stamp["version"],
            "package": prepared_stamp["package"],
            "executable": str(software_executable_from_stamp(target, prepared_stamp)),
            "cleanup_pending": False,
            "rollback": {
                "mode": "rename-restore",
                "created_dirs": created_dirs,
            },
        }
    except BaseException:
        restore_software_install_transaction(
            target,
            target_existed=target_existed,
            target_mode=target_mode,
            target_inode=target_inode,
            target_mtime_ns=target_mtime_ns,
            target_parent=target_parent,
            software_parent_manifest=software_parent_manifest,
            software_parent_initial_mode=software_parent_initial_mode,
            final_root=final_root,
            rollback_parent=rollback_parent,
            rollback_root=rollback_root,
            installed_new_root=installed_new_root,
            existing_root_modes=existing_root_modes,
            created_dirs=created_dirs,
        )
        if lstat_optional(prepared) is not None:
            make_software_tree_mutable(prepared)
        raise


def validate_software_host_request(
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> tuple[str, str, str | None]:
    os_name = normalize_platform_name(platform_arg)
    architecture = normalize_architecture(architecture_arg, os_name)
    libc = normalize_libc(libc_arg, os_name, architecture)
    return os_name, architecture, libc


def select_software_package(
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> SoftwarePackage:
    os_name, architecture, libc = validate_software_host_request(
        platform_arg,
        architecture_arg,
        libc_arg,
    )
    manifest = read_manifest_source()
    package = select_baseline_package(os_name, architecture, libc)
    verify_manifest_package(manifest, package)
    return package


def prepare_software_from_package(
    target: Path,
    package: SoftwarePackage,
) -> tuple[Path, Path]:
    stage = create_transaction_dir(target, "software-stage")
    try:
        artifact = stage_artifact(stage, package)
        prepared, executable_relative = prepare_software_root(stage, artifact, package)
        finalize_prepared_software(prepared, target, package, executable_relative)
        return prepared, stage
    except BaseException:
        cleanup_transaction_tree(stage, "software stage")
        require_no_software_transaction_residue(target, "software stage")
        raise


def software_probe(
    target: Path,
    *,
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> dict[str, Any]:
    validate_software_host_request(platform_arg, architecture_arg, libc_arg)
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        preflight_software_target(target, allow_partial=True)
        package = select_software_package(
            platform_arg,
            architecture_arg,
            libc_arg,
        )
        with software_stage(target) as stage:
            artifact = stage_artifact(stage, package)
            prepared, executable_relative = prepare_software_root(stage, artifact, package)
            finalize_prepared_software(prepared, target, package, executable_relative)
            stamp = parse_json_object(
                (prepared / SOFTWARE_STAMP_NAME).read_bytes(),
                "prepared software stamp",
            )
            return {
                "operation": "software-probe",
                "target": str(target),
                "mutates": False,
                "stage_only": True,
                "cleanup_drained": cleanup_drained,
                "cleanup_pending": False,
                "version": stamp["version"],
                "package": stamp["package"],
                "executable": stamp["executable"],
                "tree": stamp["tree"],
                "official_vendor_installer": official_vendor_installer_record(),
            }


def software_install(
    target: Path,
    *,
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> dict[str, Any]:
    validate_software_host_request(platform_arg, architecture_arg, libc_arg)
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=True):
                status = preflight_software_target(target, allow_partial=False)
                if status["state"] == "installed":
                    fail("Kiro CLI software is already installed")
                package = select_software_package(
                    platform_arg,
                    architecture_arg,
                    libc_arg,
                )
                prepared, stage = prepare_software_from_package(target, package)
                try:
                    race_status = preflight_software_target(target, allow_partial=False)
                    if race_status["state"] == "installed":
                        fail("Kiro CLI software is already installed")
                    result = install_prepared_software_root(
                        target,
                        prepared,
                        allow_existing=False,
                    )
                except BaseException:
                    cleanup_transaction_tree(stage, "software stage")
                    require_no_software_transaction_residue(target, "software stage")
                    raise
                else:
                    result["cleanup_pending"] = retire_transaction_trees_after_commit(
                        target,
                        [(stage, "software-stage-retirement")],
                    )
                    require_no_software_transaction_residue(target, "software stage")
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise
    return {
        "operation": "software-install",
        "changed": True,
        "cleanup_drained": cleanup_drained,
        **result,
        "official_vendor_installer": official_vendor_installer_record(),
    }


def software_update(
    target: Path,
    *,
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> dict[str, Any]:
    validate_software_host_request(platform_arg, architecture_arg, libc_arg)
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                status = preflight_software_target(target, allow_partial=True)
                if status["state"] in {"missing", "absent"}:
                    fail("Kiro CLI software is absent; run software-install first")
                if status["state"] == "installed":
                    return {
                        "operation": "software-update",
                        "target": str(target),
                        "changed": False,
                        "cleanup_drained": cleanup_drained,
                        "cleanup_pending": False,
                        "version": status["version"],
                        "package": status["package"],
                        "executable": status["executable"],
                        "rollback": {"mode": "none", "created_dirs": []},
                        "official_vendor_installer": official_vendor_installer_record(),
                    }
                package = select_software_package(
                    platform_arg,
                    architecture_arg,
                    libc_arg,
                )
                prepared, stage = prepare_software_from_package(target, package)
                try:
                    race_status = preflight_software_target(target, allow_partial=True)
                    if race_status["state"] == "installed":
                        result = {
                            "operation": "software-update",
                            "target": str(target),
                            "changed": False,
                            "cleanup_drained": cleanup_drained,
                            "cleanup_pending": False,
                            "version": race_status["version"],
                            "package": race_status["package"],
                            "executable": race_status["executable"],
                            "rollback": {"mode": "none", "created_dirs": []},
                            "official_vendor_installer": official_vendor_installer_record(),
                        }
                        result["cleanup_pending"] = retire_transaction_trees_after_commit(
                            target,
                            [(stage, "software-stage-retirement")],
                        )
                        require_no_software_transaction_residue(target, "software stage")
                        return result
                    post_commit_retirements: list[tuple[Path, str]] = []
                    result = install_prepared_software_root(
                        target,
                        prepared,
                        allow_existing=True,
                        post_commit_retirements=post_commit_retirements,
                    )
                except BaseException:
                    cleanup_transaction_tree(stage, "software stage")
                    require_no_software_transaction_residue(target, "software stage")
                    raise
                else:
                    post_commit_retirements.append((stage, "software-stage-retirement"))
                    result["cleanup_pending"] = retire_transaction_trees_after_commit(
                        target,
                        post_commit_retirements,
                    )
                    require_no_software_transaction_residue(target, "software stage")
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise
    return {
        "operation": "software-update",
        "changed": True,
        "cleanup_drained": cleanup_drained,
        **result,
        "official_vendor_installer": official_vendor_installer_record(),
    }


def software_remove(target: Path) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                status = software_status_body(target)
                root = software_root(target)
                if status["state"] in {"missing", "absent"}:
                    return {
                        "operation": "software-remove",
                        "target": str(target),
                        "changed": False,
                        "removed_state": status["state"],
                        "cleanup_drained": cleanup_drained,
                        "cleanup_pending": False,
                    }
                target_info = lstat_optional(target)
                target_existed = target_info is not None
                target_mode = stat.S_IMODE(target_info.st_mode) if target_info is not None else None
                target_inode = target_info.st_ino if target_info is not None else None
                target_mtime_ns = target_info.st_mtime_ns if target_info is not None else None
                target_parent = snapshot_directory_identity(
                    target.parent,
                    "software transaction parent",
                )
                software_parent_initial_mode = stat.S_IMODE(software_parent(target).lstat().st_mode)
                software_parent_manifest = snapshot_tree_manifest(software_parent(target))
                rollback_parent: Path | None = None
                rollback_root: Path | None = None
                cleanup_pending = False
                require_owned_directory_modes(
                    root,
                    "software root",
                    {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
                )
                existing_root_modes = snapshot_tree_modes(root)
                try:
                    make_software_parent_mutable(target)
                    make_software_tree_mutable(root)
                    rollback_parent = create_transaction_dir(target, "software-rollback")
                    rollback_root = rollback_parent / "previous"
                    os.replace(root, rollback_root)
                    fsync_directory(root.parent)
                    fsync_directory(rollback_parent)
                    absent = software_status_body(target)
                    if absent["state"] not in {"missing", "absent"}:
                        fail(f"Kiro CLI software remove postcondition failed: {absent['state']}")
                    make_software_tree_mutable(rollback_root)
                    cleanup_pending = retire_transaction_tree_after_commit(
                        target,
                        rollback_parent,
                        "software-rollback-retirement",
                    )
                    rollback_parent = None
                    require_no_software_transaction_residue(target, "software remove")
                except BaseException:
                    restore_software_install_transaction(
                        target,
                        target_existed=target_existed,
                        target_mode=target_mode,
                        target_inode=target_inode,
                        target_mtime_ns=target_mtime_ns,
                        target_parent=target_parent,
                        software_parent_manifest=software_parent_manifest,
                        software_parent_initial_mode=software_parent_initial_mode,
                        final_root=root,
                        rollback_parent=rollback_parent,
                        rollback_root=rollback_root,
                        installed_new_root=False,
                        existing_root_modes=existing_root_modes,
                        created_dirs=[],
                    )
                    raise
                return {
                    "operation": "software-remove",
                    "target": str(target),
                    "changed": True,
                    "removed_state": status["state"],
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def validate_permission_profile_id(profile_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(profile_id):
        fail(f"invalid permission profile id: {profile_id!r}")
    if profile_id not in PERMISSION_PROFILE_IDS:
        fail(f"unknown permission profile: {profile_id}")


def expected_settings_for(_setup_id: str) -> dict[str, Any]:
    return {
        "app.disableAutoupdates": True,
        "chat.defaultAgent": "nddev-builder",
        "chat.ui": "tui",
        "telemetry.enabled": False,
    }


def expected_permissions_for(profile_id: str) -> bytes:
    if profile_id == "safe":
        return (
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
        ).encode("utf-8")
    if profile_id == "full-auto":
        return "rules:\n  - capability: all\n    effect: allow\n".encode("utf-8")
    fail(f"unsupported permission profile id: {profile_id}")


def render_permission_profile(profile_id: str) -> PermissionProfile:
    validate_permission_profile_id(profile_id)
    profile_root = PROFILE_ROOT / profile_id
    if not profile_root.is_dir() or profile_root.is_symlink():
        fail(f"unknown permission profile: {profile_id}")
    metadata = read_json_file(
        profile_root / "profile.json",
        f"permission profile {profile_id} metadata",
    )
    expected_keys = {"schema_version", "id", "description", "permissions_file"}
    if set(metadata) != expected_keys:
        fail(f"permission profile {profile_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != profile_id:
        fail(f"permission profile {profile_id} metadata identity or schema is invalid")
    if metadata["permissions_file"] != "permissions.yaml":
        fail(f"permission profile {profile_id} permissions_file declaration is invalid")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"permission profile {profile_id} description must be non-empty")
    content, _ = read_regular_file(
        profile_root / "permissions.yaml",
        f"permission profile {profile_id}/permissions.yaml",
    )
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"permission profile {profile_id}/permissions.yaml must be UTF-8: {exc}")
    if not content or not content.endswith(b"\n") or b"\r" in content:
        fail(
            f"permission profile {profile_id}/permissions.yaml must be non-empty LF-terminated text"
        )
    if content != expected_permissions_for(profile_id):
        fail(f"permission profile {profile_id}/permissions.yaml does not match the profile")
    return PermissionProfile(
        profile_id=profile_id,
        description=metadata["description"],
        permissions=content,
    )


def render_setup(setup_id: str) -> Setup:
    validate_setup_id(setup_id)
    if setup_id != CONTENT_SETUP_ID:
        fail(f"unknown setup: {setup_id}")
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {setup_id}")
    metadata = read_json_file(setup_root / "setup.json", f"setup {setup_id} metadata")
    expected_keys = {
        "schema_version",
        "id",
        "description",
        "managed_content_files",
        "managed_settings",
        "default_permission_profile",
        "supported_permission_profiles",
        "builder_enabled",
    }
    if set(metadata) != expected_keys:
        fail(f"setup {setup_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity or schema is invalid")
    if metadata["managed_content_files"] != list(BUILDER_FILES):
        fail(f"setup {setup_id} managed content file declaration is invalid")
    if metadata["managed_settings"] != expected_settings_for(setup_id):
        fail(f"setup {setup_id} managed settings declaration is invalid")
    if metadata["builder_enabled"] is not True:
        fail(f"setup {setup_id} must enable the native nddev-builder projection")
    if metadata["default_permission_profile"] != DEFAULT_PERMISSION_PROFILE_ID:
        fail(f"setup {setup_id} default permission profile declaration is invalid")
    if metadata["supported_permission_profiles"] != list(PERMISSION_PROFILE_IDS):
        fail(f"setup {setup_id} supported permission profile declaration is invalid")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"setup {setup_id} description must be non-empty")

    source_paths = {
        SETTINGS: "settings/cli.json",
        **{relative: relative for relative in BUILDER_FILES},
    }
    files: dict[str, bytes] = {}
    for relative, source in source_paths.items():
        path = setup_root / safe_relative_path(source)
        content, _ = read_regular_file(path, f"setup {setup_id}/{source}")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"setup {setup_id}/{source} must be UTF-8: {exc}")
        if not content or not content.endswith(b"\n") or b"\r" in content:
            fail(f"setup {setup_id}/{source} must be non-empty LF-terminated text")
        files[relative] = content

    settings = parse_json_object(files[SETTINGS], f"setup {setup_id}/settings/cli.json")
    if settings != expected_settings_for(setup_id):
        fail(f"setup {setup_id}/settings/cli.json does not match the product model")
    return Setup(
        setup_id=setup_id,
        description=metadata["description"],
        managed_settings=metadata["managed_settings"],
        managed_content_files=tuple(metadata["managed_content_files"]),
        builder_enabled=True,
        files=files,
    )


def list_setups() -> list[dict[str, Any]]:
    if not CATALOG_ROOT.is_dir() or CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    result: list[dict[str, Any]] = []
    for setup_id in (CONTENT_SETUP_ID,):
        setup = render_setup(setup_id)
        result.append(
            {
                "id": setup.setup_id,
                "description": setup.description,
                "managed_content_files": list(setup.managed_content_files),
                "managed_settings": setup.managed_settings,
                "default_permission_profile": DEFAULT_PERMISSION_PROFILE_ID,
                "supported_permission_profiles": list(PERMISSION_PROFILE_IDS),
                "builder_enabled": setup.builder_enabled,
            }
        )
    if not result:
        fail("setup catalog is empty")
    return result


def list_permission_profiles() -> list[dict[str, Any]]:
    if not PROFILE_ROOT.is_dir() or PROFILE_ROOT.is_symlink():
        fail("permission profile catalog is missing or unsafe")
    result: list[dict[str, Any]] = []
    for profile_id in PERMISSION_PROFILE_IDS:
        profile = render_permission_profile(profile_id)
        result.append(
            {
                "id": profile.profile_id,
                "description": profile.description,
                "permissions_file": "permissions.yaml",
                "default": profile.profile_id == DEFAULT_PERMISSION_PROFILE_ID,
            }
        )
    return result


def require_real_directory_ancestors(path: Path, label: str) -> None:
    if not path.is_absolute():
        fail(f"{label} must be absolute")
    current = Path(path.anchor)
    require_directory(current, f"{label} filesystem root")
    for part in path.parts[1:]:
        current = current / part
        require_directory(current, f"{label} ancestor {current}")


def canonical_target_identity(path: Path) -> Path:
    if not path.is_absolute():
        fail("--target must be an absolute path")
    if path.name in {"", ".", ".."} or any(part in {".", ".."} for part in path.parts):
        fail("--target must have a stable literal basename")
    try:
        parent = path.parent.resolve(strict=True)
    except FileNotFoundError:
        fail(f"canonical --target parent is missing: {path.parent}")
    except RuntimeError:
        fail(f"canonical --target parent cannot be resolved: {path.parent}")
    require_real_directory_ancestors(parent, "canonical --target parent")
    return parent / path.name


def lexical_target_identity(path: Path) -> Path:
    if not path.is_absolute():
        fail("--target must be an absolute path")
    if path == Path(path.anchor):
        fail("filesystem root cannot be a target")
    if path.name in {"", ".", ".."} or any(part in {".", ".."} for part in path.parts):
        fail("--target must have a stable literal basename")
    return path


def resolve_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    return lexical_target_identity(expanded)


def ensure_target_directory(target: Path, *, create: bool) -> bool:
    try:
        info = target.lstat()
    except FileNotFoundError:
        if not create:
            return False
        try:
            target.mkdir(mode=OWNER_DIR_MODE)
        except FileExistsError:
            fail("--target appeared concurrently")
        os.chmod(target, OWNER_DIR_MODE)
        require_owner_private_directory(target, "--target")
        return True
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
    require_current_user_owned(info, "--target")
    require_exact_mode(info, "--target", OWNER_DIR_MODE)
    return True


def target_path(target: Path, relative: str) -> Path:
    reject_symlink_ancestors(target, relative)
    return target / safe_relative_path(relative)


def target_file_exists(target: Path, relative: str) -> bool:
    path = target_path(target, relative)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"managed path {path} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"managed path {path} must not have hard-link aliases")
    return True


def read_target_file(
    target: Path,
    relative: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> bytes:
    path = target_path(target, relative)
    content, _ = read_regular_file(
        path,
        f"managed path {path}",
        owner_only=owner_only,
        max_bytes=max_bytes,
    )
    return content


def read_target_settings_if_present(target: Path) -> dict[str, Any]:
    path = target_path(target, SETTINGS)
    if not path.exists():
        return {}
    content, _ = read_regular_file(
        path,
        f"Kiro settings {path}",
        owner_only=False,
        max_bytes=METADATA_MAX_BYTES,
    )
    return parse_json_object(content, f"Kiro settings {path}")


def settings_managed_fragment(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings[key] for key in SETTINGS_MANAGED_KEYS if key in settings}


def managed_digest(relative: str, content: bytes) -> str:
    if relative != SETTINGS:
        return sha256_bytes(content)
    settings = parse_json_object(content, "managed settings.json")
    return sha256_bytes(canonical_json(settings_managed_fragment(settings)))


def compose_settings(current: dict[str, Any], setup_settings: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result[key] = setup_settings[key]
    return result


def strip_managed_settings(current: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result.pop(key, None)
    return result


def desired_for_setup(
    target: Path,
    setup: Setup,
    profile: PermissionProfile,
) -> dict[str, bytes | None]:
    current = read_target_settings_if_present(target) if target.exists() else {}
    setup_settings = parse_json_object(setup.files[SETTINGS], "setup settings.json")
    desired = dict(setup.files)
    desired[PERMISSIONS] = profile.permissions
    desired[SETTINGS] = canonical_json(compose_settings(current, setup_settings))
    return desired


def stamp_payload(
    target: Path,
    setup_id: str,
    permission_profile_id: str,
    desired: dict[str, bytes | None],
) -> dict[str, Any]:
    managed_files: dict[str, str | None] = {}
    for relative in MANAGED_FILES:
        content = desired.get(relative)
        managed_files[relative] = None if content is None else managed_digest(relative, content)
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "permission_profile_id": permission_profile_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder": {
            "projection": BUILDER_PROJECTION,
            "enabled": True,
            "marketplace": None,
            "files": list(BUILDER_FILES),
        },
        "engine": {
            "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
            "status": MANAGED_LAUNCH_ENGINE_STATUS,
        },
    }


def legacy_stamp_payload(
    target: Path,
    setup_id: str,
    desired: dict[str, bytes | None],
) -> dict[str, Any]:
    managed_files: dict[str, str | None] = {}
    for relative in LEGACY_MANAGED_FILES:
        content = desired.get(relative)
        managed_files[relative] = None if content is None else managed_digest(relative, content)
    return {
        "schema_version": LEGACY_STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder": {
            "projection": LEGACY_BUILDER_PROJECTION,
            "enabled": True,
            "marketplace": None,
            "files": list(LEGACY_BUILDER_FILES),
        },
    }


def stamp_managed_files(stamp: dict[str, Any]) -> tuple[str, ...]:
    if stamp.get("schema_version") == STAMP_SCHEMA:
        return MANAGED_FILES
    if stamp.get("schema_version") == LEGACY_STAMP_SCHEMA:
        return LEGACY_MANAGED_FILES
    fail("managed stamp schema is invalid")


def stamp_is_current(stamp: dict[str, Any]) -> bool:
    return stamp.get("schema_version") == STAMP_SCHEMA


def validate_digest_map(
    value: Any,
    label: str,
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> dict[str, str | None]:
    if not isinstance(value, dict) or set(value) != set(managed_files):
        fail(f"{label} must declare exactly {list(managed_files)}")
    result: dict[str, str | None] = {}
    for name in managed_files:
        digest = value[name]
        if digest is not None and (
            not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
        ):
            fail(f"{label}.{name} must be null or a lowercase SHA-256 digest")
        result[name] = digest
    return result


def load_stamp(target: Path) -> dict[str, Any] | None:
    if not ensure_target_directory(target, create=False):
        return None
    if not target_file_exists(target, STAMP_NAME):
        return None
    content = read_target_file(
        target,
        STAMP_NAME,
        owner_only=True,
        max_bytes=METADATA_MAX_BYTES,
    )
    stamp = parse_json_object(content, f"managed stamp {target / STAMP_NAME}")
    schema = stamp.get("schema_version")
    if schema == LEGACY_STAMP_SCHEMA:
        if set(stamp) != LEGACY_STAMP_KEYS:
            fail("legacy managed stamp has invalid keys")
        if stamp["product_name"] != PRODUCT_NAME:
            fail("legacy managed stamp identity is invalid")
        if stamp["canonical_target"] != str(target):
            fail("legacy managed stamp is bound to a different canonical target")
        setup_id = stamp.get("setup_id")
        if setup_id not in LEGACY_SETUP_IDS:
            fail("legacy managed stamp setup_id is invalid")
        validate_digest_map(
            stamp["managed_files"],
            "legacy managed stamp managed_files",
            LEGACY_MANAGED_FILES,
        )
        builder = stamp["builder"]
        if not isinstance(builder, dict) or builder.get("projection") != LEGACY_BUILDER_PROJECTION:
            fail("legacy managed stamp builder projection is invalid")
        if builder.get("enabled") is not True or builder.get("marketplace") is not None:
            fail("legacy managed stamp builder state is invalid")
        return stamp
    if set(stamp) != STAMP_KEYS:
        fail("managed stamp has invalid keys")
    if stamp["schema_version"] != STAMP_SCHEMA or stamp["product_name"] != PRODUCT_NAME:
        fail("managed stamp identity or schema is invalid")
    if stamp["canonical_target"] != str(target):
        fail("managed stamp is bound to a different canonical target")
    if stamp["setup_id"] != CONTENT_SETUP_ID:
        fail("managed stamp setup_id is invalid")
    permission_profile_id = stamp["permission_profile_id"]
    if not isinstance(permission_profile_id, str):
        fail("managed stamp permission_profile_id must be a string")
    validate_permission_profile_id(permission_profile_id)
    validate_digest_map(stamp["managed_files"], "managed stamp managed_files", MANAGED_FILES)
    builder = stamp["builder"]
    if not isinstance(builder, dict) or builder.get("projection") != BUILDER_PROJECTION:
        fail("managed stamp builder projection is invalid")
    if builder.get("enabled") is not True or builder.get("marketplace") is not None:
        fail("managed stamp builder state is invalid")
    if builder.get("files") != list(BUILDER_FILES):
        fail("managed stamp builder file list is invalid")
    engine = stamp["engine"]
    if not isinstance(engine, dict):
        fail("managed stamp engine state is invalid")
    if (
        engine.get("argument") != MANAGED_LAUNCH_ENGINE_ARGUMENT
        or engine.get("status") != MANAGED_LAUNCH_ENGINE_STATUS
    ):
        fail("managed stamp engine state is invalid")
    return stamp


def detect_drift(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    managed_files = stamp_managed_files(stamp)
    expected = validate_digest_map(
        stamp["managed_files"],
        "managed stamp managed_files",
        managed_files,
    )
    for relative in managed_files:
        if not target_file_exists(target, relative):
            drift.append(relative)
            continue
        content = read_target_file(target, relative, owner_only=True)
        if managed_digest(relative, content) != expected[relative]:
            drift.append(relative)
    return drift


def snapshot_managed_files(
    target: Path,
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> dict[str, FileSnapshot]:
    snapshot: dict[str, FileSnapshot] = {}
    for relative in (*managed_files, STAMP_NAME):
        if ensure_target_directory(target, create=False) and target_file_exists(target, relative):
            path = target_path(target, relative)
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            content = read_target_file(target, relative, owner_only=False)
            snapshot[relative] = FileSnapshot(
                content=content,
                digest=sha256_bytes(content),
                mode=mode,
                inode=info.st_ino,
                mtime_ns=info.st_mtime_ns,
            )
        else:
            snapshot[relative] = FileSnapshot(content=None, digest=None, mode=None)
    return snapshot


def desired_path_digest(relative: str, content: bytes | None) -> str | None:
    if content is None:
        return None
    return sha256_bytes(content)


def changed_managed_paths(
    before: dict[str, FileSnapshot],
    desired: dict[str, bytes | None],
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> list[str]:
    changed: list[str] = []
    for relative in (*managed_files, STAMP_NAME):
        before_snapshot = before.get(relative, FileSnapshot(content=None, digest=None, mode=None))
        before_digest = desired_path_digest(relative, before_snapshot.content)
        after_content = desired.get(relative)
        after_digest = desired_path_digest(relative, after_content)
        after_mode = OWNER_FILE_MODE if after_content is not None else None
        if before_digest != after_digest or before_snapshot.mode != after_mode:
            changed.append(relative)
    return changed


def assert_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, expected in snapshot.items():
        exists = ensure_target_directory(target, create=False) and target_file_exists(
            target, relative
        )
        if not exists:
            actual = FileSnapshot(content=None, digest=None, mode=None)
        else:
            path = target_path(target, relative)
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            content = read_target_file(target, relative, owner_only=False)
            actual = FileSnapshot(
                content=content,
                digest=sha256_bytes(content),
                mode=mode,
                inode=info.st_ino,
                mtime_ns=info.st_mtime_ns,
            )
        if (
            actual.digest != expected.digest
            or actual.mode != expected.mode
            or actual.inode != expected.inode
            or actual.mtime_ns != expected.mtime_ns
        ):
            raise ConcurrentTargetChange(f"managed path changed concurrently: {relative}")


def preflight_unmanaged_target(target: Path) -> None:
    if not ensure_target_directory(target, create=False):
        return
    for relative in MANAGED_FILES:
        if relative == SETTINGS:
            continue
        if target_file_exists(target, relative):
            fail(f"unmanaged target already has managed path: {relative}")
    settings_path = target_path(target, SETTINGS)
    if settings_path.exists():
        settings = read_target_settings_if_present(target)
        managed = set(SETTINGS_MANAGED_KEYS) & set(settings)
        if managed:
            fail(f"unmanaged target already has managed Kiro settings keys: {sorted(managed)}")


def ensure_owner_private_directory_chain(path: Path, label: str) -> None:
    missing: list[Path] = []
    current = path
    while lstat_optional(current) is None:
        missing.append(current)
        current = current.parent
    require_owner_private_directory(current, f"{label} existing parent")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=OWNER_DIR_MODE)
        except FileExistsError:
            pass
        os.chmod(directory, OWNER_DIR_MODE)
        require_owner_private_directory(directory, f"{label} directory {directory}")


def ensure_owned_nonwritable_directory_chain(path: Path, label: str) -> None:
    missing: list[Path] = []
    current = path
    while lstat_optional(current) is None:
        missing.append(current)
        current = current.parent
    existing = require_directory(current, f"{label} existing parent")
    ensure_not_group_world_writable(existing, f"{label} existing parent")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=OWNER_DIR_MODE)
        except FileExistsError:
            pass
        os.chmod(directory, OWNER_DIR_MODE)
        require_owner_private_directory(directory, f"{label} directory {directory}")


def make_parent_directories(path: Path) -> None:
    ensure_owned_nonwritable_directory_chain(path.parent, f"parent for {path}")


def snapshot_regular_destination(path: Path) -> FileSnapshot:
    info = lstat_optional(path)
    if info is None:
        return FileSnapshot(content=None, digest=None, mode=None)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"destination must be a regular non-symlink file: {path}")
    if info.st_nlink != 1:
        fail(f"destination must not have hard-link aliases: {path}")
    content = path.read_bytes()
    return FileSnapshot(
        content=content,
        digest=sha256_bytes(content),
        mode=stat.S_IMODE(info.st_mode),
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
    )


def atomic_replace_file(
    path: Path,
    content: bytes,
    mode: int,
    *,
    on_replaced: Any | None = None,
) -> None:
    make_parent_directories(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        write_complete(fd, content, f"temporary file {temporary}")
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        if on_replaced is not None:
            on_replaced()
        fsync_directory(path.parent)
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        temporary.unlink(missing_ok=True)


def restore_regular_destination(path: Path, snapshot: FileSnapshot) -> None:
    if snapshot.content is None:
        info = lstat_optional(path)
        if info is None:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail(f"rollback destination must be a regular file: {path}")
        path.unlink()
        fsync_directory(path.parent)
        return
    atomic_replace_file(path, snapshot.content, snapshot.mode or OWNER_FILE_MODE)


def atomic_write(path: Path, content: bytes) -> None:
    before = snapshot_regular_destination(path)
    replaced = False

    def mark_replaced() -> None:
        nonlocal replaced
        replaced = True

    try:
        atomic_replace_file(path, content, OWNER_FILE_MODE, on_replaced=mark_replaced)
    except BaseException:
        if replaced:
            restore_regular_destination(path, before)
        raise


def remove_empty_managed_parents(target: Path, relative: str) -> None:
    current = (target / safe_relative_path(relative)).parent
    while current != target and current.exists():
        try:
            current.rmdir()
            fsync_directory(current.parent)
        except OSError:
            break
        current = current.parent


def desired_content_matches(path: Path, content: bytes) -> bool:
    info = lstat_optional(path)
    if info is None:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"managed path {path} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"managed path {path} must not have hard-link aliases")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    return path.read_bytes() == content


def managed_directory_paths(target: Path, managed_files: tuple[str, ...]) -> tuple[Path, ...]:
    paths: set[Path] = {target}
    for relative in (*managed_files, STAMP_NAME):
        current = target_path(target, relative).parent
        while current != target.parent:
            paths.add(current)
            if current == target:
                break
            current = current.parent
    return tuple(sorted(paths, key=lambda path: (len(path.parts), str(path))))


def managed_directory_key(target: Path, path: Path) -> str:
    return "." if path == target else path.relative_to(target).as_posix()


def managed_directory_from_key(target: Path, key: str) -> Path:
    return target if key == "." else target / safe_relative_path(key)


def snapshot_managed_directories(
    target: Path,
    managed_files: tuple[str, ...],
) -> dict[str, DirectorySnapshot]:
    snapshot: dict[str, DirectorySnapshot] = {}
    for path in managed_directory_paths(target, managed_files):
        key = managed_directory_key(target, path)
        info = lstat_optional(path)
        if info is None:
            snapshot[key] = DirectorySnapshot(
                existed=False,
                mode=None,
                inode=None,
                mtime_ns=None,
            )
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"managed directory path must be a real directory: {key}")
        snapshot[key] = DirectorySnapshot(
            existed=True,
            mode=stat.S_IMODE(info.st_mode),
            inode=info.st_ino,
            mtime_ns=info.st_mtime_ns,
        )
    return snapshot


def managed_directories_match(target: Path, snapshot: dict[str, DirectorySnapshot]) -> bool:
    try:
        for key, expected in snapshot.items():
            path = managed_directory_from_key(target, key)
            info = lstat_optional(path)
            if not expected.existed:
                if info is not None:
                    return False
                continue
            if (
                info is None
                or stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != expected.mode
                or info.st_ino != expected.inode
                or info.st_mtime_ns != expected.mtime_ns
            ):
                return False
    except ManagerError:
        return False
    return True


def restore_managed_directories(target: Path, snapshot: dict[str, DirectorySnapshot]) -> None:
    for key, expected in sorted(
        snapshot.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        if expected.existed:
            continue
        path = managed_directory_from_key(target, key)
        if lstat_optional(path) is not None:
            remove_tree_exact(path)
    for key, expected in sorted(snapshot.items(), key=lambda item: len(Path(item[0]).parts)):
        if not expected.existed:
            continue
        path = managed_directory_from_key(target, key)
        info = require_directory(path, f"managed directory {key}")
        require_current_user_owned(info, f"managed directory {key}")
        if expected.mode is None or expected.mtime_ns is None:
            fail(f"managed directory snapshot is invalid: {key}")
        os.chmod(path, expected.mode)
        refreshed = path.lstat()
        os.utime(path, ns=(refreshed.st_atime_ns, expected.mtime_ns))
        fsync_directory(path.parent)


def managed_rollback_path(transaction: ManagedStateTransaction, relative: str) -> Path:
    if transaction.rollback_dir is None:
        fail("managed rollback directory is missing")
    return transaction.rollback_dir / "files" / safe_relative_path(relative)


def ensure_rollback_parent(path: Path) -> None:
    path.parent.mkdir(mode=OWNER_DIR_MODE, parents=True, exist_ok=True)
    os.chmod(path.parent, OWNER_DIR_MODE)
    require_owner_private_directory(path.parent, f"managed rollback parent {path.parent}")


def move_managed_file_to_rollback(path: Path, rollback_path: Path) -> None:
    ensure_rollback_parent(rollback_path)
    if lstat_optional(rollback_path) is not None:
        fail(f"managed rollback path already exists: {rollback_path}")
    os.replace(path, rollback_path)
    fsync_directory(path.parent)
    fsync_directory(rollback_path.parent)


def remove_current_managed_file(path: Path) -> None:
    info = lstat_optional(path)
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"managed rollback path must be a regular file: {path}")
    path.unlink()
    fsync_directory(path.parent)


def regular_file_matches_snapshot(path: Path, expected: FileSnapshot) -> bool:
    info = lstat_optional(path)
    if expected.content is None:
        return info is None
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    return (
        sha256_bytes(content) == expected.digest
        and stat.S_IMODE(info.st_mode) == expected.mode
        and info.st_ino == expected.inode
        and info.st_mtime_ns == expected.mtime_ns
    )


def atomic_remove_managed_file(path: Path, before: FileSnapshot) -> None:
    if before.content is None:
        return
    info = lstat_optional(path)
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"managed path {path} must be a regular non-symlink file")
    path.unlink()
    try:
        fsync_directory(path.parent)
    except BaseException:
        restore_regular_destination(path, before)
        raise


def verify_exact_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    *,
    managed_files: tuple[str, ...],
) -> None:
    for relative in (*managed_files, STAMP_NAME):
        path = target_path(target, relative)
        content = desired.get(relative)
        if content is None:
            if lstat_optional(path) is not None:
                fail(f"managed path should be absent: {relative}")
            continue
        if not desired_content_matches(path, content):
            fail(f"managed path bytes or mode mismatch: {relative}")


def replace_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    expected: dict[str, FileSnapshot] | None,
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
    remove_empty_parents: bool = True,
) -> None:
    transaction = begin_managed_state_transaction(
        target,
        desired,
        expected,
        managed_files=managed_files,
        remove_empty_parents=remove_empty_parents,
    )
    try:
        commit_managed_state_transaction(transaction)
    except BaseException:
        rollback_managed_state_transaction(transaction)
        raise


def begin_managed_state_transaction(
    target: Path,
    desired: dict[str, bytes | None],
    expected: dict[str, FileSnapshot] | None,
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
    remove_empty_parents: bool = True,
) -> ManagedStateTransaction:
    ensure_target_directory(target, create=True)
    if expected is not None:
        assert_snapshot(target, expected)
        before = expected
    else:
        before = snapshot_managed_files(target, managed_files)
    changed = tuple(changed_managed_paths(before, desired, managed_files))
    directories = snapshot_managed_directories(target, managed_files)
    rollback_dir = create_transaction_dir(target, "setup-rollback") if changed else None
    transaction = ManagedStateTransaction(
        target=target,
        rollback_dir=rollback_dir,
        before=before,
        desired=desired,
        managed_files=managed_files,
        directories=directories,
        remove_empty_parents=remove_empty_parents,
        changed=changed,
    )
    try:
        for relative in changed:
            path = target_path(target, relative)
            content = desired.get(relative)
            before_item = before.get(relative, FileSnapshot(content=None, digest=None, mode=None))
            if before_item.content is not None:
                require_regular_file(path, f"managed path {path}", owner_only=False)
                move_managed_file_to_rollback(path, managed_rollback_path(transaction, relative))
            if content is not None:
                atomic_write(path, content)
        verify_exact_managed_state(target, desired, managed_files=managed_files)
        return transaction
    except BaseException:
        rollback_managed_state_transaction(transaction)
        raise


def managed_transaction_matches(transaction: ManagedStateTransaction) -> bool:
    if not managed_snapshot_matches(
        transaction.target,
        transaction.before,
        managed_files=transaction.managed_files,
    ):
        return False
    if not managed_directories_match(transaction.target, transaction.directories):
        return False
    return not setup_transaction_residue(transaction.target)


def rollback_managed_state_transaction_once(transaction: ManagedStateTransaction) -> None:
    target = transaction.target
    if transaction.rollback_dir is not None:
        for relative in reversed(transaction.changed):
            path = target_path(target, relative)
            before_item = transaction.before.get(
                relative,
                FileSnapshot(content=None, digest=None, mode=None),
            )
            if regular_file_matches_snapshot(path, before_item):
                continue
            remove_current_managed_file(path)
            if before_item.content is not None:
                rollback_path = managed_rollback_path(transaction, relative)
                if lstat_optional(rollback_path) is None:
                    if regular_file_matches_snapshot(path, before_item):
                        continue
                    fail(f"managed rollback path is missing: {relative}")
                make_parent_directories(path)
                os.replace(rollback_path, path)
                fsync_directory(path.parent)
                fsync_directory(rollback_path.parent)
        cleanup_transaction_tree(transaction.rollback_dir, "managed rollback")
    restore_managed_directories(target, transaction.directories)
    assert_snapshot(target, transaction.before)
    if not managed_directories_match(target, transaction.directories):
        fail("managed directory rollback did not restore exact pre-state")
    require_no_setup_transaction_residue(target, "managed rollback")


def rollback_managed_state_transaction(transaction: ManagedStateTransaction) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            rollback_managed_state_transaction_once(transaction)
        except BaseException as exc:
            last_error = exc
        if managed_transaction_matches(transaction):
            return
    raise ManagerError(
        "managed transaction rollback did not restore exact pre-state"
    ) from last_error


def commit_managed_state_transaction(
    transaction: ManagedStateTransaction,
    *,
    extra_retirements: list[tuple[Path, str]] | None = None,
) -> bool:
    verify_exact_managed_state(
        transaction.target,
        transaction.desired,
        managed_files=transaction.managed_files,
    )
    if transaction.remove_empty_parents:
        for relative in (*transaction.managed_files, STAMP_NAME):
            if transaction.desired.get(relative) is None:
                remove_empty_managed_parents(transaction.target, relative)
        verify_exact_managed_state(
            transaction.target,
            transaction.desired,
            managed_files=transaction.managed_files,
        )
    cleanup_pending = False
    retirements = list(extra_retirements or [])
    if transaction.rollback_dir is not None:
        retirements.append((transaction.rollback_dir, "managed-rollback-retirement"))
    if retirements:
        cleanup_pending = retire_transaction_trees_after_commit(
            transaction.target,
            retirements,
        )
    require_no_setup_transaction_residue(transaction.target, "managed transaction")
    return cleanup_pending


def managed_snapshot_matches(
    target: Path,
    snapshot: dict[str, FileSnapshot],
    *,
    managed_files: tuple[str, ...],
) -> bool:
    try:
        assert_snapshot(
            target,
            {relative: snapshot[relative] for relative in (*managed_files, STAMP_NAME)},
        )
    except (ConcurrentTargetChange, ManagerError, KeyError):
        return False
    return True


def restore_snapshot_once(
    target: Path,
    snapshot: dict[str, FileSnapshot],
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> None:
    ensure_target_directory(target, create=True)
    for relative in (*managed_files, STAMP_NAME):
        item = snapshot.get(relative, FileSnapshot(content=None, digest=None, mode=None))
        path = target_path(target, relative)
        if regular_file_matches_snapshot(path, item):
            continue
        if item.content is None:
            actual = snapshot_regular_destination(path)
            atomic_remove_managed_file(path, actual)
            remove_empty_managed_parents(target, relative)
            continue
        restore_regular_destination(path, item)
    assert_snapshot(target, snapshot)


def restore_snapshot(
    target: Path,
    snapshot: dict[str, FileSnapshot],
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            restore_snapshot_once(target, snapshot, managed_files=managed_files)
        except BaseException as exc:
            last_error = exc
        if managed_snapshot_matches(target, snapshot, managed_files=managed_files):
            return
    raise ManagerError("managed rollback did not restore exact pre-state") from last_error


def lock_root(target: Path) -> Path:
    return target / LOCK_RUNTIME_DIR


def lock_path(target: Path) -> Path:
    return lock_root(target) / LOCK_DIR_NAME


def bootstrap_system_temp_root() -> Path:
    if sys.platform == "darwin":
        return Path("/private/tmp")
    return Path("/tmp")


def require_bootstrap_system_root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        fail("bootstrap system temp root is missing")
    info = require_directory(resolved, "bootstrap system temp root")
    if not stat.S_IMODE(info.st_mode) & stat.S_ISVTX:
        fail("bootstrap system temp root must be sticky")
    return resolved


def external_product_root_path() -> Path:
    system_root = require_bootstrap_system_root(bootstrap_system_temp_root())
    uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    return system_root / f"{PRODUCT_NAME}-{uid}"


def rollback_created_product_root(handle: ProductRootCreation, label: str) -> None:
    if not handle.created:
        return
    remove_tree_exact_retry(handle.root, label)
    if handle.parent_snapshot is not None:
        restore_directory_identity(
            handle.root.parent,
            handle.parent_snapshot,
            "bootstrap system temp root",
        )


def prepare_bootstrap_product_root(*, create: bool) -> ProductRootCreation | None:
    root = external_product_root_path()
    info = lstat_optional(root)
    if info is None:
        if not create:
            return None
        parent_snapshot = snapshot_directory_identity(root.parent, "bootstrap system temp root")
        handle = ProductRootCreation(root=root, created=True, parent_snapshot=parent_snapshot)
        try:
            handle.root.mkdir(mode=OWNER_DIR_MODE)
            os.chmod(handle.root, OWNER_DIR_MODE)
            require_owner_private_directory(handle.root, "bootstrap product lock root")
            fsync_directory(handle.root.parent)
            return handle
        except FileExistsError:
            pass
        except BaseException:
            rollback_created_product_root(handle, "bootstrap product lock root")
            raise
        info = lstat_optional(root)
    require_owner_private_directory(root, "bootstrap product lock root")
    return ProductRootCreation(root=root, created=False, parent_snapshot=None)


def bootstrap_product_root(*, create: bool = True) -> Path:
    handle = prepare_bootstrap_product_root(create=create)
    if handle is None:
        fail("bootstrap product lock root is missing")
    return handle.root


def external_lock_digest_for_canonical_target(canonical_target: Path) -> str:
    return sha256_bytes(f"{PRODUCT_NAME}\0{canonical_target}".encode("utf-8"))


def external_lock_digest(target: Path) -> str:
    return external_lock_digest_for_canonical_target(canonical_target_identity(target))


def external_lock_path(target: Path, *, create: bool = True) -> Path:
    return bootstrap_product_root(create=create) / (
        f"{external_lock_digest(target)}{EXTERNAL_LOCK_NAME_SUFFIX}"
    )


def external_lock_path_for_canonical_target(
    canonical_target: Path,
    *,
    create: bool = True,
) -> Path:
    digest = external_lock_digest_for_canonical_target(canonical_target)
    return bootstrap_product_root(create=create) / f"{digest}{EXTERNAL_LOCK_NAME_SUFFIX}"


def external_product_lock_binding() -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "anchor": "product",
        "lock_name": EXTERNAL_BOOTSTRAP_LOCK_NAME,
    }


def external_lock_binding_for_canonical_target(canonical_target: Path) -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "anchor": "target",
        "canonical_target": str(canonical_target),
        "lock_digest": external_lock_digest_for_canonical_target(canonical_target),
    }


def external_lock_binding(target: Path) -> dict[str, Any]:
    return external_lock_binding_for_canonical_target(canonical_target_identity(target))


def external_bootstrap_lock_path(*, create: bool = True) -> Path:
    return bootstrap_product_root(create=create) / EXTERNAL_BOOTSTRAP_LOCK_NAME


def close_external_lock_file(handle: ExternalLockFile) -> None:
    if handle.descriptor < 0:
        return
    descriptor = handle.descriptor
    handle.descriptor = -1
    os.close(descriptor)


def restore_external_lock_parent_graph_once(handle: ExternalLockFile) -> None:
    parent = handle.lock.parent
    snapshot = handle.parent_snapshot
    if snapshot is None:
        fail("external target lock parent snapshot is missing")
    relative = handle.lock.relative_to(parent).as_posix()
    if handle.created and relative in snapshot:
        fail("created external target lock marker was pre-existing")
    if handle.created:
        info = lstat_optional(handle.lock)
        if info is not None:
            if handle.created_identity is not None and identity_of(info) != handle.created_identity:
                fail("external target lock marker changed before rollback")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                fail("external target lock marker changed kind before rollback")
            handle.lock.unlink()
            fsync_directory(parent)
    current = snapshot_tree_exact(parent, allow_symlinks=True)
    if current is None:
        fail("external target lock parent is missing")
    current_paths = set(current)
    expected_paths = set(snapshot)
    if current_paths != expected_paths:
        fail("external target lock parent rollback found unexpected topology")
    for item_relative, entry in sorted(
        snapshot.items(),
        key=lambda item: (len(Path(item[0]).parts), item[0]),
    ):
        restore_tree_snapshot_entry(parent, item_relative, entry)
    for item_relative, entry in sorted(
        snapshot.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        if entry.kind == "dir":
            restore_tree_entry_metadata(tree_snapshot_path(parent, item_relative), entry)
    fsync_directory(parent.parent)


def external_lock_parent_graph_matches(handle: ExternalLockFile) -> bool:
    try:
        return (
            snapshot_tree_exact(handle.lock.parent, allow_symlinks=True) == handle.parent_snapshot
        )
    except ManagerError:
        return False


def restore_external_lock_parent_graph(
    handle: ExternalLockFile,
    label: str,
) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            restore_external_lock_parent_graph_once(handle)
        except BaseException as exc:
            last_error = exc
        if external_lock_parent_graph_matches(handle):
            return
    raise ManagerError(f"{label} rollback did not restore exact pre-state") from last_error


def abort_external_lock_file(
    handle: ExternalLockFile,
    label: str,
    cause: BaseException,
) -> NoReturn:
    with contextlib.suppress(OSError):
        close_external_lock_file(handle)
    if not handle.committed and handle.parent_snapshot is not None:
        restore_external_lock_parent_graph(handle, label)
    if isinstance(cause, ManagerError):
        raise cause
    raise ManagerError(
        f"{label} failed after creating external target lock file: {cause}"
    ) from cause


def commit_external_lock_file(handle: ExternalLockFile) -> None:
    handle.committed = True


def capture_external_lock_parent_snapshot(handle: ExternalLockFile) -> None:
    if handle.parent_snapshot is None:
        handle.parent_snapshot = snapshot_tree_exact(
            handle.lock.parent,
            allow_symlinks=True,
        )


def external_anchor_exists_no_create(lock: Path) -> bool:
    info = lstat_optional(lock)
    if info is None:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"external anchor must be a regular non-symlink file: {lock}")
    return True


def validate_external_lock_descriptor_base(
    lock: Path,
    descriptor: int,
    label: str,
) -> tuple[os.stat_result, os.stat_result]:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owned(opened, label)
    require_exact_mode(opened, label, OWNER_FILE_MODE)
    try:
        final = lock.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(final.st_mode) or not stat.S_ISREG(final.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    require_current_user_owned(final, label)
    require_exact_mode(final, label, OWNER_FILE_MODE)
    if identity_of(opened) != identity_of(final):
        raise ConcurrentTargetChange(f"{label} changed while it was opened")
    return opened, final


def validate_external_lock_descriptor(
    lock: Path,
    descriptor: int,
    label: str,
) -> None:
    opened, final = validate_external_lock_descriptor_base(lock, descriptor, label)
    if opened.st_nlink != 1:
        fail(f"{label} must have exactly one link")
    if final.st_nlink != 1:
        fail(f"{label} path must have exactly one link")


def external_lock_publication_alias_prefix(lock: Path) -> str:
    return f".{lock.name}."


def find_external_lock_publication_alias(
    lock: Path,
    expected_identity: tuple[int, int],
    label: str,
) -> Path:
    prefix = external_lock_publication_alias_prefix(lock)
    aliases: list[Path] = []
    scanned = 0
    try:
        with os.scandir(lock.parent) as entries:
            for entry in entries:
                if not entry.name.startswith(prefix):
                    continue
                scanned += 1
                if scanned > EXTERNAL_LOCK_ALIAS_SCAN_MAX:
                    fail(f"{label} publication alias scan exceeded bounded limit")
                alias = lock.parent / entry.name
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    fail(f"{label} publication alias must be a regular non-symlink file")
                require_current_user_owned(info, f"{label} publication alias")
                require_exact_mode(info, f"{label} publication alias", OWNER_FILE_MODE)
                if identity_of(info) != expected_identity:
                    fail(f"{label} publication alias does not match final anchor")
                aliases.append(alias)
    except OSError as exc:
        fail(f"cannot scan {label} publication aliases: {exc}")
    if len(aliases) != 1:
        fail(f"{label} must have exactly one recoverable publication alias")
    return aliases[0]


def recover_external_lock_publication_alias(
    lock: Path,
    descriptor: int,
    expected: dict[str, Any],
    label: str,
) -> None:
    opened, final = validate_external_lock_descriptor_base(lock, descriptor, label)
    if opened.st_nlink == 1 and final.st_nlink == 1:
        return
    if opened.st_nlink != final.st_nlink:
        raise ConcurrentTargetChange(f"{label} link count changed while it was opened")
    if opened.st_nlink != 2:
        fail(f"{label} has unknown hard-link aliases")
    require_external_lock_binding_matches(descriptor, expected, label)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        fail(f"cannot lock {label} for publication alias recovery: {exc}")
    try:
        opened, final = validate_external_lock_descriptor_base(lock, descriptor, label)
        if opened.st_nlink == 1 and final.st_nlink == 1:
            return
        if opened.st_nlink != final.st_nlink:
            raise ConcurrentTargetChange(f"{label} link count changed during recovery")
        if opened.st_nlink != 2:
            fail(f"{label} has unknown hard-link aliases")
        alias = find_external_lock_publication_alias(lock, identity_of(opened), label)
        alias.unlink()
        fsync_directory(lock.parent)
        validate_external_lock_descriptor(lock, descriptor, label)
        require_external_lock_binding_matches(descriptor, expected, label)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)


def require_external_lock_binding_matches(
    descriptor: int,
    expected: dict[str, Any],
    label: str,
) -> None:
    existing = read_external_lock_binding(descriptor)
    if existing is None:
        fail(f"{label} binding is empty")
    if existing != expected:
        fail(f"{label} binding mismatch")


def open_existing_external_lock_descriptor(
    lock: Path,
    expected: dict[str, Any],
    *,
    label: str,
    recover_publication_alias: bool = False,
) -> ExternalLockFile | None:
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        fail(f"cannot open {label}: {exc}")
    handle = ExternalLockFile(
        lock=lock,
        descriptor=descriptor,
        created=False,
        parent_snapshot=None,
        created_identity=None,
        committed=True,
    )
    try:
        validate_external_lock_descriptor_base(lock, descriptor, label)
        require_external_lock_binding_matches(descriptor, expected, label)
        if recover_publication_alias:
            recover_external_lock_publication_alias(lock, descriptor, expected, label)
        validate_external_lock_descriptor(lock, descriptor, label)
    except BaseException:
        close_external_lock_file(handle)
        raise
    return handle


def publish_external_lock_descriptor_no_replace(
    lock: Path,
    expected: dict[str, Any],
    *,
    label: str,
) -> ExternalLockFile:
    parent_snapshot = snapshot_tree_exact(lock.parent, allow_symlinks=True)
    content = canonical_json(expected)
    fd = -1
    temporary = Path()
    final_identity: tuple[int, int] | None = None
    final_visible = False
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{lock.name}.", dir=str(lock.parent))
        temporary = Path(temporary_name)
        write_complete(fd, content, f"{label} temporary binding")
        os.fchmod(fd, OWNER_FILE_MODE)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(temporary, lock)
        except FileExistsError:
            final_visible = True
            temporary.unlink()
            fsync_directory(lock.parent)
            existing = open_existing_external_lock_descriptor(
                lock,
                expected,
                label=label,
                recover_publication_alias=True,
            )
            if existing is None:
                raise ConcurrentTargetChange(f"{label} disappeared during publication")
            return existing
        final_visible = True
        final_identity = identity_of(lock.lstat())
        fsync_directory(lock.parent)
        temporary.unlink()
        fsync_directory(lock.parent)
        handle = open_existing_external_lock_descriptor(
            lock,
            expected,
            label=label,
            recover_publication_alias=True,
        )
        if handle is None:
            raise ConcurrentTargetChange(f"{label} disappeared after publication")
        handle.created = True
        handle.parent_snapshot = parent_snapshot
        handle.created_identity = final_identity
        return handle
    except BaseException as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        if temporary != Path():
            with contextlib.suppress(OSError):
                temporary.unlink()
        if parent_snapshot is not None and not final_visible:
            handle = ExternalLockFile(
                lock=lock,
                descriptor=-1,
                created=True,
                parent_snapshot=parent_snapshot,
                created_identity=final_identity,
            )
            restore_external_lock_parent_graph(handle, label)
        if isinstance(exc, ManagerError):
            raise
        raise ManagerError(f"{label} publication failed: {exc}") from exc


def open_external_lock_descriptor_for_binding(
    lock: Path,
    expected: dict[str, Any] | None,
    *,
    create: bool,
    label: str,
) -> ExternalLockFile:
    if expected is None:
        expected = (
            external_product_lock_binding() if lock.name == EXTERNAL_BOOTSTRAP_LOCK_NAME else {}
        )
    existing = open_existing_external_lock_descriptor(
        lock,
        expected,
        label=label,
        recover_publication_alias=True,
    )
    if existing is not None:
        return existing
    if not create:
        fail(f"{label} is missing")
    return publish_external_lock_descriptor_no_replace(lock, expected, label=label)


def open_external_lock_descriptor(lock: Path) -> ExternalLockFile:
    expected = (
        external_product_lock_binding()
        if lock.name == EXTERNAL_BOOTSTRAP_LOCK_NAME
        else read_existing_external_lock_binding(lock)
    )
    return open_external_lock_descriptor_for_binding(
        lock,
        expected=expected,
        create=True,
        label="external lock",
    )


def open_external_lock_file(lock: Path) -> int:
    expected = read_existing_external_lock_binding(lock)
    handle = open_existing_external_lock_descriptor(lock, expected, label="external lock")
    if handle is None:
        fail("external lock is missing")
    return handle.descriptor


def require_external_lock_descriptor(lock: Path, descriptor: int) -> None:
    validate_external_lock_descriptor(lock, descriptor, "external target lock")


def read_existing_external_lock_binding(lock: Path) -> dict[str, Any]:
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags)
    except OSError as exc:
        fail(f"cannot open external lock binding: {exc}")
    try:
        validate_external_lock_descriptor_base(lock, descriptor, "external lock")
        binding = read_external_lock_binding(descriptor)
        if binding is None:
            fail("external lock binding is empty")
        return binding
    finally:
        os.close(descriptor)


def read_external_lock_binding(descriptor: int) -> dict[str, Any] | None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > METADATA_MAX_BYTES:
            fail("external target lock binding is too large")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        return None
    return parse_json_object(content, "external target lock binding")


def ensure_external_lock_binding(descriptor: int, target: Path) -> None:
    expected = external_lock_binding(target)
    require_external_lock_binding_matches(descriptor, expected, "external target lock")


def ensure_external_lock_binding_matches(descriptor: int, expected: dict[str, Any]) -> None:
    require_external_lock_binding_matches(descriptor, expected, "external target lock")


def flock_external_lock(
    handle: ExternalLockFile,
    *,
    shared: bool,
    blocking: bool,
    label: str,
) -> None:
    operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    if not blocking:
        operation |= fcntl.LOCK_NB
    try:
        fcntl.flock(handle.descriptor, operation)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            fail(f"target is already locked: {handle.lock}")
        fail(f"cannot lock {label}: {exc}")
    validate_external_lock_descriptor(handle.lock, handle.descriptor, label)


def unlock_external_lock(handle: ExternalLockFile) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(handle.descriptor, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        close_external_lock_file(handle)


@contextlib.contextmanager
def external_bootstrap_lock(
    *,
    blocking: bool = False,
    shared: bool = False,
    create: bool = True,
) -> Iterator[Path]:
    root_handle = prepare_bootstrap_product_root(create=create)
    if root_handle is None:
        fail("external product anchor is missing")
    lock = root_handle.root / EXTERNAL_BOOTSTRAP_LOCK_NAME
    handle: ExternalLockFile | None = None
    locked = False
    try:
        handle = open_external_lock_descriptor_for_binding(
            lock,
            external_product_lock_binding(),
            create=create,
            label="external product lock",
        )
        try:
            flock_external_lock(
                handle,
                shared=shared,
                blocking=blocking,
                label="external product lock",
            )
        except BaseException:
            if handle.created and not handle.committed and root_handle.created:
                rollback_created_product_root(root_handle, "bootstrap product lock root")
            raise
        locked = True
        commit_external_lock_file(handle)
    except BaseException as exc:
        if locked and handle is not None:
            unlock_external_lock(handle)
            locked = False
        elif handle is not None:
            close_external_lock_file(handle)
        if root_handle.created and not external_anchor_exists_no_create(lock):
            rollback_created_product_root(root_handle, "bootstrap product lock root")
        if isinstance(exc, ManagerError):
            raise
        raise ManagerError(f"external product lock failed: {exc}") from exc
    try:
        yield lock
    finally:
        if locked and handle is not None:
            unlock_external_lock(handle)


@contextlib.contextmanager
def external_lifecycle_lock(target: Path, *, blocking: bool = False) -> Iterator[tuple[Path, Path]]:
    handle: ExternalLockFile | None = None
    target_locked = False
    with external_bootstrap_lock(blocking=blocking):
        canonical_target = canonical_target_identity(target)
        lock = external_lock_path_for_canonical_target(canonical_target)
        try:
            handle = open_external_lock_descriptor_for_binding(
                lock,
                external_lock_binding_for_canonical_target(canonical_target),
                create=True,
                label="external target lock",
            )
            commit_external_lock_file(handle)
            flock_external_lock(
                handle,
                shared=False,
                blocking=blocking,
                label="external target lock",
            )
            target_locked = True
        except BaseException:
            if handle is not None:
                close_external_lock_file(handle)
            raise
    try:
        yield canonical_target, lock
    finally:
        if handle is not None:
            if target_locked:
                unlock_external_lock(handle)
            else:
                close_external_lock_file(handle)


@contextlib.contextmanager
def external_target_scope(target: Path, *, blocking: bool = False) -> Iterator[Path]:
    with external_lifecycle_lock(target, blocking=blocking) as (canonical_target, _lock):
        yield canonical_target


@contextlib.contextmanager
def external_target_lock(target: Path, *, blocking: bool = False) -> Iterator[Path]:
    with external_lifecycle_lock(target, blocking=blocking) as (_canonical_target, lock):
        yield lock


def external_product_anchor_path_no_create() -> Path:
    return external_product_root_path() / EXTERNAL_BOOTSTRAP_LOCK_NAME


def external_product_anchor_exists_no_create() -> bool:
    return external_anchor_exists_no_create(external_product_anchor_path_no_create())


def cold_product_namespace_snapshot_no_create() -> dict[str, Any] | None:
    root = external_product_root_path()
    info = lstat_optional(root)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("external product namespace must be an owner-private directory without product anchor")
    require_current_user_owned(info, "external product namespace")
    require_exact_mode(info, "external product namespace", OWNER_DIR_MODE)
    scanned = 0
    try:
        with os.scandir(root) as entries:
            for _entry in entries:
                scanned += 1
                if scanned > EXTERNAL_LOCK_ALIAS_SCAN_MAX:
                    fail("external product namespace scan exceeded bounded limit")
                fail("external product namespace must be empty without product anchor")
    except OSError as exc:
        fail(f"cannot inspect external product namespace: {exc}")
    return {
        "dev": info.st_dev,
        "ino": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def run_read_only_with_product_anchor(
    target: Path,
    operation: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    root_handle = prepare_bootstrap_product_root(create=False)
    if root_handle is None:
        fail("external product anchor is missing")
    product_lock = root_handle.root / EXTERNAL_BOOTSTRAP_LOCK_NAME
    product_handle = open_existing_external_lock_descriptor(
        product_lock,
        external_product_lock_binding(),
        label="external product lock",
    )
    if product_handle is None:
        fail("external product anchor is missing")
    product_locked = False
    target_handle: ExternalLockFile | None = None
    target_locked = False
    try:
        flock_external_lock(
            product_handle,
            shared=True,
            blocking=False,
            label="external product lock",
        )
        product_locked = True
        canonical_target = canonical_target_identity(target)
        target_lock = external_lock_path_for_canonical_target(canonical_target, create=False)
        target_handle = open_existing_external_lock_descriptor(
            target_lock,
            external_lock_binding_for_canonical_target(canonical_target),
            label="external target lock",
        )
        if target_handle is None:
            try:
                return operation(canonical_target)
            finally:
                unlock_external_lock(product_handle)
                product_locked = False
        flock_external_lock(
            target_handle,
            shared=True,
            blocking=False,
            label="external target lock",
        )
        target_locked = True
    except BaseException:
        if target_handle is not None:
            if target_locked:
                unlock_external_lock(target_handle)
                target_locked = False
            else:
                close_external_lock_file(target_handle)
        if product_locked:
            unlock_external_lock(product_handle)
        else:
            close_external_lock_file(product_handle)
        raise
    unlock_external_lock(product_handle)
    product_locked = False
    try:
        assert target_handle is not None
        return operation(canonical_target)
    finally:
        if target_handle is not None:
            if target_locked:
                unlock_external_lock(target_handle)
            else:
                close_external_lock_file(target_handle)


def run_read_only_target_operation(
    target: Path,
    operation: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    if external_product_anchor_exists_no_create():
        return run_read_only_with_product_anchor(target, operation)
    cold_snapshot = cold_product_namespace_snapshot_no_create()
    if not external_product_anchor_exists_no_create():
        canonical_target = canonical_target_identity(target)
        result = operation(canonical_target)
        if external_product_anchor_exists_no_create():
            return run_read_only_with_product_anchor(target, operation)
        if cold_product_namespace_snapshot_no_create() == cold_snapshot:
            return result
        fail("external product namespace changed during cold read")
    return run_read_only_with_product_anchor(target, operation)


def require_lock_root_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    require_current_user_owned(info, label)
    mode = stat.S_IMODE(info.st_mode)
    if mode not in {OWNER_DIR_MODE, LOCK_HELD_DIR_MODE}:
        fail(f"{label} must have mode 0700 or 0500, got {mode:04o}")
    return info


def open_lock_root_directory(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open target lock root: {exc}")
    try:
        require_lock_root_descriptor(path, descriptor, "target lock root", expected_mode=None)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def require_lock_root_descriptor(
    path: Path,
    descriptor: int,
    label: str,
    *,
    expected_mode: int | None,
) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        fail(f"{label} must be a real directory")
    require_current_user_owned(opened, label)
    if expected_mode is None:
        mode = stat.S_IMODE(opened.st_mode)
        if mode not in {OWNER_DIR_MODE, LOCK_HELD_DIR_MODE}:
            fail(f"{label} must have mode 0700 or 0500, got {mode:04o}")
    else:
        require_exact_mode(opened, label, expected_mode)
    final = require_lock_root_directory(path, label)
    if identity_of(opened) != identity_of(final):
        raise ConcurrentTargetChange("target lock root changed while it was opened")


def chmod_lock_root(path: Path, mode: int) -> None:
    descriptor = open_lock_root_directory(path)
    try:
        os.fchmod(descriptor, mode)
        require_lock_root_descriptor(
            path,
            descriptor,
            "target lock root",
            expected_mode=mode,
        )
    finally:
        os.close(descriptor)


def ensure_lock_root(target: Path) -> Path:
    runtime_root = target / NDDEV_RUNTIME_DIR
    ensure_owner_private_directory_chain(runtime_root, "target runtime root")
    root = lock_root(target)
    info = lstat_optional(root)
    if info is None:
        root.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(root, OWNER_DIR_MODE)
        require_owner_private_directory(root, "target lock root")
        return root
    require_lock_root_directory(root, "target lock root")
    if (
        stat.S_IMODE(info.st_mode) == LOCK_HELD_DIR_MODE
        and lstat_optional(lock_path(target)) is None
    ):
        chmod_lock_root(root, OWNER_DIR_MODE)
        require_owner_private_directory(root, "target lock root")
    return root


def open_lock_file(lock: Path) -> int:
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags)
        created = False
    except FileNotFoundError:
        try:
            descriptor = os.open(lock, flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(lock, flags)
                created = False
            except OSError as exc:
                fail(f"cannot open target lock file: {exc}")
        except OSError as exc:
            fail(f"cannot create target lock file: {exc}")
    except OSError as exc:
        fail(f"cannot open target lock file: {exc}")
    try:
        if created:
            os.fchmod(descriptor, OWNER_FILE_MODE)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail("target lock must be a regular file")
        require_current_user_owned(opened, "target lock")
        require_exact_mode(opened, "target lock", OWNER_FILE_MODE)
        final = require_owner_private_file(lock, "target lock")
        if identity_of(opened) != identity_of(final):
            raise ConcurrentTargetChange("target lock changed while it was opened")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@contextlib.contextmanager
def internal_target_lock(target: Path, *, create_target: bool) -> Iterator[None]:
    if not ensure_target_directory(target, create=create_target):
        fail("--target is missing")
    root = ensure_lock_root(target)
    lock = lock_path(target)
    root_descriptor = open_lock_root_directory(root)
    try:
        descriptor = open_lock_file(lock)
    except BaseException:
        os.close(root_descriptor)
        raise
    locked = False
    hardened = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"target is already locked: {lock}")
            fail(f"cannot lock target: {exc}")
        locked = True
        os.fchmod(root_descriptor, LOCK_HELD_DIR_MODE)
        require_lock_root_descriptor(
            root,
            root_descriptor,
            "target lock root",
            expected_mode=LOCK_HELD_DIR_MODE,
        )
        hardened = True
        require_owner_private_file(lock, "target lock")
        yield
    finally:
        cleanup_error: BaseException | None = None
        if locked and hardened:
            for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
                try:
                    os.fchmod(root_descriptor, OWNER_DIR_MODE)
                    require_lock_root_descriptor(
                        root,
                        root_descriptor,
                        "target lock root",
                        expected_mode=OWNER_DIR_MODE,
                    )
                    require_owner_private_file(lock, "target lock")
                    cleanup_error = None
                    break
                except BaseException as exc:
                    cleanup_error = exc
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(descriptor)
        with contextlib.suppress(OSError):
            os.close(root_descriptor)
        if cleanup_error is not None:
            raise cleanup_error


@contextlib.contextmanager
def target_lock(target: Path, *, create_target: bool) -> Iterator[Path]:
    with external_target_scope(target) as canonical_target:
        with internal_target_lock(canonical_target, create_target=create_target):
            yield canonical_target


def backup_pool(target: Path) -> Path:
    return target / BACKUP_RUNTIME_DIR


def validate_owner_private_tree(root: Path, label: str) -> None:
    require_owner_private_directory(root, label)
    count = 0
    for path in root.rglob("*"):
        count += 1
        if count > BACKUP_TREE_MAX_FILES:
            fail(f"{label} has too many entries")
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        child_label = f"{label} path {relative}"
        if stat.S_ISLNK(info.st_mode):
            fail(f"{child_label} must not be a symlink")
        if stat.S_ISDIR(info.st_mode):
            require_current_user_owned(info, child_label)
            require_exact_mode(info, child_label, OWNER_DIR_MODE)
            continue
        if stat.S_ISREG(info.st_mode):
            require_owner_private_file(path, child_label)
            continue
        fail(f"{child_label} must be a regular file or directory")


def ensure_backup_pool(target: Path) -> Path:
    pool = backup_pool(target)
    ensure_owner_private_directory_chain(pool, "backup pool")
    validate_owner_private_tree(pool, "backup pool")
    return pool


def backup_record(relative: str, content: bytes | None) -> dict[str, Any]:
    if content is None:
        return {"path": relative, "size": None, "sha256": None}
    return {"path": relative, "size": len(content), "sha256": sha256_bytes(content)}


def validate_backup_records(
    value: Any,
    label: str,
    managed_files: tuple[str, ...],
) -> dict[str, dict[str, int | str | None]]:
    if not isinstance(value, list) or len(value) != len(managed_files):
        fail(f"{label} must declare exactly one record for each managed path")
    records: dict[str, dict[str, int | str | None]] = {}
    actual_paths: list[str] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != BACKUP_RECORD_KEYS:
            fail(f"{label} records must have exactly path, size, and sha256")
        relative = item["path"]
        if not isinstance(relative, str):
            fail(f"{label} record path must be a string")
        actual_paths.append(relative)
        if relative in records:
            fail(f"{label} contains duplicate path: {relative}")
        size = item["size"]
        digest = item["sha256"]
        if size is None and digest is None:
            records[relative] = {"path": relative, "size": None, "sha256": None}
            continue
        if not isinstance(size, int) or size < 0:
            fail(f"{label}.{relative}.size must be null or a non-negative integer")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            fail(f"{label}.{relative}.sha256 must be null or a lowercase SHA-256 digest")
        records[relative] = {"path": relative, "size": size, "sha256": digest}
    if actual_paths != list(managed_files):
        fail(f"{label} path order must match the managed path contract")
    return records


def expected_backup_slot_paths(
    managed_files: Mapping[str, dict[str, int | str | None]],
) -> set[str]:
    paths = {BACKUP_NAME, "files"}
    for relative, record in managed_files.items():
        if record["sha256"] is None:
            continue
        current = Path("files") / safe_relative_path(relative)
        for parent in reversed(current.parents):
            if parent == Path("."):
                continue
            paths.add(parent.as_posix())
        paths.add(current.as_posix())
    return paths


def expected_legacy_backup_slot_paths(managed_files: Mapping[str, str | None]) -> set[str]:
    paths = {BACKUP_NAME, "files"}
    for relative, digest in managed_files.items():
        if digest is None:
            continue
        current = Path("files") / safe_relative_path(relative)
        for parent in reversed(current.parents):
            if parent == Path("."):
                continue
            paths.add(parent.as_posix())
        paths.add(current.as_posix())
    return paths


def validate_backup_slot_dir(
    target: Path,
    slot_dir: Path,
    *,
    slot: int,
    backup_managed_files: tuple[str, ...],
) -> dict[str, Any]:
    validate_owner_private_tree(slot_dir, f"backup slot {slot}")
    actual_paths = {path.relative_to(slot_dir).as_posix() for path in slot_dir.rglob("*")}
    envelope_path = slot_dir / BACKUP_NAME
    if envelope_path.is_symlink() or not envelope_path.is_file():
        fail(f"backup slot is missing envelope: {slot}")
    envelope = read_json_file(envelope_path, f"backup slot {slot}", owner_only=True)
    if set(envelope) != BACKUP_KEYS:
        fail("backup envelope has invalid keys")
    if envelope["schema_version"] != BACKUP_SCHEMA or envelope["product_name"] != PRODUCT_NAME:
        fail("backup envelope identity or schema is invalid")
    if not isinstance(envelope["build_version"], str) or envelope["build_version"] != VERSION:
        fail("backup envelope build_version is invalid")
    if not isinstance(envelope["slot"], int) or envelope["slot"] != slot:
        fail("backup envelope slot is invalid")
    if envelope["canonical_target"] != str(target):
        fail("backup belongs to a different canonical target")
    if envelope["stamp_schema"] not in {STAMP_SCHEMA, LEGACY_STAMP_SCHEMA}:
        fail("backup envelope stamp_schema is invalid")
    if not isinstance(envelope["source_setup_id"], str):
        fail("backup envelope source_setup_id is invalid")
    if envelope["stamp_schema"] == STAMP_SCHEMA:
        if envelope["source_setup_id"] != CONTENT_SETUP_ID:
            fail("backup envelope source_setup_id is invalid")
        source_permission_profile_id = envelope["source_permission_profile_id"]
        if not isinstance(source_permission_profile_id, str):
            fail("backup envelope source_permission_profile_id is invalid")
        validate_permission_profile_id(source_permission_profile_id)
    else:
        if envelope["source_setup_id"] not in LEGACY_SETUP_IDS:
            fail("legacy backup envelope source_setup_id is invalid")
        if envelope["source_permission_profile_id"] is not None:
            fail("legacy backup envelope source_permission_profile_id must be null")
    if not isinstance(envelope["stamp_sha256"], str) or not SHA256_PATTERN.fullmatch(
        envelope["stamp_sha256"]
    ):
        fail("backup envelope stamp_sha256 is invalid")
    managed_files = validate_backup_records(
        envelope["managed_files"],
        "backup managed_files",
        backup_managed_files,
    )
    expected_paths = expected_backup_slot_paths(managed_files)
    if actual_paths != expected_paths:
        fail("backup slot path set is invalid")
    files_dir = slot_dir / "files"
    require_owner_private_directory(files_dir, f"backup slot {slot} files")
    for relative, record in managed_files.items():
        path = files_dir / safe_relative_path(relative)
        if record["sha256"] is None:
            if lstat_optional(path) is not None:
                fail(f"backup file should be absent: {relative}")
            continue
        content, _ = read_regular_file(path, f"backup file {relative}", owner_only=True)
        if len(content) > MANAGED_PAYLOAD_MAX_BYTES:
            fail(f"backup file is too large: {relative}")
        if len(content) != record["size"] or sha256_bytes(content) != record["sha256"]:
            fail(f"backup file digest mismatch: {relative}")
    return envelope


def choose_backup_slot(pool: Path) -> int:
    require_owner_private_directory(pool, "backup pool")
    slots = sorted(int(path.name) for path in pool.iterdir() if path.name.isdigit())
    for path in pool.iterdir():
        if not path.name.isdigit():
            fail(f"backup pool contains unexpected path: {path.name}")
        slot = int(path.name)
        if slot < 0 or slot >= MAX_BACKUPS:
            fail(f"backup pool contains invalid slot: {path.name}")
        require_owner_private_directory(path, f"backup slot {path.name}")
    if not slots:
        return 0
    return (slots[-1] + 1) % MAX_BACKUPS


def backup_transaction_dir(pool: Path, slot: int, label: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix=f".{slot}.{label}.", dir=str(pool)))
    os.chmod(directory, OWNER_DIR_MODE)
    return directory


def stage_backup(target: Path, stamp: dict[str, Any]) -> BackupTransaction:
    ensure_target_directory(target, create=False)
    pool = ensure_backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        load_backup(target, slot)
    stage_dir = backup_transaction_dir(pool, slot, "stage")
    files_dir = stage_dir / "files"
    files_dir.mkdir(parents=True, mode=OWNER_DIR_MODE)
    os.chmod(files_dir, OWNER_DIR_MODE)
    require_owner_private_directory(stage_dir, f"backup slot {slot} stage")
    require_owner_private_directory(files_dir, f"backup slot {slot} files")
    managed_files: list[dict[str, Any]] = []
    backup_managed_files = stamp_managed_files(stamp)
    try:
        for relative in backup_managed_files:
            if target_file_exists(target, relative):
                content = read_target_file(target, relative, owner_only=False)
                backup_path = files_dir / safe_relative_path(relative)
                atomic_write(backup_path, content)
                managed_files.append(backup_record(relative, content))
            else:
                managed_files.append(backup_record(relative, None))
        stamp_content = read_target_file(
            target,
            STAMP_NAME,
            owner_only=True,
            max_bytes=METADATA_MAX_BYTES,
        )
        envelope = {
            "schema_version": BACKUP_SCHEMA,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "slot": slot,
            "canonical_target": str(target),
            "source_setup_id": stamp["setup_id"],
            "source_permission_profile_id": stamp.get("permission_profile_id"),
            "stamp_schema": stamp["schema_version"],
            "managed_files": managed_files,
            "stamp_sha256": sha256_bytes(stamp_content),
        }
        atomic_write(stage_dir / BACKUP_NAME, canonical_json(envelope))
        validate_backup_slot_dir(
            target,
            stage_dir,
            slot=slot,
            backup_managed_files=backup_managed_files,
        )
        return BackupTransaction(
            slot=slot,
            pool=pool,
            slot_dir=slot_dir,
            stage_dir=stage_dir,
            backup_managed_files=backup_managed_files,
        )
    except BaseException:
        cleanup_transaction_tree(stage_dir, f"backup slot {slot} stage")
        raise


def commit_backup(
    transaction: BackupTransaction,
    target: Path,
    *,
    retire: bool = True,
) -> BackupCommitResult:
    rollback_dir: Path | None = None
    rollback_ready = False
    published = False
    cleanup_pending = False
    deferred_retirement = False
    try:
        if transaction.slot_dir.exists():
            rollback_dir = backup_transaction_dir(transaction.pool, transaction.slot, "rollback")
            rollback_dir.rmdir()
            fsync_directory(transaction.pool)
            os.replace(transaction.slot_dir, rollback_dir)
            rollback_ready = True
            fsync_directory(transaction.pool)
        try:
            os.replace(transaction.stage_dir, transaction.slot_dir)
            published = True
            fsync_directory(transaction.pool)
            validate_backup_slot_dir(
                target,
                transaction.slot_dir,
                slot=transaction.slot,
                backup_managed_files=transaction.backup_managed_files,
            )
        except BaseException:
            if published:
                remove_tree_exact_retry(
                    transaction.slot_dir,
                    f"backup slot {transaction.slot} failed publication",
                )
                published = False
            if (
                rollback_ready
                and rollback_dir is not None
                and lstat_optional(rollback_dir) is not None
            ):
                os.replace(rollback_dir, transaction.slot_dir)
                fsync_directory(transaction.pool)
                rollback_ready = False
                rollback_dir = None
            raise
        if rollback_dir is not None and not retire:
            deferred_retirement = True
            rollback_ready = False
            return BackupCommitResult(
                slot=transaction.slot,
                cleanup_pending=False,
                retirement_dir=rollback_dir,
            )
        if rollback_dir is not None:
            try:
                cleanup_pending = retire_transaction_tree_after_commit(
                    target,
                    rollback_dir,
                    "backup-slot-retirement",
                )
                rollback_ready = False
                rollback_dir = None
            except BaseException:
                if published:
                    remove_tree_exact_retry(
                        transaction.slot_dir,
                        f"backup slot {transaction.slot} failed publication",
                    )
                    published = False
                if rollback_ready and lstat_optional(rollback_dir) is not None:
                    os.replace(rollback_dir, transaction.slot_dir)
                    fsync_directory(transaction.pool)
                    rollback_ready = False
                    rollback_dir = None
                raise
        return BackupCommitResult(slot=transaction.slot, cleanup_pending=cleanup_pending)
    finally:
        if lstat_optional(transaction.stage_dir) is not None:
            cleanup_transaction_tree(
                transaction.stage_dir,
                f"backup slot {transaction.slot} stage",
            )
        if rollback_dir is not None and not rollback_ready and not deferred_retirement:
            cleanup_transaction_tree(
                rollback_dir,
                f"backup slot {transaction.slot} rollback",
            )


def rollback_deferred_backup_commit(
    transaction: BackupTransaction,
    result: BackupCommitResult | None,
) -> None:
    if result is None or result.retirement_dir is None:
        return
    if lstat_optional(transaction.slot_dir) is not None:
        remove_tree_exact_retry(
            transaction.slot_dir,
            f"backup slot {transaction.slot} failed publication",
        )
    if lstat_optional(result.retirement_dir) is None:
        fail(f"backup slot {transaction.slot} rollback retirement is missing")
    os.replace(result.retirement_dir, transaction.slot_dir)
    fsync_directory(transaction.pool)


def write_backup(target: Path, stamp: dict[str, Any]) -> BackupCommitResult:
    transaction = stage_backup(target, stamp)
    try:
        return commit_backup(transaction, target)
    except BaseException:
        if lstat_optional(transaction.stage_dir) is not None:
            cleanup_transaction_tree(transaction.stage_dir, f"backup slot {transaction.slot} stage")
        raise


def load_backup(
    target: Path,
    slot: int,
) -> tuple[dict[str, Any], dict[str, bytes | None], tuple[str, ...]]:
    if slot < 0 or slot >= MAX_BACKUPS:
        fail("--backup must be between 0 and 9")
    ensure_target_directory(target, create=False)
    ensure_backup_pool(target)
    slot_dir = backup_pool(target) / str(slot)
    validate_owner_private_tree(slot_dir, f"backup slot {slot}")
    envelope_path = slot_dir / BACKUP_NAME
    if envelope_path.is_symlink() or not envelope_path.is_file():
        fail(f"backup slot is missing: {slot}")
    envelope = read_json_file(envelope_path, f"backup slot {slot}", owner_only=True)
    if envelope.get("schema_version") == LEGACY_BACKUP_SCHEMA:
        if set(envelope) != LEGACY_BACKUP_KEYS:
            fail("legacy backup envelope has invalid keys")
        if envelope["product_name"] != PRODUCT_NAME:
            fail("legacy backup envelope identity is invalid")
        if not isinstance(envelope["build_version"], str):
            fail("legacy backup envelope build_version is invalid")
        if not isinstance(envelope["slot"], int) or envelope["slot"] != slot:
            fail("legacy backup envelope slot is invalid")
        if not isinstance(envelope["stamp_sha256"], str) or not SHA256_PATTERN.fullmatch(
            envelope["stamp_sha256"]
        ):
            fail("legacy backup envelope stamp_sha256 is invalid")
        backup_managed_files = LEGACY_MANAGED_FILES
        source_permission_profile_id = None
        stamp_schema = LEGACY_STAMP_SCHEMA
        if envelope["source_setup_id"] not in LEGACY_SETUP_IDS:
            fail("legacy backup envelope source_setup_id is invalid")
    else:
        if set(envelope) != BACKUP_KEYS:
            fail("backup envelope has invalid keys")
        if envelope["schema_version"] != BACKUP_SCHEMA or envelope["product_name"] != PRODUCT_NAME:
            fail("backup envelope identity or schema is invalid")
        if not isinstance(envelope["build_version"], str) or envelope["build_version"] != VERSION:
            fail("backup envelope build_version is invalid")
        if not isinstance(envelope["slot"], int) or envelope["slot"] != slot:
            fail("backup envelope slot is invalid")
        if not isinstance(envelope["stamp_sha256"], str) or not SHA256_PATTERN.fullmatch(
            envelope["stamp_sha256"]
        ):
            fail("backup envelope stamp_sha256 is invalid")
        stamp_schema = envelope["stamp_schema"]
        if stamp_schema == STAMP_SCHEMA:
            backup_managed_files = MANAGED_FILES
            if envelope["source_setup_id"] != CONTENT_SETUP_ID:
                fail("backup envelope source_setup_id is invalid")
            source_permission_profile_id = envelope["source_permission_profile_id"]
            if not isinstance(source_permission_profile_id, str):
                fail("backup envelope source_permission_profile_id is invalid")
            validate_permission_profile_id(source_permission_profile_id)
        elif stamp_schema == LEGACY_STAMP_SCHEMA:
            backup_managed_files = LEGACY_MANAGED_FILES
            if envelope["source_setup_id"] not in LEGACY_SETUP_IDS:
                fail("legacy backup envelope source_setup_id is invalid")
            source_permission_profile_id = None
            if envelope["source_permission_profile_id"] is not None:
                fail("legacy backup envelope source_permission_profile_id must be null")
        else:
            fail("backup envelope stamp_schema is invalid")
    if envelope["canonical_target"] != str(target):
        fail("backup belongs to a different canonical target")
    actual_paths = {path.relative_to(slot_dir).as_posix() for path in slot_dir.rglob("*")}
    files: dict[str, bytes | None] = {}
    files_dir = slot_dir / "files"
    require_owner_private_directory(files_dir, f"backup slot {slot} files")
    if envelope["schema_version"] == LEGACY_BACKUP_SCHEMA:
        expected_files = validate_digest_map(
            envelope["managed_files"],
            "legacy backup managed_files",
            backup_managed_files,
        )
        if actual_paths != expected_legacy_backup_slot_paths(expected_files):
            fail("legacy backup slot path set is invalid")
        for relative in backup_managed_files:
            expected = expected_files[relative]
            path = files_dir / safe_relative_path(relative)
            if expected is None:
                if lstat_optional(path) is not None:
                    fail(f"backup file should be absent: {relative}")
                files[relative] = None
                continue
            content, _ = read_regular_file(path, f"backup file {relative}", owner_only=True)
            if len(content) > MANAGED_PAYLOAD_MAX_BYTES:
                fail(f"backup file is too large: {relative}")
            if managed_digest(relative, content) != expected:
                fail(f"backup file digest mismatch: {relative}")
            files[relative] = content
    else:
        expected_records = validate_backup_records(
            envelope["managed_files"],
            "backup managed_files",
            backup_managed_files,
        )
        if actual_paths != expected_backup_slot_paths(expected_records):
            fail("backup slot path set is invalid")
        for relative, record in expected_records.items():
            path = files_dir / safe_relative_path(relative)
            if record["sha256"] is None:
                if lstat_optional(path) is not None:
                    fail(f"backup file should be absent: {relative}")
                files[relative] = None
                continue
            content, _ = read_regular_file(path, f"backup file {relative}", owner_only=True)
            if len(content) > MANAGED_PAYLOAD_MAX_BYTES:
                fail(f"backup file is too large: {relative}")
            if len(content) != record["size"] or sha256_bytes(content) != record["sha256"]:
                fail(f"backup file digest mismatch: {relative}")
            files[relative] = content
    if stamp_schema == STAMP_SCHEMA:
        assert isinstance(source_permission_profile_id, str)
        files[STAMP_NAME] = canonical_json(
            stamp_payload(
                target,
                envelope["source_setup_id"],
                source_permission_profile_id,
                files,
            )
        )
    else:
        files[STAMP_NAME] = canonical_json(
            legacy_stamp_payload(target, envelope["source_setup_id"], files)
        )
    return envelope, files, backup_managed_files


def all_setup_managed_files() -> tuple[str, ...]:
    return tuple(dict.fromkeys((*LEGACY_MANAGED_FILES, *MANAGED_FILES)))


def setup_transaction_snapshot(target: Path) -> dict[str, Any]:
    managed_files = all_setup_managed_files()
    target_info = lstat_optional(target)
    target_mode: int | None = None
    target_inode: int | None = None
    target_mtime_ns: int | None = None
    if target_info is not None:
        target_mode = stat.S_IMODE(target_info.st_mode)
        target_inode = target_info.st_ino
        target_mtime_ns = target_info.st_mtime_ns
    return {
        "target_existed": target_info is not None,
        "target_mode": target_mode,
        "target_inode": target_inode,
        "target_mtime_ns": target_mtime_ns,
        "target_parent": snapshot_directory_identity(target.parent, "setup transaction parent"),
        "managed_files": managed_files,
        "managed": snapshot_managed_files(target, managed_files),
        "backup_pool": snapshot_tree_exact(backup_pool(target)),
        "lock_root": snapshot_tree_exact(lock_root(target)),
        "software_parent": snapshot_tree_manifest(software_parent(target)),
    }


def remove_empty_directory_if_present(path: Path) -> None:
    info = lstat_optional(path)
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"runtime cleanup path must be a real directory: {path}")
    try:
        path.rmdir()
        fsync_directory(path.parent)
    except OSError as exc:
        if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
            return
        raise


def remove_empty_runtime_dirs(target: Path) -> None:
    runtime_root = target / NDDEV_RUNTIME_DIR
    for path in (
        runtime_root / "backups" / "setup",
        runtime_root / "backups",
        runtime_root / "locks",
        runtime_root,
    ):
        remove_empty_directory_if_present(path)


def setup_transaction_matches(target: Path, snapshot: dict[str, Any]) -> bool:
    if setup_transaction_residue(target):
        return False
    if not directory_identity_matches(target.parent, snapshot["target_parent"]):
        return False
    if not snapshot["target_existed"]:
        return lstat_optional(target) is None
    try:
        info = lstat_optional(target)
        if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return False
        if stat.S_IMODE(info.st_mode) != snapshot["target_mode"]:
            return False
        if info.st_ino != snapshot["target_inode"]:
            return False
        if info.st_mtime_ns != snapshot["target_mtime_ns"]:
            return False
        if not managed_snapshot_matches(
            target,
            snapshot["managed"],
            managed_files=snapshot["managed_files"],
        ):
            return False
        if not tree_matches_snapshot(backup_pool(target), snapshot["backup_pool"]):
            return False
        if not tree_matches_snapshot(lock_root(target), snapshot["lock_root"]):
            return False
        if not tree_matches_manifest(software_parent(target), snapshot["software_parent"]):
            return False
    except ManagerError:
        return False
    return True


def ensure_restored_target_directory(target: Path, mode: int, inode: int, mtime_ns: int) -> None:
    info = lstat_optional(target)
    if info is None:
        fail("setup transaction target directory is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("setup transaction target directory changed kind")
    if info.st_ino != inode:
        fail("setup transaction target directory identity changed")
    require_current_user_owned(info, "--target")
    os.chmod(target, mode)
    refreshed = target.lstat()
    os.utime(target, ns=(refreshed.st_atime_ns, mtime_ns))
    fsync_existing_path(target, directory=True)
    fsync_directory(target.parent)


def restore_setup_transaction_once(target: Path, snapshot: dict[str, Any]) -> None:
    if not snapshot["target_existed"]:
        remove_tree_exact(target)
        restore_directory_identity(
            target.parent,
            snapshot["target_parent"],
            "setup transaction parent",
        )
        return
    target_mode = snapshot["target_mode"]
    target_inode = snapshot["target_inode"]
    target_mtime_ns = snapshot["target_mtime_ns"]
    if (
        not isinstance(target_mode, int)
        or not isinstance(target_inode, int)
        or not isinstance(target_mtime_ns, int)
    ):
        fail("setup transaction snapshot target identity is invalid")
    ensure_restored_target_directory(target, target_mode, target_inode, target_mtime_ns)
    restore_snapshot(
        target,
        snapshot["managed"],
        managed_files=snapshot["managed_files"],
    )
    restore_tree_exact_retry(backup_pool(target), snapshot["backup_pool"], "backup pool")
    restore_tree_exact_retry(lock_root(target), snapshot["lock_root"], "lock root")
    remove_empty_runtime_dirs(target)
    os.chmod(target, target_mode)
    refreshed = target.lstat()
    os.utime(target, ns=(refreshed.st_atime_ns, target_mtime_ns))
    fsync_existing_path(target, directory=True)
    fsync_directory(target.parent)
    restore_directory_identity(
        target.parent,
        snapshot["target_parent"],
        "setup transaction parent",
    )


def restore_setup_transaction(target: Path, snapshot: dict[str, Any]) -> None:
    last_error: BaseException | None = None
    for _attempt in range(ROLLBACK_RETRY_ATTEMPTS):
        try:
            restore_setup_transaction_once(target, snapshot)
        except BaseException as exc:
            last_error = exc
        if setup_transaction_matches(target, snapshot):
            return
    raise ManagerError("setup transaction rollback did not restore exact pre-state") from last_error


def restore_setup_transaction_if_changed(target: Path, snapshot: dict[str, Any]) -> None:
    if not setup_transaction_matches(target, snapshot):
        restore_setup_transaction(target, snapshot)


def current_status_body(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        software = software_status_body(target)
        return add_cleanup_pending_fields(
            {
                "state": "missing",
                "target": str(target),
                "setup_id": None,
                "permission_profile_id": None,
                "schema_version": None,
                "migration_required": False,
                "launch_allowed": False,
                "drift": [],
                "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
                "software": software,
            },
            target,
        )
    stamp = load_stamp(target)
    if stamp is None:
        software = software_status_body(target)
        return add_cleanup_pending_fields(
            {
                "state": "unmanaged",
                "target": str(target),
                "setup_id": None,
                "permission_profile_id": None,
                "schema_version": None,
                "migration_required": False,
                "launch_allowed": False,
                "drift": [],
                "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
                "software": software,
            },
            target,
        )
    drift = detect_drift(target, stamp)
    software = software_status_body(target)
    if not stamp_is_current(stamp):
        return add_cleanup_pending_fields(
            {
                "state": "legacy-managed",
                "target": str(target),
                "setup_id": stamp["setup_id"],
                "permission_profile_id": None,
                "schema_version": stamp["schema_version"],
                "build_version": stamp["build_version"],
                "migration_required": True,
                "launch_allowed": False,
                "drift": drift,
                "builder": {
                    "projection": LEGACY_BUILDER_PROJECTION,
                    "enabled": not any(item in drift for item in LEGACY_BUILDER_FILES),
                },
                "software": software,
            },
            target,
        )
    return add_cleanup_pending_fields(
        {
            "state": "managed",
            "target": str(target),
            "setup_id": stamp["setup_id"],
            "permission_profile_id": stamp["permission_profile_id"],
            "schema_version": stamp["schema_version"],
            "build_version": stamp["build_version"],
            "migration_required": False,
            "launch_allowed": not drift and software["state"] == "installed",
            "drift": drift,
            "builder": {
                "projection": BUILDER_PROJECTION,
                "enabled": not any(item in drift for item in BUILDER_FILES),
            },
            "software": software,
        },
        target,
    )


def current_status(target: Path) -> dict[str, Any]:
    require_supported_host_preflight()
    return run_read_only_target_operation(target, current_status_body)


def plan_setup(target: Path, setup_id: str, permission_profile_id: str) -> dict[str, Any]:
    require_supported_host_preflight()

    def plan_body(locked_target: Path) -> dict[str, Any]:
        target = locked_target
        setup = render_setup(setup_id)
        profile = render_permission_profile(permission_profile_id)
        status = current_status_body(target)
        managed_files = MANAGED_FILES
        if status["state"] == "missing":
            operation = "install"
            backup_required = False
        elif status["state"] == "unmanaged":
            operation = "install"
            backup_required = False
        elif status["state"] == "legacy-managed":
            operation = "migrate"
            backup_required = True
        elif (
            status["setup_id"] == setup_id
            and status["permission_profile_id"] == permission_profile_id
        ):
            operation = "update"
            backup_required = False
        else:
            operation = "switch"
            backup_required = True
        if operation in {"install", "update", "switch"}:
            before = snapshot_managed_files(target)
            desired = desired_for_setup(target, setup, profile)
            desired[STAMP_NAME] = canonical_json(
                stamp_payload(target, setup_id, permission_profile_id, desired)
            )
        else:
            stamp = load_stamp(target)
            if stamp is None:
                fail("migrate plan requires a managed target")
            managed_files = tuple(dict.fromkeys((*LEGACY_MANAGED_FILES, *MANAGED_FILES)))
            before = snapshot_managed_files(target, managed_files)
            desired = desired_for_setup(target, setup, profile)
            for relative in managed_files:
                desired.setdefault(relative, None)
            desired[STAMP_NAME] = canonical_json(
                stamp_payload(target, setup.setup_id, profile.profile_id, desired)
            )
        changed = changed_managed_paths(before, desired, managed_files)
        return add_cleanup_pending_fields(
            {
                "operation": operation,
                "target": str(target),
                "setup_id": setup_id,
                "permission_profile_id": permission_profile_id,
                "mutates": False,
                "backup_required": backup_required,
                "changed": changed,
                "state": status["state"],
                "current_setup_id": status["setup_id"],
                "current_permission_profile_id": status["permission_profile_id"],
                "drift": status["drift"],
            },
            target,
        )

    return run_read_only_target_operation(target, plan_body)


def require_clean_managed(target: Path) -> dict[str, Any]:
    stamp = load_stamp(target)
    if stamp is None:
        fail("target is not managed")
    if not stamp_is_current(stamp):
        fail("legacy managed target cannot launch; run migrate first")
    drift = detect_drift(target, stamp)
    if drift:
        fail(f"managed target has drift: {drift}")
    return stamp


def require_clean_any_managed(target: Path) -> dict[str, Any]:
    stamp = load_stamp(target)
    if stamp is None:
        fail("target is not managed")
    drift = detect_drift(target, stamp)
    if drift:
        fail(f"managed target has drift: {drift}")
    return stamp


def mutate_setup(
    target: Path,
    setup_id: str,
    permission_profile_id: str,
    action: str,
) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(
            target,
            create_target=action == "install",
        )
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=action == "install"):
                setup = render_setup(setup_id)
                profile = render_permission_profile(permission_profile_id)
                ensure_target_directory(target, create=True)
                existing_stamp = load_stamp(target)
                if existing_stamp is None:
                    if action == "switch":
                        fail("switch requires a managed target")
                    preflight_unmanaged_target(target)
                else:
                    if not stamp_is_current(existing_stamp):
                        fail(
                            "legacy managed target requires migrate before apply, switch, update, or launch"
                        )
                    if action == "install":
                        fail("install requires an absent managed target; use update or switch")
                    drift = detect_drift(target, existing_stamp)
                    if drift:
                        fail(f"managed target has drift: {drift}")
                backup_slot: int | None = None
                backup_transaction: BackupTransaction | None = None
                before = snapshot_managed_files(target)
                desired = desired_for_setup(target, setup, profile)
                desired[STAMP_NAME] = canonical_json(
                    stamp_payload(target, setup_id, permission_profile_id, desired)
                )
                if existing_stamp is not None and (
                    existing_stamp["setup_id"] != setup_id
                    or existing_stamp["permission_profile_id"] != permission_profile_id
                ):
                    backup_transaction = stage_backup(target, existing_stamp)
                managed_transaction: ManagedStateTransaction | None = None
                backup_result: BackupCommitResult | None = None
                cleanup_pending = False
                try:
                    managed_transaction = begin_managed_state_transaction(target, desired, before)
                    if backup_transaction is not None:
                        backup_result = commit_backup(backup_transaction, target, retire=False)
                        backup_slot = backup_result.slot
                    extra_retirements = []
                    if backup_result is not None and backup_result.retirement_dir is not None:
                        extra_retirements.append(
                            (backup_result.retirement_dir, "backup-slot-retirement")
                        )
                    cleanup_pending = commit_managed_state_transaction(
                        managed_transaction,
                        extra_retirements=extra_retirements,
                    )
                except BaseException:
                    if backup_transaction is not None:
                        rollback_deferred_backup_commit(backup_transaction, backup_result)
                    if managed_transaction is not None:
                        rollback_managed_state_transaction(managed_transaction)
                    else:
                        restore_snapshot(target, before)
                    raise
                changed = changed_managed_paths(before, desired)
                return {
                    "operation": "install" if existing_stamp is None else action,
                    "target": str(target),
                    "setup_id": setup_id,
                    "permission_profile_id": permission_profile_id,
                    "changed": changed,
                    "backup_slot": backup_slot,
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                    "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
                    "engine": {
                        "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                        "status": MANAGED_LAUNCH_ENGINE_STATUS,
                    },
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def update_setup(target: Path) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                stamp = load_stamp(target)
                if stamp is None:
                    fail("update requires a managed target")
                if not stamp_is_current(stamp):
                    fail("legacy managed target requires migrate before update")
                setup = render_setup(stamp["setup_id"])
                profile = render_permission_profile(stamp["permission_profile_id"])
                before = snapshot_managed_files(target)
                desired = desired_for_setup(target, setup, profile)
                desired[STAMP_NAME] = canonical_json(
                    stamp_payload(target, setup.setup_id, profile.profile_id, desired)
                )
                managed_transaction: ManagedStateTransaction | None = None
                cleanup_pending = False
                try:
                    managed_transaction = begin_managed_state_transaction(target, desired, before)
                    cleanup_pending = commit_managed_state_transaction(managed_transaction)
                except BaseException:
                    if managed_transaction is not None:
                        rollback_managed_state_transaction(managed_transaction)
                    else:
                        restore_snapshot(target, before)
                    raise
                changed = changed_managed_paths(before, desired)
                return {
                    "operation": "update",
                    "target": str(target),
                    "setup_id": setup.setup_id,
                    "permission_profile_id": profile.profile_id,
                    "changed": changed,
                    "backup_slot": None,
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                    "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
                    "engine": {
                        "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                        "status": MANAGED_LAUNCH_ENGINE_STATUS,
                    },
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def migrate_setup(target: Path, permission_profile_id: str) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                setup = render_setup(CONTENT_SETUP_ID)
                profile = render_permission_profile(permission_profile_id)
                stamp = load_stamp(target)
                if stamp is None:
                    fail("migrate requires a managed target")
                if stamp_is_current(stamp):
                    fail("target already uses the current managed schema")
                drift = detect_drift(target, stamp)
                if drift:
                    fail(f"managed target has drift: {drift}")
                managed_files = all_setup_managed_files()
                before = snapshot_managed_files(target, managed_files)
                desired = desired_for_setup(target, setup, profile)
                for relative in managed_files:
                    desired.setdefault(relative, None)
                desired[STAMP_NAME] = canonical_json(
                    stamp_payload(target, setup.setup_id, profile.profile_id, desired)
                )
                backup_transaction = stage_backup(target, stamp)
                backup_slot: int | None = None
                managed_transaction: ManagedStateTransaction | None = None
                backup_result: BackupCommitResult | None = None
                cleanup_pending = False
                try:
                    managed_transaction = begin_managed_state_transaction(
                        target,
                        desired,
                        before,
                        managed_files=managed_files,
                    )
                    backup_result = commit_backup(backup_transaction, target, retire=False)
                    backup_slot = backup_result.slot
                    extra_retirements = []
                    if backup_result.retirement_dir is not None:
                        extra_retirements.append(
                            (backup_result.retirement_dir, "backup-slot-retirement")
                        )
                    cleanup_pending = commit_managed_state_transaction(
                        managed_transaction,
                        extra_retirements=extra_retirements,
                    )
                except BaseException:
                    rollback_deferred_backup_commit(backup_transaction, backup_result)
                    if managed_transaction is not None:
                        rollback_managed_state_transaction(managed_transaction)
                    else:
                        restore_snapshot(target, before, managed_files=managed_files)
                    raise
                changed = changed_managed_paths(before, desired, managed_files)
                return {
                    "operation": "migrate",
                    "target": str(target),
                    "from_schema_version": stamp["schema_version"],
                    "from_setup_id": stamp["setup_id"],
                    "setup_id": setup.setup_id,
                    "permission_profile_id": profile.profile_id,
                    "changed": changed,
                    "backup_slot": backup_slot,
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                    "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
                    "engine": {
                        "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                        "status": MANAGED_LAUNCH_ENGINE_STATUS,
                    },
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                stamp = require_clean_any_managed(target)
                _, files, backup_managed_files = load_backup(target, slot)
                active_managed_files = stamp_managed_files(stamp)
                managed_files = tuple(dict.fromkeys((*active_managed_files, *backup_managed_files)))
                for relative in managed_files:
                    files.setdefault(relative, None)
                before = snapshot_managed_files(target, managed_files)
                backup_transaction = stage_backup(target, stamp)
                backup_slot: int | None = None
                managed_transaction: ManagedStateTransaction | None = None
                backup_result: BackupCommitResult | None = None
                cleanup_pending = False
                try:
                    managed_transaction = begin_managed_state_transaction(
                        target,
                        files,
                        before,
                        managed_files=managed_files,
                    )
                    backup_result = commit_backup(backup_transaction, target, retire=False)
                    backup_slot = backup_result.slot
                    extra_retirements = []
                    if backup_result.retirement_dir is not None:
                        extra_retirements.append(
                            (backup_result.retirement_dir, "backup-slot-retirement")
                        )
                    cleanup_pending = commit_managed_state_transaction(
                        managed_transaction,
                        extra_retirements=extra_retirements,
                    )
                except BaseException:
                    rollback_deferred_backup_commit(backup_transaction, backup_result)
                    if managed_transaction is not None:
                        rollback_managed_state_transaction(managed_transaction)
                    else:
                        restore_snapshot(target, before, managed_files=managed_files)
                    raise
                changed = changed_managed_paths(before, files, managed_files)
                restored_stamp = load_stamp(target)
                assert restored_stamp is not None
                return {
                    "operation": "restore",
                    "target": str(target),
                    "setup_id": restored_stamp["setup_id"],
                    "permission_profile_id": restored_stamp.get("permission_profile_id"),
                    "schema_version": restored_stamp["schema_version"],
                    "changed": changed,
                    "backup_slot": backup_slot,
                    "restored_backup": slot,
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                    "migration_required": not stamp_is_current(restored_stamp),
                    "builder": {
                        "projection": BUILDER_PROJECTION
                        if stamp_is_current(restored_stamp)
                        else LEGACY_BUILDER_PROJECTION,
                        "enabled": True,
                    },
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def remove_setup(target: Path) -> dict[str, Any]:
    require_supported_host_preflight()
    with external_target_scope(target) as locked_target:
        target = locked_target
        cleanup_drained = drain_cleanup_pending_before_mutation(target, create_target=False)
        transaction = setup_transaction_snapshot(target)
        try:
            with internal_target_lock(target, create_target=False):
                stamp = require_clean_any_managed(target)
                managed_files = stamp_managed_files(stamp)
                before = snapshot_managed_files(target, managed_files)
                desired: dict[str, bytes | None] = {relative: None for relative in managed_files}
                if target_file_exists(target, SETTINGS):
                    current = read_target_settings_if_present(target)
                    stripped = strip_managed_settings(current)
                    desired[SETTINGS] = canonical_json(stripped) if stripped else None
                desired[STAMP_NAME] = None
                backup_transaction = stage_backup(target, stamp)
                backup_slot: int | None = None
                managed_transaction: ManagedStateTransaction | None = None
                backup_result: BackupCommitResult | None = None
                cleanup_pending = False
                try:
                    managed_transaction = begin_managed_state_transaction(
                        target,
                        desired,
                        before,
                        managed_files=managed_files,
                    )
                    backup_result = commit_backup(backup_transaction, target, retire=False)
                    backup_slot = backup_result.slot
                    extra_retirements = []
                    if backup_result.retirement_dir is not None:
                        extra_retirements.append(
                            (backup_result.retirement_dir, "backup-slot-retirement")
                        )
                    cleanup_pending = commit_managed_state_transaction(
                        managed_transaction,
                        extra_retirements=extra_retirements,
                    )
                except BaseException:
                    rollback_deferred_backup_commit(backup_transaction, backup_result)
                    if managed_transaction is not None:
                        rollback_managed_state_transaction(managed_transaction)
                    else:
                        restore_snapshot(target, before, managed_files=managed_files)
                    raise
                changed = changed_managed_paths(before, desired, managed_files)
                return {
                    "operation": "remove",
                    "target": str(target),
                    "removed_setup_id": stamp["setup_id"],
                    "removed_permission_profile_id": stamp.get("permission_profile_id"),
                    "removed_schema_version": stamp["schema_version"],
                    "changed": changed,
                    "backup_slot": backup_slot,
                    "cleanup_drained": cleanup_drained,
                    "cleanup_pending": cleanup_pending,
                    "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
                }
        except BaseException:
            restore_setup_transaction_if_changed(target, transaction)
            raise


def build_launch_env(target: Path) -> dict[str, str]:
    ensure_target_private_directory(target, NDDEV_RUNTIME_DIR, "launch runtime root")
    home = ensure_target_private_directory(target, f"{NDDEV_RUNTIME_DIR}/home", "launch HOME")
    temp = ensure_target_private_directory(target, f"{NDDEV_RUNTIME_DIR}/tmp", "launch TMPDIR")
    ensure_target_private_directory(target, f"{NDDEV_RUNTIME_DIR}/xdg", "launch XDG root")
    xdg_config = ensure_target_private_directory(
        target,
        f"{NDDEV_RUNTIME_DIR}/xdg/config",
        "launch XDG_CONFIG_HOME",
    )
    xdg_data = ensure_target_private_directory(
        target,
        f"{NDDEV_RUNTIME_DIR}/xdg/data",
        "launch XDG_DATA_HOME",
    )
    xdg_state = ensure_target_private_directory(
        target,
        f"{NDDEV_RUNTIME_DIR}/xdg/state",
        "launch XDG_STATE_HOME",
    )
    xdg_cache = ensure_target_private_directory(
        target,
        f"{NDDEV_RUNTIME_DIR}/xdg/cache",
        "launch XDG_CACHE_HOME",
    )
    logs = ensure_target_private_directory(target, f"{NDDEV_RUNTIME_DIR}/logs", "launch logs")
    env: dict[str, str] = {
        "HOME": str(home),
        "KIRO_HOME": str(target),
        "TMPDIR": str(temp),
        "PATH": TRUSTED_SYSTEM_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_STATE_HOME": str(xdg_state),
        "XDG_CACHE_HOME": str(xdg_cache),
        "KIRO_CHAT_LOG_FILE": str(logs / "kiro-chat.log"),
    }
    if "TERM" in os.environ:
        env["TERM"] = os.environ["TERM"]
    for key in tuple(env):
        if key in SECRET_ENV_NAMES or key.startswith(SECRET_ENV_PREFIXES):
            env.pop(key, None)
    return env


def revalidate_software_executable(target: Path) -> Path:
    stamp = load_software_stamp(target)
    if stamp is None:
        fail("Kiro CLI software stamp is missing")
    executable = software_executable_from_stamp(target, stamp)
    mode_drift = software_installation_mode_drift(target, stamp["executable"]["relative_path"])
    if mode_drift:
        fail(f"Kiro CLI software mutable before launch: {mode_drift}")
    digest, info = digest_regular_file(
        executable,
        f"Kiro CLI executable {executable}",
        owner_only=False,
        max_bytes=SOFTWARE_TREE_MAX_BYTES,
    )
    ensure_not_group_world_writable(info, f"Kiro CLI executable {executable}")
    require_exact_mode(
        info,
        f"Kiro CLI executable {executable}",
        SOFTWARE_IMMUTABLE_EXECUTABLE_MODE,
    )
    if digest != stamp["executable"]["sha256"]:
        fail("Kiro CLI executable digest changed before launch")
    return executable


def require_clean_software(target: Path) -> Path:
    status = software_status_body(target)
    if status["state"] != "installed":
        fail(f"Kiro CLI software is not installed cleanly in target: {status['state']}")
    return revalidate_software_executable(target)


def reject_managed_launch_overrides(child_args: list[str]) -> None:
    if child_args:
        first = child_args[0]
        if first in MANAGED_LAUNCH_BLOCKED_COMMANDS:
            fail(f"launch refuses managed-scope Kiro CLI command: {first}")
    blocked_options = set(MANAGED_LAUNCH_BLOCKED_OPTIONS)
    for argument in child_args:
        if argument == "--":
            continue
        if argument.startswith("--"):
            option = argument.split("=", 1)[0]
            if option in blocked_options:
                fail(f"launch refuses managed-scope Kiro CLI option: {option}")


def resolve_caller_workspace() -> Path:
    try:
        workspace = Path.cwd().resolve(strict=True)
        info = workspace.stat()
    except (FileNotFoundError, OSError) as exc:
        fail(f"cannot resolve caller workspace: {exc}")
    if not stat.S_ISDIR(info.st_mode):
        fail("caller workspace must resolve to a directory")
    if not os.access(workspace, os.R_OK | os.X_OK):
        fail("caller workspace must be readable and searchable")
    return workspace


def launch_scope_status() -> dict[str, Any]:
    return {
        "target_role": "managed-configuration-runtime-home",
        "workspace_source": "captured-caller-current-directory",
        "child_working_directory_policy": "strict-resolved-caller-workspace",
        "native_workspace_argument": None,
    }


def launch(
    target: Path,
    child_args: list[str],
    *,
    workspace: Optional[Path] = None,
) -> int:
    if workspace is None:
        workspace = resolve_caller_workspace()
    require_supported_host_preflight()
    with target_lock(target, create_target=False) as locked_target:
        target = locked_target
        drain_cleanup_pending(target)
        reject_managed_launch_overrides(child_args)
        require_clean_managed(target)
        executable = require_clean_software(target)
        env = build_launch_env(target)
        executable = revalidate_software_executable(target)
        launch_args = [MANAGED_LAUNCH_ENGINE_ARGUMENT, *child_args]
        return subprocess.call(
            [str(executable), *launch_args],
            cwd=str(workspace),
            env=env,
        )


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def wants_json(argv: list[str]) -> bool:
    return "--json" in argv


class JsonBoundaryArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, json_argv: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._json_argv = json_argv

    def error(self, message: str) -> NoReturn:
        if self._json_argv is not None and wants_json(self._json_argv):
            fail(f"argument error: {message}")
        super().error(message)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = JsonBoundaryArgumentParser(description=__doc__, json_argv=raw_argv)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=lambda *args, **kwargs: JsonBoundaryArgumentParser(
            *args,
            json_argv=raw_argv,
            **kwargs,
        ),
    )

    list_parser = subparsers.add_parser("list", help="list available setups")
    list_parser.add_argument("--json", action="store_true")

    for name in ("status", "remove", "update", "software-status", "software-remove"):
        command = subparsers.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    for name in ("plan", "install", "apply", "switch"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", default=CONTENT_SETUP_ID)
        command.add_argument("--profile", default=DEFAULT_PERMISSION_PROFILE_ID)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--target")
    migrate_parser.add_argument("--profile", default=DEFAULT_PERMISSION_PROFILE_ID)
    migrate_parser.add_argument("--json", action="store_true")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True, type=int)
    restore_parser.add_argument("--target")
    restore_parser.add_argument("--json", action="store_true")

    for name in ("software-probe", "software-install", "software-update"):
        command = subparsers.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(raw_argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
        caller_workspace = resolve_caller_workspace() if args.command == "launch" else None
        if command_requires_supported_host(args.command):
            require_supported_host_preflight()
        if args.command == "list":
            emit(
                {
                    "setups": list_setups(),
                    "permission_profiles": list_permission_profiles(),
                    "default_setup": CONTENT_SETUP_ID,
                    "default_permission_profile": DEFAULT_PERMISSION_PROFILE_ID,
                },
                as_json=args.json,
            )
            return 0
        if args.command == "status":
            emit(
                {
                    **current_status(resolve_target(args.target)),
                    "launch_scope": launch_scope_status(),
                },
                as_json=args.json,
            )
            return 0
        if args.command == "software-status":
            emit(software_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "plan":
            emit(
                plan_setup(resolve_target(args.target), args.setup, args.profile),
                as_json=args.json,
            )
            return 0
        if args.command in {"install", "apply", "switch"}:
            action = "install" if args.command == "apply" else args.command
            emit(
                mutate_setup(resolve_target(args.target), args.setup, args.profile, action),
                as_json=args.json,
            )
            return 0
        if args.command == "migrate":
            emit(
                migrate_setup(resolve_target(args.target), args.profile),
                as_json=args.json,
            )
            return 0
        if args.command == "update":
            emit(update_setup(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "restore":
            emit(restore_backup(resolve_target(args.target), args.backup), as_json=args.json)
            return 0
        if args.command == "remove":
            emit(remove_setup(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "software-probe":
            emit(
                software_probe(
                    resolve_target(args.target),
                    platform_arg=None,
                    architecture_arg=None,
                    libc_arg=None,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "software-install":
            emit(
                software_install(
                    resolve_target(args.target),
                    platform_arg=None,
                    architecture_arg=None,
                    libc_arg=None,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "software-update":
            emit(
                software_update(
                    resolve_target(args.target),
                    platform_arg=None,
                    architecture_arg=None,
                    libc_arg=None,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "software-remove":
            emit(software_remove(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "launch":
            child_args = list(args.child_args)
            if child_args and child_args[0] == "--":
                child_args = child_args[1:]
            if caller_workspace is None:
                fail("caller workspace was not resolved")
            return launch(
                resolve_target(args.target),
                child_args,
                workspace=caller_workspace,
            )
        fail(f"unsupported command: {args.command}")
    except ManagerError as exc:
        if wants_json(raw_argv):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"nddev-kiro-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
