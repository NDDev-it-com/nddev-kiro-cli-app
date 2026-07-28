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
import ctypes
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
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-kiro-cli-app"
STAMP_NAME = "NDDEV-KIRO-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-KIRO-CLI-BACKUP.json"
STAMP_SCHEMA = 2
LEGACY_STAMP_SCHEMA = 1
BACKUP_SCHEMA = 2
LEGACY_BACKUP_SCHEMA = 1
MAX_BACKUPS = 10
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
EXTERNAL_LOCK_NAME_SUFFIX = ".lock"
EXTERNAL_PRODUCT_LOCK_NAME = "product.lock"
EXTERNAL_LOCK_STAGE_NAME_EXTRA_PATTERN = re.compile(r"[1-9][0-9]{0,18}\.[1-9][0-9]{0,18}\Z")
EXTERNAL_TARGET_LOCK_NAME_PATTERN = re.compile(r"[0-9a-f]{64}\.lock\Z")
EXTERNAL_TARGET_LOCK_STAGE_NAME_PATTERN = re.compile(
    r"\.([0-9a-f]{64}\.lock)\.nddev\.tmp\.([1-9][0-9]{0,18}\.[1-9][0-9]{0,18})\Z"
)
EXTERNAL_LOCK_DIRECTORY_SCAN_MAX_ENTRIES = 4096
EXTERNAL_LOCK_STAGE_ACCEPT_MAX = 16
AT_FDCWD_BY_SYSTEM = {"darwin": -2, "linux": -100}
RENAME_EXCL_DARWIN = 0x00000004
RENAME_NOREPLACE_LINUX = 1
RENAMEAT2_SYSCALL_BY_MACHINE = {
    "amd64": 316,
    "x86_64": 316,
    "aarch64": 276,
    "arm64": 276,
}
BACKUP_RUNTIME_DIR = ".nddev-runtime/backups/setup"
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
    "--cwd",
    "--directory",
    "--folder",
    "--no-interactive",
    "--project",
    "--require-mcp-startup",
    "--trust-all-tools",
    "--trust-tools",
    "--v3",
    "--workspace",
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


@dataclass(frozen=True)
class LockStage:
    path: Path
    dev: int
    ino: int
    mode: int
    uid: int | None
    nlink: int
    size: int
    mtime_ns: int
    payload: bytes


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


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open directory for durability sync {path}: {exc}")
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"cannot sync directory {path}: {exc}")
    finally:
        os.close(descriptor)


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
    except FileNotFoundError:
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


def normalize_platform_name(value: str | None) -> str:
    raw = value or platform.system().lower()
    normalized = raw.lower()
    if normalized in {"darwin", "mac", "macos"}:
        return "macos"
    if normalized in {"linux", "ubuntu"}:
        return "linux"
    fail(f"unsupported software platform: {raw}")


def normalize_architecture(value: str | None, os_name: str) -> str:
    if os_name == "macos":
        if value in {None, "", "universal"}:
            return "universal"
        if value in {"x86_64", "amd64", "arm64", "aarch64"}:
            return "universal"
        fail(f"unsupported macOS architecture: {value}")
    raw = value or platform.machine().lower()
    if raw in {"x86_64", "amd64"}:
        return "x86_64"
    if raw in {"arm64", "aarch64"}:
        return "aarch64"
    fail(f"unsupported Linux architecture: {raw}")


def detect_linux_libc() -> str:
    if platform.system().lower() != "linux":
        return "glibc"
    libc_name, libc_version = platform.libc_ver()
    if libc_name == "glibc" and libc_version:
        major_text, _, minor_text = libc_version.partition(".")
        try:
            major = int(major_text)
            minor = int(minor_text or "0")
        except ValueError:
            return "musl"
        minimum_minor = 39 if normalize_architecture(None, "linux") == "aarch64" else 34
        if major > 2 or (major == 2 and minor >= minimum_minor):
            return "glibc"
        return "musl"
    return "musl"


def normalize_libc(value: str | None, os_name: str) -> str | None:
    if os_name != "linux":
        if value not in {None, ""}:
            fail("--libc is only valid for Linux software installs")
        return None
    if value in {None, ""}:
        return detect_linux_libc()
    if value in {"glibc", "gnu"}:
        return "glibc"
    if value == "musl":
        return "musl"
    fail(f"unsupported Linux libc variant: {value}")


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


def package_matches(package: dict[str, Any], os_name: str, architecture: str, libc: str | None) -> bool:
    if package.get("os") != os_name or package.get("architecture") != architecture:
        return False
    if os_name == "macos":
        return package.get("fileType") == "dmg" and package.get("variant") == "full"
    if package.get("fileType") != "zip" or package.get("variant") != "headless":
        return False
    download = str(package.get("download", ""))
    is_musl = "-musl." in download
    return is_musl if libc == "musl" else not is_musl


def select_baseline_package(os_name: str, architecture: str, libc: str | None) -> SoftwarePackage:
    matches = [
        package
        for package in baseline_packages()
        if package_matches(package, os_name, architecture, libc)
    ]
    if len(matches) != 1:
        fail(f"cannot select exact Kiro CLI package for {os_name}/{architecture}/{libc}")
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
        os_name=os_name,
        architecture=architecture,
        libc=libc,
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
    if optional_owner_private_directory(target / NDDEV_RUNTIME_DIR, "software runtime directory") is None:
        return "absent"
    software_modes = {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE}
    if optional_owned_directory_modes(software_parent(target), "software parent", software_modes) is None:
        return "absent"
    if optional_owned_directory_modes(software_root(target), "software root", software_modes) is None:
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


def harden_software_tree(root: Path, executable_relative: str) -> None:
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
        return {
            "state": "missing",
            "target": str(target),
            "version": expected_runtime_version(),
            "executable": None,
            "drift": [],
            "executes_binary": False,
        }
    if presence == "absent":
        return {
            "state": "absent",
            "target": str(target),
            "version": expected_runtime_version(),
            "executable": None,
            "drift": [],
            "executes_binary": False,
        }
    root = software_root(target)
    stamp, stamp_issue = load_software_stamp_for_status(target)
    if stamp_issue is not None:
        return {
            "state": "partial",
            "target": str(target),
            "version": expected_runtime_version(),
            "executable": None,
            "drift": [f"software stamp invalid: {stamp_issue}"],
            "executes_binary": False,
        }
    if stamp is None:
        return {
            "state": "partial",
            "target": str(target),
            "version": expected_runtime_version(),
            "executable": None,
            "drift": ["software stamp missing"],
            "executes_binary": False,
        }
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
    return {
        "state": state,
        "target": str(target),
        "version": stamp["version"],
        "package": stamp["package"],
        "executable": str(software_executable_from_stamp(target, stamp)),
        "drift": drift,
        "executes_binary": False,
    }


