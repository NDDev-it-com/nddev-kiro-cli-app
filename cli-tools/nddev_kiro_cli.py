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
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-kiro-cli-app"
STAMP_NAME = "NDDEV-KIRO-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-KIRO-CLI-BACKUP.json"
STAMP_SCHEMA = 1
BACKUP_SCHEMA = 1
MAX_BACKUPS = 10
OWNER_FILE_MODE = 0o600
OWNER_DIR_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 1024 * 1024
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SETTINGS = "settings/cli.json"
PERMISSIONS = "settings/permissions.yaml"
BUILDER_AGENT = "agents/nddev-builder.md"
BUILDER_SKILL = "skills/nddev-builder/SKILL.md"
BUILDER_STEERING = "steering/nddev-builder.md"
BUILDER_HOOK = "hooks/nddev-builder.json"
BUILDER_FILES = (BUILDER_AGENT, BUILDER_SKILL, BUILDER_STEERING, BUILDER_HOOK)
MANAGED_FILES = (SETTINGS, PERMISSIONS, *BUILDER_FILES)
BASELINE_PATH = ROOT / "references" / "kiro-cli-baseline.json"
OFFICIAL_INSTALL_MANIFEST_URL = "https://prod.download.cli.kiro.dev/stable/latest/manifest.json"
SOFTWARE_RUNTIME_DIR = ".nddev-runtime/software"
SOFTWARE_DIR_NAME = "kiro-cli"
SOFTWARE_STAMP_NAME = "NDDEV-KIRO-CLI-SOFTWARE.json"
SOFTWARE_STAMP_SCHEMA = 1
SOFTWARE_TREE_MAX_FILES = 20000
SOFTWARE_TREE_MAX_BYTES = 3 * 1024 * 1024 * 1024
SOFTWARE_METADATA_MAX_BYTES = 1024 * 1024
DOWNLOAD_METADATA_MAX_BYTES = 4 * 1024 * 1024
MANAGED_LAUNCH_ENGINE_ARGUMENT = "--v3"
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
    "chat.defaultAgent",
    "chat.disableInheritingDefaultResources",
    "chat.ui",
    "telemetry.enabled",
)
BUILDER_PROJECTION = "native-agent-skill-steering-hook"
STAMP_KEYS = {
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
    managed_files: tuple[str, ...]
    builder_enabled: bool
    files: dict[str, bytes]


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


def fail(message: str) -> NoReturn:
    raise ManagerError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def is_owner_only_file(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        return False
    return True


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


def package_from_manifest_for_tests(
    manifest: dict[str, Any],
    os_name: str,
    architecture: str,
    libc: str | None,
) -> SoftwarePackage:
    if not test_sources_enabled():
        fail("manifest-selected software packages are private-test only")
    if manifest.get("version") != expected_runtime_version():
        fail("test Kiro CLI manifest must use the exact current runtime version")
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        fail("test Kiro CLI manifest packages must be a list")
    matches = [
        item
        for item in packages
        if isinstance(item, dict) and package_matches(item, os_name, architecture, libc)
    ]
    if len(matches) != 1:
        fail(f"cannot select test Kiro CLI package for {os_name}/{architecture}/{libc}")
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
        fail("test Kiro CLI package is missing download, size, or sha256")
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


def test_sources_enabled() -> bool:
    return os.environ.get("NDDEV_KIRO_CLI_ALLOW_TEST_SOURCES") == "1"


def read_manifest_source(path: str | None, url: str | None) -> dict[str, Any]:
    if path:
        if not test_sources_enabled():
            fail("local software manifest sources are private-test only")
        content, _ = read_regular_file(
            Path(path),
            "local Kiro CLI software manifest",
            owner_only=False,
            max_bytes=DOWNLOAD_METADATA_MAX_BYTES,
        )
    else:
        if url and url != OFFICIAL_INSTALL_MANIFEST_URL and not test_sources_enabled():
            fail("non-official software manifest URLs are private-test only")
        content = read_bounded_url(
            url or OFFICIAL_INSTALL_MANIFEST_URL,
            DOWNLOAD_METADATA_MAX_BYTES,
            "Kiro CLI install manifest",
        )
        if not test_sources_enabled():
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


def stage_artifact(
    stage: Path,
    package: SoftwarePackage,
    *,
    artifact_path: str | None,
    artifact_base_url: str | None,
) -> Path:
    artifact = stage / "download" / Path(package.download).name
    if artifact_path:
        if not test_sources_enabled():
            fail("local software artifact sources are private-test only")
        source = Path(artifact_path)
        content, _ = read_regular_file(
            source,
            "local Kiro CLI software artifact",
            owner_only=False,
            max_bytes=package.size,
        )
        if len(content) != package.size:
            fail("local Kiro CLI software artifact size mismatch")
        if sha256_bytes(content) != package.sha256:
            fail("local Kiro CLI software artifact digest mismatch")
        atomic_write(artifact, content)
        return artifact
    base_url = artifact_base_url or "https://prod.download.cli.kiro.dev/stable"
    if artifact_base_url and base_url != "https://prod.download.cli.kiro.dev/stable" and not test_sources_enabled():
        fail("non-official software artifact URLs are private-test only")
    url = artifact_download_url(base_url, package.download)
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
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        fail(f"{label} must be owned by the current user")


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
        (target / SOFTWARE_RUNTIME_DIR, "software parent"),
    )


def software_root_presence(target: Path) -> str:
    if optional_private_directory(target, "--target") is None:
        return "missing"
    for path, label in software_ancestor_paths(target):
        if optional_private_directory(path, label) is None:
            return "absent"
    if optional_private_directory(software_root(target), "software root") is None:
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
        "install_mode": "harness-owned-official-artifact",
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
    if stamp["build_version"] != VERSION:
        fail("software stamp build version is invalid")
    if stamp["runtime_product"] != "Kiro CLI" or stamp["version"] != expected_runtime_version():
        fail("software stamp runtime identity is invalid")
    if stamp["canonical_target"] != str(target):
        fail("software stamp is bound to a different canonical target")
    if stamp["install_mode"] != "harness-owned-official-artifact":
        fail("software stamp install mode is invalid")
    package = stamp["package"]
    if not isinstance(package, dict):
        fail("software stamp package is invalid")
    for key in ("os", "architecture", "fileType", "variant", "download", "sha256", "size"):
        if key not in package:
            fail(f"software stamp package.{key} is missing")
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


def load_software_stamp(target: Path) -> dict[str, Any] | None:
    if software_root_presence(target) != "present":
        return None
    stamp_path = software_stamp_path(target)
    if require_regular_stamp_if_present(stamp_path, "software stamp") is None:
        return None
    stamp = read_json_file(stamp_path, "software stamp", owner_only=False)
    validate_software_stamp(stamp, target)
    return stamp


def software_status(target: Path) -> dict[str, Any]:
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
    stamp = load_software_stamp(target)
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
    drift = []
    if tree.digest != stamp["tree"]["sha256"]:
        drift.append("software tree digest")
    if tree.executable_sha256 != stamp["executable"]["sha256"]:
        drift.append("software executable digest")
    return {
        "state": "installed" if not drift else "drift",
        "target": str(target),
        "version": stamp["version"],
        "package": stamp["package"],
        "executable": str(software_executable_from_stamp(target, stamp)),
        "drift": drift,
        "executes_binary": False,
    }


def preflight_software_target(target: Path, *, allow_partial: bool) -> dict[str, Any]:
    validated_transaction_parent(target)
    status = software_status(target)
    if status["state"] in {"partial", "drift"} and not allow_partial:
        fail("software target is partial; run software-update to repair it")
    return status


def validated_transaction_parent(target: Path) -> Path:
    parent = target.parent
    require_private_directory(parent, "software transaction parent")
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
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "KIRO_CLI_SKIP_SETUP": "1",
    }
    for key in tuple(env):
        if key in SECRET_ENV_NAMES or key.startswith(SECRET_ENV_PREFIXES):
            env.pop(key, None)
    return env


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
        ["bash", str(install_script)],
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
                "hdiutil",
                "attach",
                str(artifact),
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mount),
            ],
            text=True,
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
                ["hdiutil", "detach", str(mount), "-quiet"],
                text=True,
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
    require_private_directory(current, f"{label} existing parent")
    for directory in reversed(missing):
        directory.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(directory, OWNER_DIR_MODE)
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
            ensure_not_group_world_writable(target_info, "--target")
        for path, label in software_ancestor_paths(target):
            if lstat_optional(path) is not None:
                require_private_directory(path, label)
        software_parent = final_root.parent
        if lstat_optional(software_parent) is None:
            ensure_directory_chain(software_parent, created_dirs, "software parent")
        else:
            require_private_directory(software_parent, "software parent")
        final_root_info = lstat_optional(final_root)
        if final_root_info is not None:
            if not allow_existing:
                fail("Kiro CLI software is already installed")
            if stat.S_ISLNK(final_root_info.st_mode) or not stat.S_ISDIR(final_root_info.st_mode):
                fail("existing software root must be a real directory")
            ensure_not_group_world_writable(final_root_info, "existing software root")
            rollback_parent = create_transaction_dir(target, "software-rollback")
            rollback_root = rollback_parent / "previous"
            os.replace(final_root, rollback_root)
        os.replace(prepared, final_root)
        installed_new_root = True
        stamp = load_software_stamp(target)
        assert stamp is not None
        if rollback_parent is not None:
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
        if installed_new_root:
            final_info = lstat_optional(final_root)
            if final_info is not None and stat.S_ISDIR(final_info.st_mode) and not stat.S_ISLNK(
                final_info.st_mode
            ):
                shutil.rmtree(final_root, ignore_errors=True)
        if rollback_root is not None and lstat_optional(rollback_root) is not None:
            os.replace(rollback_root, final_root)
        if rollback_parent is not None:
            shutil.rmtree(rollback_parent, ignore_errors=True)
        for directory in reversed(created_dirs):
            with contextlib.suppress(OSError):
                Path(directory).rmdir()
        raise


