"""Where input files come from and reports go: a local folder or Azure Blob Storage.

Layout (identical in both):
    audit-inputs/<client>/<batch>/prices.csv
    audit-inputs/<client>/<batch>/positions.csv
    audit-inputs/<client>/<batch>/gates.json        (optional)
    audit-inputs/<client>/<batch>/submit.json       (uploaded LAST; its arrival starts the audit)
    audit-reports/<client>/<batch>/report.html, results.json, explanations.json
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

INPUTS = "audit-inputs"
REPORTS = "audit-reports"
SUBMIT_FILE = "submit.json"
MAX_INPUT_BYTES = 200 * 1024 * 1024

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


def check_name(value: str, what: str) -> str:
    """Client and batch names become folder and blob names: allow only safe characters."""
    if not _NAME.match(value or "") or ".." in value:
        raise ValueError(f"Invalid {what} name {value!r}: use letters, digits, '-', '_' or '.'")
    return value


def parse_submit_path(blob_path: str) -> tuple[str, str] | None:
    """'audit-inputs/acme/2026-11-18/submit.json' -> ('acme', '2026-11-18'); None if not a submit file."""
    parts = blob_path.strip("/").split("/")
    if parts and parts[0] == INPUTS:
        parts = parts[1:]
    if len(parts) != 3 or parts[2] != SUBMIT_FILE:
        return None
    return check_name(parts[0], "client"), check_name(parts[1], "batch")


class Store(Protocol):
    def exists(self, container: str, path: str) -> bool: ...
    def read_bytes(self, container: str, path: str) -> bytes: ...
    def write_bytes(self, container: str, path: str, data: bytes, content_type: str) -> str: ...


class LocalStore:
    """A folder standing in for a storage account: each container is a subfolder."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, container: str, path: str) -> Path:
        full = (self.root / container / path).resolve()
        if self.root.resolve() not in full.parents:
            raise ValueError(f"Path escapes the store: {path}")
        return full

    def exists(self, container: str, path: str) -> bool:
        return self._path(container, path).is_file()

    def read_bytes(self, container: str, path: str) -> bytes:
        file = self._path(container, path)
        if file.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError(f"{path} is larger than {MAX_INPUT_BYTES // 2**20} MB")
        return file.read_bytes()

    def write_bytes(self, container: str, path: str, data: bytes, content_type: str) -> str:
        file = self._path(container, path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        return str(file)


class BlobStore:
    """Azure Blob Storage / Data Lake Gen2, authenticated with Microsoft Entra ID (no keys).

    In Azure the Function's managed identity is used; on your PC, `az login` is used.
    """

    def __init__(self, account_url: str, credential=None):
        from azure.identity import DefaultAzureCredential  # lazy: only needed in Azure mode
        from azure.storage.blob import BlobServiceClient

        self.client = BlobServiceClient(account_url, credential=credential or DefaultAzureCredential())

    def exists(self, container: str, path: str) -> bool:
        return self.client.get_blob_client(container, path).exists()

    def read_bytes(self, container: str, path: str) -> bytes:
        blob = self.client.get_blob_client(container, path)
        size = blob.get_blob_properties().size
        if size > MAX_INPUT_BYTES:
            raise ValueError(f"{path} is larger than {MAX_INPUT_BYTES // 2**20} MB")
        return blob.download_blob().readall()

    def write_bytes(self, container: str, path: str, data: bytes, content_type: str) -> str:
        from azure.storage.blob import ContentSettings

        blob = self.client.get_blob_client(container, path)
        blob.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
        return blob.url