def preflight_software_target(target: Path, *, allow_partial: bool) -> dict[str, Any]:
    validated_transaction_parent(target)
    status = software_status_body(target)
    if status["state"] in {"partial", "drift", "needs-update"} and not allow_partial:
        fail("software target needs update or repair; run software-update")
    return status


def software_status(target: Path) -> dict[str, Any]:
    with external_target_lock(target):
        return software_status_body(target)


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


@contextlib.contextmanager
def software_stage(target: Path) -> Iterator[Path]:
    stage = create_transaction_dir(target, "software-stage")
    try:
        yield stage
    finally:
        shutil.rmtree(stage, ignore_errors=True)


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
                if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
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


def prepare_macos_software_root(stage: Path, artifact: Path, package: SoftwarePackage) -> tuple[Path, str]:
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
            "#!/bin/sh\n"
            "set -eu\n"
            f'exec "$(dirname "$0")/../{apps[0].name}/{cli_path}" "$@"\n'
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


def prepare_software_root(stage: Path, artifact: Path, package: SoftwarePackage) -> tuple[Path, str]:
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


def install_prepared_software_root(
    target: Path,
    prepared: Path,
    *,
    allow_existing: bool,
) -> dict[str, Any]:
    created_dirs: list[str] = []
    rollback_parent: Path | None = None
    rollback_root: Path | None = None
    installed_new_root = False
    final_root = software_root(target)
    try:
        target_info = lstat_optional(target)
        if target_info is None:
            target.mkdir(mode=OWNER_DIR_MODE)
            os.chmod(target, OWNER_DIR_MODE)
            created_dirs.append(str(target))
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
        if lstat_optional(software_parent_path) is None:
            ensure_directory_chain(software_parent_path, created_dirs, "software parent")
        else:
            make_software_parent_mutable(target)
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
            rollback_parent = create_transaction_dir(target, "software-rollback")
            rollback_root = rollback_parent / "previous"
            os.replace(final_root, rollback_root)
        os.replace(prepared, final_root)
        installed_new_root = True
        stamp = read_json_file(final_root / SOFTWARE_STAMP_NAME, "software stamp", owner_only=True)
        executable_relative = stamp["executable"]["relative_path"]
        harden_installed_software(target, executable_relative)
        stamp = load_software_stamp(target)
        assert stamp is not None
        if rollback_parent is not None:
            if rollback_root is not None:
                make_software_tree_mutable(rollback_root)
            shutil.rmtree(rollback_parent)
            rollback_parent = None
        return {
            "target": str(target),
            "version": stamp["version"],
            "package": stamp["package"],
            "executable": str(software_executable_from_stamp(target, stamp)),
            "rollback": {
                "mode": "rename-restore",
                "created_dirs": created_dirs,
            },
        }
    except BaseException:
        with contextlib.suppress(ManagerError, OSError):
            make_software_parent_mutable(target)
        if installed_new_root:
            final_info = lstat_optional(final_root)
            if final_info is not None and stat.S_ISDIR(final_info.st_mode) and not stat.S_ISLNK(
                final_info.st_mode
            ):
                with contextlib.suppress(ManagerError, OSError):
                    make_software_tree_mutable(final_root)
                shutil.rmtree(final_root, ignore_errors=True)
        if rollback_root is not None and lstat_optional(rollback_root) is not None:
            os.replace(rollback_root, final_root)
            with contextlib.suppress(ManagerError, OSError):
                stamp = load_software_stamp(target)
                if stamp is not None:
                    harden_installed_software(target, stamp["executable"]["relative_path"])
        if rollback_parent is not None:
            if rollback_root is not None:
                with contextlib.suppress(ManagerError, OSError):
                    make_software_tree_mutable(rollback_root)
            shutil.rmtree(rollback_parent, ignore_errors=True)
        for directory in reversed(created_dirs):
            with contextlib.suppress(OSError):
                Path(directory).rmdir()
        raise