def select_software_package(
    platform_arg: str | None,
    architecture_arg: str | None,
    libc_arg: str | None,
    manifest_path: str | None,
    manifest_url: str | None,
) -> SoftwarePackage:
    os_name = normalize_platform_name(platform_arg)
    architecture = normalize_architecture(architecture_arg, os_name)
    libc = normalize_libc(libc_arg, os_name)
    manifest = read_manifest_source(manifest_path, manifest_url)
    if manifest_path and test_sources_enabled():
        return package_from_manifest_for_tests(manifest, os_name, architecture, libc)
    package = select_baseline_package(os_name, architecture, libc)
    verify_manifest_package(manifest, package)
    return package


def prepare_software_from_package(
    target: Path,
    package: SoftwarePackage,
    *,
    artifact_path: str | None,
    artifact_base_url: str | None,
) -> tuple[Path, Path]:
    stage = create_transaction_dir(target, "software-stage")
    try:
        artifact = stage_artifact(
            stage,
            package,
            artifact_path=artifact_path,
            artifact_base_url=artifact_base_url,
        )
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
    manifest_path: str | None,
    manifest_url: str | None,
    artifact_path: str | None,
    artifact_base_url: str | None,
) -> dict[str, Any]:
    preflight_software_target(target, allow_partial=True)
    package = select_software_package(
        platform_arg,
        architecture_arg,
        libc_arg,
        manifest_path,
        manifest_url,
    )
    with software_stage(target) as stage:
        artifact = stage_artifact(
            stage,
            package,
            artifact_path=artifact_path,
            artifact_base_url=artifact_base_url,
        )
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
    manifest_path: str | None,
    manifest_url: str | None,
    artifact_path: str | None,
    artifact_base_url: str | None,
) -> dict[str, Any]:
    status = preflight_software_target(target, allow_partial=False)
    if status["state"] == "installed":
        fail("Kiro CLI software is already installed")
    package = select_software_package(
        platform_arg,
        architecture_arg,
        libc_arg,
        manifest_path,
        manifest_url,
    )
    prepared, stage = prepare_software_from_package(
        target,
        package,
        artifact_path=artifact_path,
        artifact_base_url=artifact_base_url,
    )
    try:
        with target_lock(target):
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
    manifest_path: str | None,
    manifest_url: str | None,
    artifact_path: str | None,
    artifact_base_url: str | None,
) -> dict[str, Any]:
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
        manifest_path,
        manifest_url,
    )
    prepared, stage = prepare_software_from_package(
        target,
        package,
        artifact_path=artifact_path,
        artifact_base_url=artifact_base_url,
    )
    try:
        with target_lock(target):
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
    with target_lock(target):
        status = software_status(target)
        root = software_root(target)
        if status["state"] in {"missing", "absent"}:
            return {
                "operation": "software-remove",
                "target": str(target),
                "changed": False,
                "removed_state": status["state"],
            }
        require_directory(root, "software root")
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


