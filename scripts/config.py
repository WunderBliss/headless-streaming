#!/usr/bin/env python3
"""Strict configuration handling for headless-virtual-display."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path("/etc/headless-virtual-display/topology.conf")
CONFIG_SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 4096

_USER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,31}")
_PCI_SLOT = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]")
_PCI_ID = re.compile(r"[0-9a-f]{4}")
_DRIVER = re.compile(r"[a-z0-9_]{1,32}")
_CONNECTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{1,63}")
_KEY = re.compile(r"[a-z][a-z0-9_]*")
_REQUIRED_KEYS = (
    "schema_version",
    "desktop_user",
    "desktop_uid",
    "pci_slot",
    "pci_vendor",
    "pci_device",
    "driver",
    "connector",
)


class ConfigError(ValueError):
    """Raised when topology configuration is missing, unsafe, or invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: int
    desktop_user: str
    desktop_uid: int
    pci_slot: str
    pci_vendor: str
    pci_device: str
    driver: str
    connector: str

    def lines(self) -> list[str]:
        return [
            f"schema_version={self.schema_version}",
            f"desktop_user={self.desktop_user}",
            f"desktop_uid={self.desktop_uid}",
            f"pci_slot={self.pci_slot}",
            f"pci_vendor={self.pci_vendor}",
            f"pci_device={self.pci_device}",
            f"driver={self.driver}",
            f"connector={self.connector}",
        ]

    def text(self) -> str:
        return "\n".join(self.lines()) + "\n"


def _parse_unsigned(value: str, name: str, maximum: int) -> int:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        raise ConfigError(f"{name} must be an unsigned decimal integer")
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise ConfigError(f"{name} must be between 1 and {maximum}")
    return parsed


def parse_config_text(text: str) -> RuntimeConfig:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line or raw_line.startswith("#"):
            continue
        if raw_line != raw_line.strip() or "=" not in raw_line:
            raise ConfigError(f"invalid configuration syntax on line {line_number}")
        key, value = raw_line.split("=", 1)
        if not _KEY.fullmatch(key) or not value or value != value.strip():
            raise ConfigError(f"invalid key/value syntax on line {line_number}")
        if key not in _REQUIRED_KEYS:
            raise ConfigError(f"unknown configuration key {key!r}")
        if key in values:
            raise ConfigError(f"duplicate configuration key {key!r}")
        values[key] = value

    missing = [key for key in _REQUIRED_KEYS if key not in values]
    if missing:
        raise ConfigError("missing configuration keys: " + ", ".join(missing))

    schema_version = _parse_unsigned(values["schema_version"], "schema_version", 999)
    if schema_version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported configuration schema {schema_version}; "
            f"expected {CONFIG_SCHEMA_VERSION}"
        )
    desktop_uid = _parse_unsigned(values["desktop_uid"], "desktop_uid", 2**31 - 1)
    if not _USER.fullmatch(values["desktop_user"]):
        raise ConfigError("desktop_user has an unsafe or unsupported name")
    if not _PCI_SLOT.fullmatch(values["pci_slot"]):
        raise ConfigError("pci_slot must be a lowercase domain:bus:device.function BDF")
    for name in ("pci_vendor", "pci_device"):
        if not _PCI_ID.fullmatch(values[name]):
            raise ConfigError(f"{name} must contain exactly four lowercase hex digits")
    if not _DRIVER.fullmatch(values["driver"]):
        raise ConfigError("driver contains unsupported characters")
    if not _CONNECTOR.fullmatch(values["connector"]):
        raise ConfigError("connector contains unsupported characters")

    return RuntimeConfig(
        schema_version=schema_version,
        desktop_user=values["desktop_user"],
        desktop_uid=desktop_uid,
        pci_slot=values["pci_slot"],
        pci_vendor=values["pci_vendor"],
        pci_device=values["pci_device"],
        driver=values["driver"],
        connector=values["connector"],
    )


def load_config(
    path: Path = CONFIG_PATH, *, require_secure_ownership: bool = True
) -> RuntimeConfig:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ConfigError(f"cannot open topology configuration {path}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigError(f"topology configuration is not a regular file: {path}")
        if require_secure_ownership and (
            metadata.st_uid != 0 or metadata.st_mode & 0o022
        ):
            raise ConfigError(
                f"topology configuration must be root-owned and not group/other-writable: {path}"
            )
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_CONFIG_BYTES:
            raise ConfigError(
                f"topology configuration exceeds {MAX_CONFIG_BYTES} bytes: {path}"
            )
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError as error:
            raise ConfigError("topology configuration must contain ASCII text") from error
    finally:
        os.close(descriptor)
    if "\0" in text:
        raise ConfigError("topology configuration must not contain NUL bytes")
    return parse_config_text(text)