def select_software_package(
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> SoftwarePackage:
    os_name = normalize_platform_name(platform_arg)
    architecture = normalize_architecture(architecture_arg, os_name)
    libc = normalize_libc(libc_arg, os_name)
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
        shutil.rmtree(stage, ignore_errors=True)
        raise


def software_probe(
    target: Path,
    *,
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
) -> dict[str, Any]:
    with external_target_lock(target):
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
    with target_lock(target, create_target=True):
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
            result = install_prepared_software_root(target, prepared, allow_existing=False)
        finally:
            shutil.rmtree(prepared, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)
    return {
        "operation": "software-install",
        "changed": True,
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
    with target_lock(target, create_target=False):
        status = preflight_software_target(target, allow_partial=True)
        if status["state"] in {"missing", "absent"}:
            fail("Kiro CLI software is absent; run software-install first")
        if status["state"] == "installed":
            return {
                "operation": "software-update",
                "target": str(target),
                "changed": False,
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
                return {
                    "operation": "software-update",
                    "target": str(target),
                    "changed": False,
                    "version": race_status["version"],
                    "package": race_status["package"],
                    "executable": race_status["executable"],
                    "rollback": {"mode": "none", "created_dirs": []},
                    "official_vendor_installer": official_vendor_installer_record(),
                }
            result = install_prepared_software_root(target, prepared, allow_existing=True)
        finally:
            shutil.rmtree(prepared, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)
    return {
        "operation": "software-update",
        "changed": True,
        **result,
        "official_vendor_installer": official_vendor_installer_record(),
    }


def software_remove(target: Path) -> dict[str, Any]:
    with target_lock(target, create_target=False):
        status = software_status_body(target)
        root = software_root(target)
        if status["state"] in {"missing", "absent"}:
            return {
                "operation": "software-remove",
                "target": str(target),
                "changed": False,
                "removed_state": status["state"],
            }
        require_owned_directory_modes(
            root,
            "software root",
            {OWNER_DIR_MODE, SOFTWARE_IMMUTABLE_DIR_MODE},
        )
        make_software_parent_mutable(target)
        make_software_tree_mutable(root)
        shutil.rmtree(root)
        with contextlib.suppress(OSError):
            root.parent.rmdir()
        return {
            "operation": "software-remove",
            "target": str(target),
            "changed": True,
            "removed_state": status["state"],
        }


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
            f"permission profile {profile_id}/permissions.yaml "
            "must be non-empty LF-terminated text"
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
    require_real_directory_ancestors(path.parent, "canonical --target parent")
    parent = path.parent.resolve(strict=True)
    return parent / path.name


def resolve_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    target = canonical_target_identity(expanded)
    if target == Path(target.anchor):
        fail("filesystem root cannot be a target")
    return target


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
            content = read_target_file(target, relative, owner_only=False)
            snapshot[relative] = FileSnapshot(content=content, digest=sha256_bytes(content))
        else:
            snapshot[relative] = FileSnapshot(content=None, digest=None)
    return snapshot


def assert_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, expected in snapshot.items():
        exists = ensure_target_directory(target, create=False) and target_file_exists(
            target, relative
        )
        if not exists:
            actual = FileSnapshot(content=None, digest=None)
        else:
            content = read_target_file(target, relative, owner_only=False)
            actual = FileSnapshot(content=content, digest=sha256_bytes(content))
        if actual.digest != expected.digest:
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


def atomic_write(path: Path, content: bytes) -> None:
    make_parent_directories(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temporary, OWNER_FILE_MODE)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_empty_managed_parents(target: Path, relative: str) -> None:
    current = (target / safe_relative_path(relative)).parent
    while current != target and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def replace_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    expected: dict[str, FileSnapshot] | None,
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
    remove_empty_parents: bool = True,
) -> None:
    ensure_target_directory(target, create=True)
    if expected is not None:
        assert_snapshot(target, expected)
    for relative in (*managed_files, STAMP_NAME):
        path = target_path(target, relative)
        content = desired.get(relative)
        if content is None:
            if path.exists():
                require_regular_file(path, f"managed path {path}", owner_only=False)
                path.unlink()
                if remove_empty_parents:
                    remove_empty_managed_parents(target, relative)
            continue
        atomic_write(path, content)
    if expected is not None:
        for relative in (*managed_files, STAMP_NAME):
            target_file_exists(target, relative)


def restore_snapshot(
    target: Path,
    snapshot: dict[str, FileSnapshot],
    *,
    managed_files: tuple[str, ...] = MANAGED_FILES,
) -> None:
    desired = {relative: item.content for relative, item in snapshot.items()}
    replace_managed_state(target, desired, None, managed_files=managed_files)


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


def restore_directory_metadata(path: Path, before: os.stat_result, label: str) -> None:
    flags = os.O_RDONLY
    if not hasattr(os, "O_DIRECTORY"):
        fail(f"{label} fd-bound directory restore is unsupported")
    flags |= os.O_DIRECTORY
    if not hasattr(os, "O_NOFOLLOW"):
        fail(f"{label} no-follow directory restore is unsupported")
    flags |= os.O_NOFOLLOW
    if not hasattr(os, "O_CLOEXEC"):
        fail(f"{label} close-on-exec directory restore is unsupported")
    flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open {label} for metadata restore: {exc}")
    before_mode = stat.S_IMODE(before.st_mode)
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISDIR(current.st_mode):
            fail(f"{label} must be a real directory")
        if identity_of(current) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} identity changed")
        if stat.S_IMODE(current.st_mode) != before_mode:
            if not current_user_owns(current):
                fail(f"{label} mode changed and cannot be restored")
            try:
                os.fchmod(descriptor, before_mode)
            except OSError as exc:
                fail(f"cannot restore {label} mode: {exc}")
        if os.utime not in os.supports_fd:
            fail(f"{label} fd-bound timestamp restore is unsupported")
        try:
            os.utime(descriptor, ns=(before.st_atime_ns, before.st_mtime_ns))
        except OSError as exc:
            fail(f"cannot restore {label} timestamps: {exc}")
        restored_fd = os.fstat(descriptor)
        if not stat.S_ISDIR(restored_fd.st_mode):
            fail(f"{label} must remain a real directory")
        if identity_of(restored_fd) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} identity changed")
    finally:
        os.close(descriptor)
    restored = require_directory(path, label)
    if identity_of(restored) != identity_of(before):
        raise ConcurrentTargetChange(f"{label} identity changed")
    if stat.S_IMODE(restored.st_mode) != before_mode:
        fail(f"{label} mode was not restored")
    if restored.st_atime_ns != before.st_atime_ns or restored.st_mtime_ns != before.st_mtime_ns:
        fail(f"{label} timestamps were not restored")


def bootstrap_product_root_path() -> Path:
    system_root = require_bootstrap_system_root(bootstrap_system_temp_root())
    uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    return system_root / f"{PRODUCT_NAME}-{uid}"


def bootstrap_product_root(*, create: bool = True) -> Path | None:
    system_root = require_bootstrap_system_root(bootstrap_system_temp_root())
    system_before = system_root.lstat()
    uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    root = system_root / f"{PRODUCT_NAME}-{uid}"
    info = lstat_optional(root)
    created = False
    if info is None:
        if not create:
            return None
        try:
            root.mkdir(mode=OWNER_DIR_MODE)
            created = True
        except FileExistsError:
            pass
    if created:
        try:
            os.chmod(root, OWNER_DIR_MODE)
            restore_directory_metadata(system_root, system_before, "bootstrap system temp root")
            fsync_directory(system_root)
        except BaseException:
            with contextlib.suppress(OSError):
                root.rmdir()
            with contextlib.suppress(ManagerError):
                restore_directory_metadata(system_root, system_before, "bootstrap system temp root")
                fsync_directory(system_root)
            raise
    require_owner_private_directory(root, "bootstrap product lock root")
    return root


def external_lock_digest(target: Path) -> str:
    canonical_target = canonical_target_identity(target)
    return sha256_bytes(f"{PRODUCT_NAME}\0{canonical_target}".encode("utf-8"))


def external_lock_path(target: Path) -> Path:
    root = bootstrap_product_root()
    assert root is not None
    return root / f"{external_lock_digest(target)}{EXTERNAL_LOCK_NAME_SUFFIX}"


def external_lock_binding(target: Path) -> dict[str, Any]:
    canonical_target = canonical_target_identity(target)
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "canonical_target": str(canonical_target),
        "lock_digest": external_lock_digest(canonical_target),
    }


def external_product_lock_path(root: Path) -> Path:
    return root / EXTERNAL_PRODUCT_LOCK_NAME


def external_product_lock_binding(root: Path) -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "anchor_kind": "product",
        "lock_root": str(root),
    }


def external_anchor_binding(path: Path, target: Path | None) -> dict[str, Any]:
    if target is None:
        return external_product_lock_binding(path.parent)
    payload = external_lock_binding(target)
    payload["anchor_kind"] = "target"
    return payload


def lexical_canonical_target_valid(value: str) -> bool:
    target = Path(value)
    if not target.is_absolute():
        return False
    if target.name in {"", ".", ".."}:
        return False
    return not any(part in {"", ".", ".."} for part in target.parts)


def external_lock_digest_for_canonical_text(canonical_target: str) -> str:
    return sha256_bytes(f"{PRODUCT_NAME}\0{canonical_target}".encode("utf-8"))