def expected_settings_for(_setup_id: str) -> dict[str, Any]:
    return {
        "chat.defaultAgent": "nddev-builder",
        "chat.disableInheritingDefaultResources": False,
        "chat.ui": "terminal",
        "telemetry.enabled": False,
    }


def expected_permissions_for(setup_id: str) -> bytes:
    if setup_id == "safe":
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
    if setup_id == "balanced":
        return (
            "rules:\n"
            "  - capability: fs_read\n"
            "    effect: deny\n"
            "    match:\n"
            '      - "**/.env"\n'
            '      - "**/.env.*"\n'
            '      - "**/*.pem"\n'
            '      - "secrets/**"\n'
            "  - capability: fs_read\n"
            "    effect: allow\n"
            "  - capability: shell\n"
            "    effect: allow\n"
            "    match:\n"
            '      - "git status*"\n'
            '      - "git diff*"\n'
            '      - "git log*"\n'
            '      - "git branch*"\n'
            '      - "python3 -m unittest*"\n'
            '      - "python3 -m pytest*"\n'
            '      - "npm test*"\n'
            '      - "npm run test*"\n'
            "  - capability: fs_write\n"
            "    effect: ask\n"
            "  - capability: web_fetch\n"
            "    effect: ask\n"
            "  - capability: web_search\n"
            "    effect: ask\n"
            "  - capability: mcp\n"
            "    effect: ask\n"
            "  - capability: subagent\n"
            "    effect: allow\n"
            "  - capability: skill\n"
            "    effect: allow\n"
            "  - capability: diagnostics\n"
            "    effect: allow\n"
            "  - capability: context\n"
            "    effect: allow\n"
        ).encode("utf-8")
    if setup_id == "full-auto":
        return "rules:\n  - capability: all\n    effect: allow\n".encode("utf-8")
    fail(f"unsupported setup id: {setup_id}")