def validate_external_target_lock_content(lock: Path, content: bytes, label: str) -> bytes:
    if EXTERNAL_TARGET_LOCK_NAME_PATTERN.fullmatch(lock.name) is None:
        fail(f"{label} filename is not a canonical target lock")
    binding = parse_json_object(content, label)
    expected_keys = {"schema_version", "product_name", "canonical_target", "lock_digest"}
    if set(binding) != expected_keys:
        fail(f"{label} binding keys are invalid")
    if binding["schema_version"] != EXTERNAL_LOCK_SCHEMA or binding["product_name"] != PRODUCT_NAME:
        fail(f"{label} binding identity or schema is invalid")
    canonical_target = binding["canonical_target"]
    if not isinstance(canonical_target, str) or not lexical_canonical_target_valid(canonical_target):
        fail(f"{label} canonical target is invalid")
    digest = external_lock_digest_for_canonical_text(canonical_target)
    if not isinstance(binding["lock_digest"], str):
        fail(f"{label} binding digest is invalid")
    if binding["lock_digest"] != digest:
        fail(f"{label} binding digest mismatch")
    if lock.name != f"{digest}{EXTERNAL_LOCK_NAME_SUFFIX}":
        fail(f"{label} filename digest mismatch")
    expected = {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "canonical_target": canonical_target,
        "lock_digest": digest,
    }
    encoded = canonical_json(expected)
    if content != encoded:
        fail(f"{label} binding is not canonical")
    return encoded


def external_lock_open_flags() -> int:
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def external_lock_stage_prefix(lock: Path) -> str:
    return f".{lock.name}.nddev.tmp."


def external_lock_stage_name_valid(lock: Path, name: str) -> bool:
    prefix = external_lock_stage_prefix(lock)
    if not name.startswith(prefix):
        return False
    return EXTERNAL_LOCK_STAGE_NAME_EXTRA_PATTERN.fullmatch(name[len(prefix) :]) is not None


def external_lock_namespace_snapshot(root: Path) -> tuple[Any, ...]:
    info = lstat_optional(root)
    if info is None:
        return ("missing",)
    require_owner_private_directory(root, "bootstrap product lock root")
    entries: list[tuple[Any, ...]] = [
        (
            ".",
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_uid if hasattr(info, "st_uid") else None,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
        )
    ]
    count = 0
    try:
        iterator = root.iterdir()
        for entry in iterator:
            count += 1
            if count > EXTERNAL_LOCK_DIRECTORY_SCAN_MAX_ENTRIES:
                fail("bootstrap product lock root has too many entries")
            child = entry.lstat()
            entries.append(
                (
                    entry.name,
                    child.st_dev,
                    child.st_ino,
                    child.st_mode,
                    child.st_uid if hasattr(child, "st_uid") else None,
                    child.st_nlink,
                    child.st_size,
                    child.st_mtime_ns,
                    child.st_ctime_ns,
                )
            )
    except OSError as exc:
        fail(f"cannot inspect bootstrap product lock root: {exc}")
    return tuple(sorted(entries))


def validate_external_lock_stage(lock: Path, expected: bytes, entry: Path) -> LockStage:
    content, info = read_regular_file(
        entry,
        "external lock publication stage",
        owner_only=True,
        max_bytes=METADATA_MAX_BYTES,
    )
    if content != expected:
        fail("external lock publication stage binding mismatch")
    return LockStage(
        path=entry,
        dev=info.st_dev,
        ino=info.st_ino,
        mode=info.st_mode,
        uid=info.st_uid if hasattr(info, "st_uid") else None,
        nlink=info.st_nlink,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        payload=content,
    )


def revalidate_external_lock_stage(stage: LockStage, expected: bytes) -> None:
    content, _ = read_regular_file(
        stage.path,
        "external lock publication stage",
        owner_only=True,
        max_bytes=METADATA_MAX_BYTES,
    )
    if content != expected:
        fail("external lock publication stage binding mismatch")
    validate_external_lock_stage_identity(stage)


def validate_external_lock_stage_identity(stage: LockStage) -> None:
    try:
        info = stage.path.lstat()
    except FileNotFoundError:
        raise ConcurrentTargetChange("external lock publication stage disappeared")
    if (
        info.st_dev != stage.dev
        or info.st_ino != stage.ino
        or info.st_mode != stage.mode
        or (info.st_uid if hasattr(info, "st_uid") else None) != stage.uid
        or info.st_nlink != stage.nlink
        or info.st_size != stage.size
        or info.st_mtime_ns != stage.mtime_ns
    ):
        raise ConcurrentTargetChange("external lock publication stage changed after validation")


def validate_external_target_lock_file(lock: Path) -> None:
    content, _ = read_regular_file(
        lock,
        "external target lock",
        owner_only=True,
        max_bytes=METADATA_MAX_BYTES,
    )
    validate_external_target_lock_content(lock, content, "external target lock")


def validate_external_target_lock_stage(root: Path, name: str, entry: Path) -> str:
    match = EXTERNAL_TARGET_LOCK_STAGE_NAME_PATTERN.fullmatch(name)
    if match is None:
        fail("external lock publication stage name is not attributable")
    lock = root / match.group(1)
    content, _ = read_regular_file(
        entry,
        "external target lock publication stage",
        owner_only=True,
        max_bytes=METADATA_MAX_BYTES,
    )
    validate_external_target_lock_content(lock, content, "external target lock publication stage")
    return lock.name


def validate_external_lock_namespace(root: Path, product_expected: bytes) -> None:
    require_owner_private_directory(root, "bootstrap product lock root")
    product_lock = external_product_lock_path(root)
    stage_counts: dict[str, int] = {}
    product_seen = False
    count = 0
    try:
        entries = root.iterdir()
        for entry in entries:
            count += 1
            if count > EXTERNAL_LOCK_DIRECTORY_SCAN_MAX_ENTRIES:
                fail("bootstrap product lock root has too many entries")
            name = entry.name
            if name == EXTERNAL_PRODUCT_LOCK_NAME:
                content, _ = read_regular_file(
                    entry,
                    "external product lock",
                    owner_only=True,
                    max_bytes=METADATA_MAX_BYTES,
                )
                if content != product_expected:
                    fail("external product lock binding mismatch")
                product_seen = True
                continue
            if name.startswith(external_lock_stage_prefix(product_lock)):
                if not external_lock_stage_name_valid(product_lock, name):
                    fail("external product lock publication stage name is not bounded")
                validate_external_lock_stage(product_lock, product_expected, entry)
                stage_counts[product_lock.name] = stage_counts.get(product_lock.name, 0) + 1
                continue
            if EXTERNAL_TARGET_LOCK_NAME_PATTERN.fullmatch(name) is not None:
                validate_external_target_lock_file(entry)
                continue
            if name.startswith("."):
                lock_name = validate_external_target_lock_stage(root, name, entry)
                stage_counts[lock_name] = stage_counts.get(lock_name, 0) + 1
                continue
            fail("unknown external lock namespace entry")
    except OSError as exc:
        fail(f"cannot inspect bootstrap product lock root: {exc}")
    if not product_seen:
        fail("external product lock is missing")
    if any(total > EXTERNAL_LOCK_STAGE_ACCEPT_MAX for total in stage_counts.values()):
        fail("external lock has too many publication stages")


def require_external_lock_stages(lock: Path, expected: bytes) -> list[LockStage]:
    prefix = external_lock_stage_prefix(lock)
    stages: list[LockStage] = []
    try:
        entries = lock.parent.iterdir()
    except FileNotFoundError:
        return []
    except OSError as exc:
        fail(f"cannot inspect external target lock publication stages: {exc}")
    count = 0
    try:
        for entry in entries:
            count += 1
            if count > EXTERNAL_LOCK_DIRECTORY_SCAN_MAX_ENTRIES:
                fail("bootstrap product lock root has too many entries")
            if not entry.name.startswith(prefix):
                continue
            if not external_lock_stage_name_valid(lock, entry.name):
                fail("external lock publication stage name is not bounded")
            stages.append(validate_external_lock_stage(lock, expected, entry))
    except OSError as exc:
        fail(f"cannot inspect external target lock publication stages: {exc}")
    if len(stages) > EXTERNAL_LOCK_STAGE_ACCEPT_MAX:
        fail("external lock has too many publication stages")
    return sorted(stages, key=lambda item: item.path.name)


def restore_external_lock_parent_metadata(parent: Path, before: os.stat_result) -> None:
    restore_directory_metadata(parent, before, "external target lock parent")


def rollback_empty_product_root(
    root: Path,
    system_root: Path,
    system_before: os.stat_result,
) -> None:
    info = lstat_optional(root)
    if info is not None:
        require_owner_private_directory(root, "bootstrap product lock root")
        try:
            next(root.iterdir())
        except StopIteration:
            root.rmdir()
        except OSError as exc:
            fail(f"cannot inspect bootstrap product lock root for rollback: {exc}")
        else:
            fail("bootstrap product lock root is not empty after failed product anchor publication")
    restore_directory_metadata(system_root, system_before, "bootstrap system temp root")
    fsync_directory(system_root)


def rename_no_replace(source: Path, destination: Path, label: str) -> bool:
    system = platform.system().lower()
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if system == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            AT_FDCWD_BY_SYSTEM["darwin"],
            source_bytes,
            AT_FDCWD_BY_SYSTEM["darwin"],
            destination_bytes,
            RENAME_EXCL_DARWIN,
        )
    elif system == "linux":
        machine = platform.machine().lower()
        syscall_number = RENAMEAT2_SYSCALL_BY_MACHINE.get(machine)
        if syscall_number is None:
            fail(f"{label} no-replace publication is unsupported on this architecture")
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        result = syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(source_bytes),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(RENAME_NOREPLACE_LINUX),
        )
    else:
        fail(f"{label} no-replace publication is unsupported on this platform")
    if result == 0:
        return True
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        return False
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
        fail(f"{label} no-replace publication primitive is unavailable")
    fail(f"{label} no-replace publication failed: {os.strerror(error)}")


def recover_external_lock_publication_stage(lock: Path, expected: bytes, stage: LockStage) -> None:
    revalidate_external_lock_stage(stage, expected)
    try:
        promoted = rename_no_replace(stage.path, lock, "external lock stage recovery")
    except ManagerError:
        if lstat_optional(stage.path) is None and external_lock_final_matches(lock, expected):
            return
        raise
    if not promoted:
        return
    fsync_directory(lock.parent)


def external_lock_final_matches(lock: Path, expected: bytes) -> bool:
    flags = external_lock_open_flags()
    try:
        descriptor = os.open(lock, flags)
    except FileNotFoundError:
        return False
    except OSError as exc:
        fail(f"cannot open external target lock file: {exc}")
    try:
        require_external_lock_descriptor(lock, descriptor)
        ensure_external_lock_binding(descriptor, expected)
    finally:
        os.close(descriptor)
    return True


def drain_external_lock_publication_stages(lock: Path, expected: bytes, label: str) -> None:
    stages = require_external_lock_stages(lock, expected)
    if not stages:
        return
    parent_before = require_owner_private_directory(lock.parent, f"{label} parent")
    for stage in stages:
        revalidate_external_lock_stage(stage, expected)
        stage.path.unlink()
        fsync_directory(lock.parent)
    restore_external_lock_parent_metadata(lock.parent, parent_before)
    fsync_directory(lock.parent)


def publish_missing_external_lock_file(lock: Path, expected: bytes, label: str) -> None:
    stage_name = f".{lock.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}"
    stage = lock.with_name(stage_name)
    descriptor: int | None = None
    published = False
    staged: LockStage | None = None
    parent_before = require_owner_private_directory(lock.parent, f"{label} parent")
    try:
        descriptor = os.open(
            stage,
            external_lock_open_flags() | os.O_CREAT | os.O_EXCL,
            OWNER_FILE_MODE,
        )
        os.fchmod(descriptor, OWNER_FILE_MODE)
        write_complete(descriptor, expected, f"{label} staged binding")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        staged = validate_external_lock_stage(lock, expected, stage)
        try:
            published = rename_no_replace(stage, lock, label)
        except ManagerError:
            if lstat_optional(stage) is None and external_lock_final_matches(lock, expected):
                return
            raise
        if not published:
            if not external_lock_final_matches(lock, expected):
                fail(f"{label} publication lost final winner")
            return
        fsync_directory(lock.parent)
    except BaseException:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if lstat_optional(stage) is not None:
            if staged is not None:
                revalidate_external_lock_stage(staged, expected)
            with contextlib.suppress(OSError):
                stage.unlink()
            if not published:
                with contextlib.suppress(ManagerError):
                    restore_external_lock_parent_metadata(lock.parent, parent_before)
                    fsync_directory(lock.parent)
        raise


def open_external_lock_file(
    lock: Path,
    expected: bytes,
    *,
    recover_publication: bool,
    label: str,
) -> int:
    flags = external_lock_open_flags()
    stages = require_external_lock_stages(lock, expected)
    if stages and not recover_publication:
        fail(f"{label} publication is incomplete")
    try:
        descriptor = os.open(lock, flags)
    except FileNotFoundError:
        if stages:
            recover_external_lock_publication_stage(lock, expected, stages[0])
        else:
            publish_missing_external_lock_file(lock, expected, label)
        try:
            descriptor = os.open(lock, flags)
        except OSError as exc:
            fail(f"cannot open {label} after publication: {exc}")
    except OSError as exc:
        fail(f"cannot open {label}: {exc}")
    return descriptor