def render_setup(setup_id: str) -> Setup:
    validate_setup_id(setup_id)
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {setup_id}")
    metadata = read_json_file(setup_root / "setup.json", f"setup {setup_id} metadata")
    expected_keys = {
        "schema_version",
        "id",
        "description",
        "managed_files",
        "managed_settings",
        "permission_profile",
        "builder_enabled",
    }
    if set(metadata) != expected_keys:
        fail(f"setup {setup_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity or schema is invalid")
    if metadata["managed_files"] != list(MANAGED_FILES):
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["managed_settings"] != expected_settings_for(setup_id):
        fail(f"setup {setup_id} managed settings declaration is invalid")
    if metadata["builder_enabled"] is not True:
        fail(f"setup {setup_id} must enable the native nddev-builder projection")
    if metadata["permission_profile"] != setup_id:
        fail(f"setup {setup_id} permission profile declaration is invalid")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"setup {setup_id} description must be non-empty")

    source_paths = {
        SETTINGS: "settings/cli.json",
        PERMISSIONS: "settings/permissions.yaml",
        BUILDER_AGENT: "agents/nddev-builder.md",
        BUILDER_SKILL: "skills/nddev-builder/SKILL.md",
        BUILDER_STEERING: "steering/nddev-builder.md",
        BUILDER_HOOK: "hooks/nddev-builder.json",
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
    if files[PERMISSIONS] != expected_permissions_for(setup_id):
        fail(f"setup {setup_id}/settings/permissions.yaml does not match the profile")
    hook = parse_json_object(files[BUILDER_HOOK], f"setup {setup_id}/hooks/nddev-builder.json")
    if hook.get("version") != "v1" or not isinstance(hook.get("hooks"), list):
        fail(f"setup {setup_id}/hooks/nddev-builder.json is not a Kiro v3 hook file")
    return Setup(
        setup_id=setup_id,
        description=metadata["description"],
        managed_settings=metadata["managed_settings"],
        managed_files=tuple(metadata["managed_files"]),
        builder_enabled=True,
        files=files,
    )


def list_setups() -> list[dict[str, Any]]:
    if not CATALOG_ROOT.is_dir() or CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    result: list[dict[str, Any]] = []
    for candidate in sorted(CATALOG_ROOT.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"catalog entry must be a real directory: {candidate.name}")
        setup = render_setup(candidate.name)
        result.append(
            {
                "id": setup.setup_id,
                "description": setup.description,
                "managed_files": list(setup.managed_files),
                "managed_settings": setup.managed_settings,
                "permission_profile": setup.setup_id,
                "builder_enabled": setup.builder_enabled,
            }
        )
    if not result:
        fail("setup catalog is empty")
    return result


def resolve_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    if not expanded.is_absolute():
        fail("--target must be an absolute path")
    try:
        raw_info = expanded.lstat()
    except FileNotFoundError:
        raw_info = None
    if raw_info is not None and stat.S_ISLNK(raw_info.st_mode):
        fail("--target must not be a symlink")
    target = expanded.resolve(strict=False)
    if target == Path(target.anchor):
        fail("filesystem root cannot be a target")
    parent_info = require_directory(target.parent, "canonical --target parent")
    if stat.S_ISLNK(parent_info.st_mode):
        fail("canonical --target parent must be a real directory")
    if target.exists():
        require_directory(target, "--target")
    return target


def ensure_target_directory(target: Path, *, create: bool) -> bool:
    try:
        info = target.lstat()
    except FileNotFoundError:
        if not create:
            return False
        target.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(target, OWNER_DIR_MODE)
        return True
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
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


def desired_for_setup(target: Path, setup: Setup) -> dict[str, bytes | None]:
    current = read_target_settings_if_present(target) if target.exists() else {}
    setup_settings = parse_json_object(setup.files[SETTINGS], "setup settings.json")
    desired = dict(setup.files)
    desired[SETTINGS] = canonical_json(compose_settings(current, setup_settings))
    return desired


def stamp_payload(target: Path, setup_id: str, desired: dict[str, bytes | None]) -> dict[str, Any]:
    managed_files: dict[str, str | None] = {}
    for relative in MANAGED_FILES:
        content = desired.get(relative)
        managed_files[relative] = None if content is None else managed_digest(relative, content)
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder": {
            "projection": BUILDER_PROJECTION,
            "enabled": True,
            "marketplace": None,
            "files": list(BUILDER_FILES),
        },
    }