def lock_external_descriptor(
    descriptor: int,
    lock: Path,
    *,
    exclusive: bool,
    blocking: bool,
    busy_label: str,
) -> None:
    lock_kind = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    operation = lock_kind if blocking else lock_kind | fcntl.LOCK_NB
    try:
        fcntl.flock(descriptor, operation)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            fail(f"{busy_label} is already locked: {lock}")
        fail(f"cannot lock {busy_label}: {exc}")


def unlock_close_external_descriptor(descriptor: int | None, *, locked: bool) -> None:
    if descriptor is None:
        return
    if locked:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(descriptor)


@contextlib.contextmanager
def cold_external_target_inspection(lock: Path) -> Iterator[Path]:
    before = external_lock_namespace_snapshot(lock.parent)
    try:
        yield lock
    finally:
        after = external_lock_namespace_snapshot(lock.parent)
        if after != before:
            raise ConcurrentTargetChange("external target lock namespace changed during cold inspection")


@contextlib.contextmanager
def external_product_lock(root: Path, *, exclusive: bool, recover_publication: bool) -> Iterator[Path]:
    lock = external_product_lock_path(root)
    expected = canonical_json(external_product_lock_binding(root))
    descriptor = open_external_lock_file(
        lock,
        expected,
        recover_publication=recover_publication,
        label="external product lock",
    )
    locked = False
    try:
        lock_kind = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, lock_kind | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"product is already locked: {lock}")
            fail(f"cannot lock product externally: {exc}")
        locked = True
        require_external_lock_descriptor(lock, descriptor)
        ensure_external_lock_binding(descriptor, expected)
        if recover_publication:
            drain_external_lock_publication_stages(lock, expected, "external product lock")
        elif require_external_lock_stages(lock, expected):
            fail("external product lock publication is incomplete")
        require_external_lock_descriptor(lock, descriptor)
        yield lock
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(descriptor)


def require_external_lock_descriptor(lock: Path, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail("external target lock must be a regular file")
    if opened.st_nlink != 1:
        fail("external target lock must have exactly one link")
    require_current_user_owned(opened, "external target lock")
    require_exact_mode(opened, "external target lock", OWNER_FILE_MODE)
    final = require_owner_private_file(lock, "external target lock")
    if final.st_nlink != 1:
        fail("external target lock path must have exactly one link")
    if identity_of(opened) != identity_of(final):
        raise ConcurrentTargetChange("external target lock changed while it was opened")


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


def ensure_external_lock_binding(descriptor: int, expected: bytes) -> None:
    existing = read_external_lock_binding(descriptor)
    if existing is None:
        fail("external target lock binding is empty")
    if canonical_json(existing) != expected:
        fail("external target lock binding mismatch")


@contextlib.contextmanager
def external_target_lock(
    target: Path,
    *,
    blocking: bool = False,
    recover_publication: bool = False,
) -> Iterator[Path]:
    canonical_target = canonical_target_identity(target)
    target_expected = canonical_json(external_lock_binding(canonical_target))
    if recover_publication:
        system_root = require_bootstrap_system_root(bootstrap_system_temp_root())
        system_before = system_root.lstat()
        root_path = bootstrap_product_root_path()
        root_existed_before = lstat_optional(root_path) is not None
        root = bootstrap_product_root(create=True)
        assert root is not None
        product_lock = external_product_lock_path(root)
        product_expected = canonical_json(external_product_lock_binding(root))
        try:
            product_descriptor: int | None = open_external_lock_file(
                product_lock,
                product_expected,
                recover_publication=True,
                label="external product lock",
            )
        except BaseException:
            if not root_existed_before and lstat_optional(product_lock) is None:
                rollback_empty_product_root(root, system_root, system_before)
            raise
        product_locked = False
        target_descriptor: int | None = None
        target_locked = False
        lock = root / f"{external_lock_digest(canonical_target)}{EXTERNAL_LOCK_NAME_SUFFIX}"
        try:
            lock_external_descriptor(
                product_descriptor,
                product_lock,
                exclusive=True,
                blocking=True,
                busy_label="product",
            )
            product_locked = True
            require_external_lock_descriptor(product_lock, product_descriptor)
            ensure_external_lock_binding(product_descriptor, product_expected)
            validate_external_lock_namespace(root, product_expected)
            drain_external_lock_publication_stages(
                product_lock,
                product_expected,
                "external product lock",
            )
            require_external_lock_descriptor(product_lock, product_descriptor)
            validate_external_lock_namespace(root, product_expected)

            target_descriptor = open_external_lock_file(
                lock,
                target_expected,
                recover_publication=True,
                label="external target lock",
            )
            lock_external_descriptor(
                target_descriptor,
                lock,
                exclusive=True,
                blocking=blocking,
                busy_label="target",
            )
            target_locked = True
            require_external_lock_descriptor(lock, target_descriptor)
            ensure_external_lock_binding(target_descriptor, target_expected)
            drain_external_lock_publication_stages(lock, target_expected, "external target lock")
            require_external_lock_descriptor(lock, target_descriptor)
            validate_external_lock_namespace(root, product_expected)
            unlock_close_external_descriptor(product_descriptor, locked=True)
            product_descriptor = None
            product_locked = False
            yield lock
        finally:
            unlock_close_external_descriptor(target_descriptor, locked=target_locked)
            unlock_close_external_descriptor(product_descriptor, locked=product_locked)
        return

    root = bootstrap_product_root(create=False)
    if root is None:
        lock = bootstrap_product_root_path() / f"{external_lock_digest(canonical_target)}{EXTERNAL_LOCK_NAME_SUFFIX}"
        with cold_external_target_inspection(lock) as cold_lock:
            yield cold_lock
        return
    product_lock = external_product_lock_path(root)
    if lstat_optional(product_lock) is None:
        before = external_lock_namespace_snapshot(root)
        if len(before) > 1:
            fail("external product lock is missing but namespace is not empty")
        lock = root / f"{external_lock_digest(canonical_target)}{EXTERNAL_LOCK_NAME_SUFFIX}"
        with cold_external_target_inspection(lock) as cold_lock:
            yield cold_lock
        after = external_lock_namespace_snapshot(root)
        if after != before:
            raise ConcurrentTargetChange("external target lock namespace changed during cold inspection")
        return

    product_expected = canonical_json(external_product_lock_binding(root))
    product_descriptor: int | None = open_external_lock_file(
        product_lock,
        product_expected,
        recover_publication=False,
        label="external product lock",
    )
    product_locked = False
    target_descriptor: int | None = None
    target_locked = False
    lock = root / f"{external_lock_digest(canonical_target)}{EXTERNAL_LOCK_NAME_SUFFIX}"
    try:
        lock_external_descriptor(
            product_descriptor,
            product_lock,
            exclusive=False,
            blocking=blocking,
            busy_label="product",
        )
        product_locked = True
        require_external_lock_descriptor(product_lock, product_descriptor)
        ensure_external_lock_binding(product_descriptor, product_expected)
        validate_external_lock_namespace(root, product_expected)
        if require_external_lock_stages(product_lock, product_expected):
            fail("external product lock publication is incomplete")
        if require_external_lock_stages(lock, target_expected):
            fail("external target lock publication is incomplete")
        if lstat_optional(lock) is None:
            yield lock
            return
        target_descriptor = open_external_lock_file(
            lock,
            target_expected,
            recover_publication=False,
            label="external target lock",
        )
        lock_external_descriptor(
            target_descriptor,
            lock,
            exclusive=False,
            blocking=blocking,
            busy_label="target",
        )
        target_locked = True
        require_external_lock_descriptor(lock, target_descriptor)
        ensure_external_lock_binding(target_descriptor, target_expected)
        if require_external_lock_stages(lock, target_expected):
            fail("external target lock publication is incomplete")
        unlock_close_external_descriptor(product_descriptor, locked=True)
        product_descriptor = None
        product_locked = False
        yield lock
    finally:
        unlock_close_external_descriptor(target_descriptor, locked=target_locked)
        unlock_close_external_descriptor(product_descriptor, locked=product_locked)


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
            try:
                os.fchmod(root_descriptor, OWNER_DIR_MODE)
                require_lock_root_descriptor(
                    root,
                    root_descriptor,
                    "target lock root",
                    expected_mode=OWNER_DIR_MODE,
                )
                require_owner_private_file(lock, "target lock")
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
def target_lock(target: Path, *, create_target: bool) -> Iterator[None]:
    with external_target_lock(target, recover_publication=True):
        with internal_target_lock(target, create_target=create_target):
            yield


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


def choose_backup_slot(pool: Path) -> int:
    require_owner_private_directory(pool, "backup pool")
    slots = sorted(
        int(path.name) for path in pool.iterdir() if path.name.isdigit()
    )
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


def write_backup(target: Path, stamp: dict[str, Any]) -> int:
    ensure_target_directory(target, create=False)
    pool = ensure_backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        validate_owner_private_tree(slot_dir, f"backup slot {slot}")
        shutil.rmtree(slot_dir)
    files_dir = slot_dir / "files"
    files_dir.mkdir(parents=True, mode=OWNER_DIR_MODE)
    os.chmod(slot_dir, OWNER_DIR_MODE)
    os.chmod(files_dir, OWNER_DIR_MODE)
    require_owner_private_directory(slot_dir, f"backup slot {slot}")
    require_owner_private_directory(files_dir, f"backup slot {slot} files")
    managed_files: dict[str, str | None] = {}
    backup_managed_files = stamp_managed_files(stamp)
    for relative in backup_managed_files:
        if target_file_exists(target, relative):
            content = read_target_file(target, relative, owner_only=False)
            backup_path = files_dir / safe_relative_path(relative)
            atomic_write(backup_path, content)
            managed_files[relative] = managed_digest(relative, content)
        else:
            managed_files[relative] = None
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
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope))
    return slot


def load_backup(
    target: Path,
    slot: int,
) -> tuple[dict[str, Any], dict[str, bytes | None], tuple[str, ...]]:
    if slot < 0 or slot >= MAX_BACKUPS:
        fail("--backup must be between 0 and 9")
    ensure_target_directory(target, create=False)
    pool = ensure_backup_pool(target)
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
    validate_digest_map(envelope["managed_files"], "backup managed_files", backup_managed_files)
    files: dict[str, bytes | None] = {}
    files_dir = slot_dir / "files"
    for relative in backup_managed_files:
        expected = envelope["managed_files"][relative]
        path = files_dir / safe_relative_path(relative)
        if expected is None:
            files[relative] = None
            continue
        content, _ = read_regular_file(path, f"backup file {relative}", owner_only=True)
        if managed_digest(relative, content) != expected:
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


def current_status_body(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        software = software_status_body(target)
        return {
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
        }
    stamp = load_stamp(target)
    if stamp is None:
        software = software_status_body(target)
        return {
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
        }
    drift = detect_drift(target, stamp)
    software = software_status_body(target)
    if not stamp_is_current(stamp):
        return {
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
        }
    return {
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
    }


def current_status(target: Path) -> dict[str, Any]:
    with external_target_lock(target):
        return current_status_body(target)


def plan_setup(target: Path, setup_id: str, permission_profile_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    render_permission_profile(permission_profile_id)
    status = current_status(target)
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
    return {
        "operation": operation,
        "target": str(target),
        "setup_id": setup_id,
        "permission_profile_id": permission_profile_id,
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "current_setup_id": status["setup_id"],
        "current_permission_profile_id": status["permission_profile_id"],
        "drift": status["drift"],
    }


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
    setup = render_setup(setup_id)
    profile = render_permission_profile(permission_profile_id)
    with target_lock(target, create_target=action == "install"):
        ensure_target_directory(target, create=True)
        existing_stamp = load_stamp(target)
        if existing_stamp is None:
            if action == "switch":
                fail("switch requires a managed target")
            preflight_unmanaged_target(target)
        else:
            if not stamp_is_current(existing_stamp):
                fail(
                    "legacy managed target requires migrate before apply, "
                    "switch, update, or launch"
                )
            if action == "install":
                fail("install requires an absent managed target; use update or switch")
            drift = detect_drift(target, existing_stamp)
            if drift:
                fail(f"managed target has drift: {drift}")
        backup_slot: int | None = None
        if existing_stamp is not None and (
            existing_stamp["setup_id"] != setup_id
            or existing_stamp["permission_profile_id"] != permission_profile_id
        ):
            backup_slot = write_backup(target, existing_stamp)
        before = snapshot_managed_files(target)
        desired = desired_for_setup(target, setup, profile)
        desired[STAMP_NAME] = canonical_json(
            stamp_payload(target, setup_id, permission_profile_id, desired)
        )
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        changed = [
            relative
            for relative in MANAGED_FILES
            if before[relative].digest != sha256_bytes(desired[relative] or b"")
        ]
        return {
            "operation": "install" if existing_stamp is None else action,
            "target": str(target),
            "setup_id": setup_id,
            "permission_profile_id": permission_profile_id,
            "changed": changed,
            "backup_slot": backup_slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
            "engine": {
                "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                "status": MANAGED_LAUNCH_ENGINE_STATUS,
            },
        }


def update_setup(target: Path) -> dict[str, Any]:
    with target_lock(target, create_target=False):
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
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        changed = [
            relative
            for relative in MANAGED_FILES
            if before[relative].digest != sha256_bytes(desired[relative] or b"")
        ]
        return {
            "operation": "update",
            "target": str(target),
            "setup_id": setup.setup_id,
            "permission_profile_id": profile.profile_id,
            "changed": changed,
            "backup_slot": None,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
            "engine": {
                "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                "status": MANAGED_LAUNCH_ENGINE_STATUS,
            },
        }


def migrate_setup(target: Path, permission_profile_id: str) -> dict[str, Any]:
    setup = render_setup(CONTENT_SETUP_ID)
    profile = render_permission_profile(permission_profile_id)
    with target_lock(target, create_target=False):
        stamp = load_stamp(target)
        if stamp is None:
            fail("migrate requires a managed target")
        if stamp_is_current(stamp):
            fail("target already uses the current managed schema")
        drift = detect_drift(target, stamp)
        if drift:
            fail(f"managed target has drift: {drift}")
        backup_slot = write_backup(target, stamp)
        managed_files = tuple(dict.fromkeys((*LEGACY_MANAGED_FILES, *MANAGED_FILES)))
        before = snapshot_managed_files(target, managed_files)
        desired = desired_for_setup(target, setup, profile)
        for relative in managed_files:
            desired.setdefault(relative, None)
        desired[STAMP_NAME] = canonical_json(
            stamp_payload(target, setup.setup_id, profile.profile_id, desired)
        )
        try:
            replace_managed_state(target, desired, before, managed_files=managed_files)
        except BaseException:
            restore_snapshot(target, before, managed_files=managed_files)
            raise
        return {
            "operation": "migrate",
            "target": str(target),
            "from_schema_version": stamp["schema_version"],
            "from_setup_id": stamp["setup_id"],
            "setup_id": setup.setup_id,
            "permission_profile_id": profile.profile_id,
            "backup_slot": backup_slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
            "engine": {
                "argument": MANAGED_LAUNCH_ENGINE_ARGUMENT,
                "status": MANAGED_LAUNCH_ENGINE_STATUS,
            },
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target, create_target=False):
        stamp = require_clean_any_managed(target)
        _, files, backup_managed_files = load_backup(target, slot)
        backup_slot = write_backup(target, stamp)
        active_managed_files = stamp_managed_files(stamp)
        managed_files = tuple(dict.fromkeys((*active_managed_files, *backup_managed_files)))
        for relative in managed_files:
            files.setdefault(relative, None)
        before = snapshot_managed_files(target, managed_files)
        try:
            replace_managed_state(target, files, before, managed_files=managed_files)
        except BaseException:
            restore_snapshot(target, before, managed_files=managed_files)
            raise
        restored_stamp = load_stamp(target)
        assert restored_stamp is not None
        return {
            "operation": "restore",
            "target": str(target),
            "setup_id": restored_stamp["setup_id"],
            "permission_profile_id": restored_stamp.get("permission_profile_id"),
            "schema_version": restored_stamp["schema_version"],
            "backup_slot": backup_slot,
            "restored_backup": slot,
            "migration_required": not stamp_is_current(restored_stamp),
            "builder": {
                "projection": BUILDER_PROJECTION
                if stamp_is_current(restored_stamp)
                else LEGACY_BUILDER_PROJECTION,
                "enabled": True,
            },
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target, create_target=False):
        stamp = require_clean_any_managed(target)
        backup_slot = write_backup(target, stamp)
        managed_files = stamp_managed_files(stamp)
        before = snapshot_managed_files(target, managed_files)
        desired: dict[str, bytes | None] = {relative: None for relative in managed_files}
        if target_file_exists(target, SETTINGS):
            current = read_target_settings_if_present(target)
            stripped = strip_managed_settings(current)
            desired[SETTINGS] = canonical_json(stripped) if stripped else None
        desired[STAMP_NAME] = None
        try:
            replace_managed_state(target, desired, before, managed_files=managed_files)
        except BaseException:
            restore_snapshot(target, before, managed_files=managed_files)
            raise
        return {
            "operation": "remove",
            "target": str(target),
            "removed_setup_id": stamp["setup_id"],
            "removed_permission_profile_id": stamp.get("permission_profile_id"),
            "removed_schema_version": stamp["schema_version"],
            "backup_slot": backup_slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
        }


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
        elif argument.startswith("-C"):
            fail("launch refuses managed-scope Kiro CLI option: -C")


def capture_caller_workspace() -> Path:
    try:
        return Path.cwd()
    except OSError as exc:
        fail(f"cannot capture caller workspace: {exc}")


def resolve_launch_workspace(raw_workspace: str | None, caller_workspace: Path) -> Path:
    workspace = caller_workspace if raw_workspace is None else Path(raw_workspace).expanduser()
    if not workspace.is_absolute():
        fail("--workspace must be an absolute path")
    info = require_directory(workspace, "launch workspace")
    if not os.access(workspace, os.R_OK | os.X_OK):
        fail("launch workspace must be accessible")
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as exc:
        fail(f"cannot resolve launch workspace: {exc}")
    resolved_info = require_directory(resolved, "launch workspace")
    if identity_of(info) != identity_of(resolved_info):
        raise ConcurrentTargetChange("launch workspace changed while it was resolved")
    if not os.access(resolved, os.R_OK | os.X_OK):
        fail("launch workspace must be accessible")
    return resolved


def launch(target: Path, child_args: list[str], workspace: Path | None = None) -> int:
    if workspace is None:
        workspace = resolve_launch_workspace(None, capture_caller_workspace())
    reject_managed_launch_overrides(child_args)
    with target_lock(target, create_target=False):
        require_clean_managed(target)
        executable = require_clean_software(target)
        env = build_launch_env(target)
        executable = revalidate_software_executable(target)
        launch_args = [MANAGED_LAUNCH_ENGINE_ARGUMENT, *child_args]
        return subprocess.call([str(executable), *launch_args], env=env, cwd=str(workspace))


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        command.add_argument("--platform")
        command.add_argument("--architecture")
        command.add_argument("--libc")
        command.add_argument("--json", action="store_true")

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target")
    launch_parser.add_argument("--workspace")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def wants_json(argv: list[str]) -> bool:
    return "--json" in argv


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        caller_workspace = capture_caller_workspace()
        args = parse_args(raw_argv)
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
            emit(current_status(resolve_target(args.target)), as_json=args.json)
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
                    platform_arg=args.platform,
                    architecture_arg=args.architecture,
                    libc_arg=args.libc,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "software-install":
            emit(
                software_install(
                    resolve_target(args.target),
                    platform_arg=args.platform,
                    architecture_arg=args.architecture,
                    libc_arg=args.libc,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "software-update":
            emit(
                software_update(
                    resolve_target(args.target),
                    platform_arg=args.platform,
                    architecture_arg=args.architecture,
                    libc_arg=args.libc,
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
            workspace = resolve_launch_workspace(args.workspace, caller_workspace)
            return launch(resolve_target(args.target), child_args, workspace)
        fail(f"unsupported command: {args.command}")
    except ManagerError as exc:
        if wants_json(raw_argv):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"nddev-kiro-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