def validate_digest_map(value: Any, label: str) -> dict[str, str | None]:
    if not isinstance(value, dict) or set(value) != set(MANAGED_FILES):
        fail(f"{label} must declare exactly {list(MANAGED_FILES)}")
    result: dict[str, str | None] = {}
    for name in MANAGED_FILES:
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
    content = read_target_file(target, STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    stamp = parse_json_object(content, f"managed stamp {target / STAMP_NAME}")
    if set(stamp) != STAMP_KEYS:
        fail("managed stamp has invalid keys")
    if stamp["schema_version"] != STAMP_SCHEMA or stamp["product_name"] != PRODUCT_NAME:
        fail("managed stamp identity or schema is invalid")
    if stamp["canonical_target"] != str(target):
        fail("managed stamp is bound to a different canonical target")
    if not isinstance(stamp["setup_id"], str):
        fail("managed stamp setup_id must be a string")
    validate_setup_id(stamp["setup_id"])
    validate_digest_map(stamp["managed_files"], "managed stamp managed_files")
    builder = stamp["builder"]
    if not isinstance(builder, dict) or builder.get("projection") != BUILDER_PROJECTION:
        fail("managed stamp builder projection is invalid")
    if builder.get("enabled") is not True or builder.get("marketplace") is not None:
        fail("managed stamp builder state is invalid")
    return stamp


def detect_drift(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    expected = validate_digest_map(stamp["managed_files"], "managed stamp managed_files")
    for relative in MANAGED_FILES:
        if not target_file_exists(target, relative):
            drift.append(relative)
            continue
        content = read_target_file(target, relative, owner_only=True)
        if managed_digest(relative, content) != expected[relative]:
            drift.append(relative)
    return drift


def snapshot_managed_files(target: Path) -> dict[str, FileSnapshot]:
    snapshot: dict[str, FileSnapshot] = {}
    for relative in (*MANAGED_FILES, STAMP_NAME):
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


def make_parent_directories(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, OWNER_DIR_MODE)
    except OSError:
        pass


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
    remove_empty_parents: bool = True,
) -> None:
    ensure_target_directory(target, create=True)
    if expected is not None:
        assert_snapshot(target, expected)
    for relative in (*MANAGED_FILES, STAMP_NAME):
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
        for relative in (*MANAGED_FILES, STAMP_NAME):
            target_file_exists(target, relative)


def restore_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    desired = {relative: item.content for relative, item in snapshot.items()}
    replace_managed_state(target, desired, None)


@contextlib.contextmanager
def target_lock(target: Path) -> Iterator[None]:
    lock = target.parent / f".{target.name}.nddev-kiro-cli-lock"
    try:
        lock.mkdir(mode=OWNER_DIR_MODE)
    except FileExistsError:
        fail(f"target is already locked: {lock}")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.rmdir()


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-kiro-cli-backups"


def choose_backup_slot(pool: Path) -> int:
    if not pool.exists():
        return 0
    slots = sorted(
        int(path.name)
        for path in pool.iterdir()
        if path.is_dir() and path.name.isdigit() and 0 <= int(path.name) < MAX_BACKUPS
    )
    if not slots:
        return 0
    return (slots[-1] + 1) % MAX_BACKUPS


def write_backup(target: Path, stamp: dict[str, Any]) -> int:
    pool = backup_pool(target)
    if pool.exists() and pool.is_symlink():
        fail("backup pool must not be a symlink")
    pool.mkdir(mode=OWNER_DIR_MODE, exist_ok=True)
    os.chmod(pool, OWNER_DIR_MODE)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        shutil.rmtree(slot_dir)
    files_dir = slot_dir / "files"
    files_dir.mkdir(parents=True, mode=OWNER_DIR_MODE)
    managed_files: dict[str, str | None] = {}
    for relative in MANAGED_FILES:
        if target_file_exists(target, relative):
            content = read_target_file(target, relative, owner_only=False)
            backup_path = files_dir / safe_relative_path(relative)
            atomic_write(backup_path, content)
            managed_files[relative] = managed_digest(relative, content)
        else:
            managed_files[relative] = None
    stamp_content = read_target_file(target, STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    envelope = {
        "schema_version": BACKUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(target),
        "source_setup_id": stamp["setup_id"],
        "managed_files": managed_files,
        "stamp_sha256": sha256_bytes(stamp_content),
    }
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope))
    return slot


def load_backup(target: Path, slot: int) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    if slot < 0 or slot >= MAX_BACKUPS:
        fail("--backup must be between 0 and 9")
    slot_dir = backup_pool(target) / str(slot)
    envelope_path = slot_dir / BACKUP_NAME
    if envelope_path.is_symlink() or not envelope_path.is_file():
        fail(f"backup slot is missing: {slot}")
    envelope = read_json_file(envelope_path, f"backup slot {slot}", owner_only=False)
    if set(envelope) != BACKUP_KEYS:
        fail("backup envelope has invalid keys")
    if envelope["schema_version"] != BACKUP_SCHEMA or envelope["product_name"] != PRODUCT_NAME:
        fail("backup envelope identity or schema is invalid")
    if envelope["canonical_target"] != str(target):
        fail("backup belongs to a different canonical target")
    validate_digest_map(envelope["managed_files"], "backup managed_files")
    files: dict[str, bytes | None] = {}
    files_dir = slot_dir / "files"
    for relative in MANAGED_FILES:
        expected = envelope["managed_files"][relative]
        path = files_dir / safe_relative_path(relative)
        if expected is None:
            files[relative] = None
            continue
        content, _ = read_regular_file(path, f"backup file {relative}", owner_only=False)
        if managed_digest(relative, content) != expected:
            fail(f"backup file digest mismatch: {relative}")
        files[relative] = content
    files[STAMP_NAME] = canonical_json(stamp_payload(target, envelope["source_setup_id"], files))
    return envelope, files


def current_status(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        return {
            "state": "missing",
            "target": str(target),
            "setup_id": None,
            "drift": [],
            "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
            "software": software_status(target),
        }
    stamp = load_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "target": str(target),
            "setup_id": None,
            "drift": [],
            "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
            "software": software_status(target),
        }
    drift = detect_drift(target, stamp)
    return {
        "state": "managed",
        "target": str(target),
        "setup_id": stamp["setup_id"],
        "build_version": stamp["build_version"],
        "drift": drift,
        "builder": {
            "projection": BUILDER_PROJECTION,
            "enabled": not any(item in drift for item in BUILDER_FILES),
        },
        "software": software_status(target),
    }


def plan_setup(target: Path, setup_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    status = current_status(target)
    if status["state"] == "missing":
        operation = "install"
        backup_required = False
    elif status["state"] == "unmanaged":
        operation = "install"
        backup_required = False
    elif status["setup_id"] == setup_id:
        operation = "update"
        backup_required = False
    else:
        operation = "switch"
        backup_required = True
    return {
        "operation": operation,
        "target": str(target),
        "setup_id": setup_id,
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "current_setup_id": status["setup_id"],
        "drift": status["drift"],
    }


def require_clean_managed(target: Path) -> dict[str, Any]:
    stamp = load_stamp(target)
    if stamp is None:
        fail("target is not managed")
    drift = detect_drift(target, stamp)
    if drift:
        fail(f"managed target has drift: {drift}")
    return stamp


def mutate_setup(target: Path, setup_id: str, action: str) -> dict[str, Any]:
    setup = render_setup(setup_id)
    with target_lock(target):
        ensure_target_directory(target, create=True)
        existing_stamp = load_stamp(target)
        if existing_stamp is None:
            if action == "switch":
                fail("switch requires a managed target")
            preflight_unmanaged_target(target)
        else:
            if action == "install":
                fail("install requires an absent managed target; use update or switch")
            drift = detect_drift(target, existing_stamp)
            if drift:
                fail(f"managed target has drift: {drift}")
        backup_slot: int | None = None
        if existing_stamp is not None and existing_stamp["setup_id"] != setup_id:
            backup_slot = write_backup(target, existing_stamp)
        before = snapshot_managed_files(target)
        desired = desired_for_setup(target, setup)
        desired[STAMP_NAME] = canonical_json(stamp_payload(target, setup_id, desired))
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
            "changed": changed,
            "backup_slot": backup_slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
        }


def update_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        stamp = load_stamp(target)
        if stamp is None:
            fail("update requires a managed target")
        setup = render_setup(stamp["setup_id"])
        before = snapshot_managed_files(target)
        desired = desired_for_setup(target, setup)
        desired[STAMP_NAME] = canonical_json(stamp_payload(target, setup.setup_id, desired))
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
            "changed": changed,
            "backup_slot": None,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target):
        stamp = require_clean_managed(target)
        _, files = load_backup(target, slot)
        backup_slot = write_backup(target, stamp)
        before = snapshot_managed_files(target)
        try:
            replace_managed_state(target, files, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        restored_stamp = load_stamp(target)
        assert restored_stamp is not None
        return {
            "operation": "restore",
            "target": str(target),
            "setup_id": restored_stamp["setup_id"],
            "backup_slot": backup_slot,
            "restored_backup": slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": True},
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        stamp = require_clean_managed(target)
        backup_slot = write_backup(target, stamp)
        before = snapshot_managed_files(target)
        desired: dict[str, bytes | None] = {relative: None for relative in MANAGED_FILES}
        if target_file_exists(target, SETTINGS):
            current = read_target_settings_if_present(target)
            stripped = strip_managed_settings(current)
            desired[SETTINGS] = canonical_json(stripped) if stripped else None
        desired[STAMP_NAME] = None
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        return {
            "operation": "remove",
            "target": str(target),
            "removed_setup_id": stamp["setup_id"],
            "backup_slot": backup_slot,
            "builder": {"projection": BUILDER_PROJECTION, "enabled": False},
        }


def build_launch_env(target: Path) -> dict[str, str]:
    runtime = target / ".nddev-runtime"
    xdg = runtime / "xdg"
    env: dict[str, str] = {
        "HOME": str(runtime / "home"),
        "KIRO_HOME": str(target),
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_DATA_HOME": str(xdg / "data"),
        "XDG_STATE_HOME": str(xdg / "state"),
        "XDG_CACHE_HOME": str(xdg / "cache"),
        "KIRO_CHAT_LOG_FILE": str(runtime / "logs" / "kiro-chat.log"),
    }
    if "TERM" in os.environ:
        env["TERM"] = os.environ["TERM"]
    for directory in (
        Path(env["XDG_CONFIG_HOME"]),
        Path(env["XDG_DATA_HOME"]),
        Path(env["XDG_STATE_HOME"]),
        Path(env["XDG_CACHE_HOME"]),
        Path(env["HOME"]),
        Path(env["KIRO_CHAT_LOG_FILE"]).parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, OWNER_DIR_MODE)
    for key in tuple(env):
        if key in SECRET_ENV_NAMES or key.startswith(SECRET_ENV_PREFIXES):
            env.pop(key, None)
    return env


def require_clean_software(target: Path) -> Path:
    status = software_status(target)
    if status["state"] != "installed":
        fail(f"Kiro CLI software is not installed cleanly in target: {status['state']}")
    stamp = load_software_stamp(target)
    if stamp is None:
        fail("Kiro CLI software stamp is missing")
    executable = software_executable_from_stamp(target, stamp)
    require_regular_file(executable, f"Kiro CLI executable {executable}", owner_only=False)
    return executable


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


def launch(target: Path, child_args: list[str]) -> int:
    reject_managed_launch_overrides(child_args)
    with target_lock(target):
        require_clean_managed(target)
        executable = require_clean_software(target)
        env = build_launch_env(target)
    launch_args = [MANAGED_LAUNCH_ENGINE_ARGUMENT, *child_args]
    return subprocess.call([str(executable), *launch_args], env=env)


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
        command.add_argument("--setup", required=True)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

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
        command.add_argument("--manifest-url")
        command.add_argument("--manifest-path")
        command.add_argument("--artifact-base-url")
        command.add_argument("--artifact-path")
        command.add_argument("--json", action="store_true")

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def wants_json(argv: list[str]) -> bool:
    return "--json" in argv


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
        if args.command == "list":
            emit({"setups": list_setups()}, as_json=args.json)
            return 0
        if args.command == "status":
            emit(current_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "software-status":
            emit(software_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "plan":
            emit(plan_setup(resolve_target(args.target), args.setup), as_json=args.json)
            return 0
        if args.command in {"install", "apply", "switch"}:
            action = "install" if args.command == "apply" else args.command
            emit(mutate_setup(resolve_target(args.target), args.setup, action), as_json=args.json)
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
                    manifest_path=args.manifest_path,
                    manifest_url=args.manifest_url,
                    artifact_path=args.artifact_path,
                    artifact_base_url=args.artifact_base_url,
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
                    manifest_path=args.manifest_path,
                    manifest_url=args.manifest_url,
                    artifact_path=args.artifact_path,
                    artifact_base_url=args.artifact_base_url,
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
                    manifest_path=args.manifest_path,
                    manifest_url=args.manifest_url,
                    artifact_path=args.artifact_path,
                    artifact_base_url=args.artifact_base_url,
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
            return launch(resolve_target(args.target), child_args)
        fail(f"unsupported command: {args.command}")
    except ManagerError as exc:
        if wants_json(raw_argv):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"nddev-kiro-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
