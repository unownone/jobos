"""BlobStore Module: tenant-scoped file bytes.

Interface is put/get/delete with TenantContext. Adapters: FilesystemBlobStore
(production, volumized), MemoryBlobStore (tests), and R2BlobStore (Cloudflare
R2 binding). R2 uses the Workers binding shape, not boto3 or the S3 API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.tenant import TenantContext

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._/-]{1,240}$")


@dataclass(frozen=True)
class Blob:
    key: str
    content: bytes
    content_type: str
    filename: str
    updated_at: str
    account_id: str

    def as_legacy(self) -> dict:
        """Shape older hub_blobs callers expect."""
        return {
            "key": self.key,
            "content": self.content,
            "content_type": self.content_type,
            "filename": self.filename,
            "updated_at": self.updated_at,
        }


class BlobStore(Protocol):
    def put(
        self,
        tenant: TenantContext,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "",
    ) -> Blob: ...

    def get(self, tenant: TenantContext, key: str) -> Blob | None: ...

    def delete(self, tenant: TenantContext, key: str) -> bool: ...


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_key(key: str) -> str:
    text = (key or "").strip().lstrip("/")
    if ".." in text or not _SAFE_KEY.match(text):
        raise ValueError("blob key must be a relative path without '..'")
    return text


class MemoryBlobStore:
    """In-memory Adapter for tests. Same Interface as the filesystem Adapter."""

    def __init__(self) -> None:
        self._blobs: dict[tuple[str, str], Blob] = {}

    def put(
        self,
        tenant: TenantContext,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "",
    ) -> Blob:
        norm = normalize_key(key)
        blob = Blob(
            key=norm,
            content=bytes(content),
            content_type=content_type or "application/octet-stream",
            filename=filename or Path(norm).name,
            updated_at=utc_stamp(),
            account_id=tenant.account_id,
        )
        self._blobs[(tenant.account_id, norm)] = blob
        return blob

    def get(self, tenant: TenantContext, key: str) -> Blob | None:
        return self._blobs.get((tenant.account_id, normalize_key(key)))

    def delete(self, tenant: TenantContext, key: str) -> bool:
        return self._blobs.pop((tenant.account_id, normalize_key(key)), None) is not None


class FilesystemBlobStore:
    """Production Adapter: `{root}/{account_id}/{key}` plus a JSON sidecar for meta."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, tenant: TenantContext, key: str) -> tuple[Path, Path]:
        norm = normalize_key(key)
        data = self.root / tenant.account_id / norm
        meta = data.with_name(data.name + ".meta.json")
        return data, meta

    def put(
        self,
        tenant: TenantContext,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "",
    ) -> Blob:
        data_path, meta_path = self._paths(tenant, key)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_bytes(bytes(content))
        blob = Blob(
            key=normalize_key(key),
            content=bytes(content),
            content_type=content_type or "application/octet-stream",
            filename=filename or data_path.name,
            updated_at=utc_stamp(),
            account_id=tenant.account_id,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "key": blob.key,
                    "content_type": blob.content_type,
                    "filename": blob.filename,
                    "updated_at": blob.updated_at,
                    "account_id": blob.account_id,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return blob

    def get(self, tenant: TenantContext, key: str) -> Blob | None:
        data_path, meta_path = self._paths(tenant, key)
        if not data_path.is_file():
            return None
        content_type = "application/octet-stream"
        filename = data_path.name
        updated_at = utc_stamp()
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                content_type = str(meta.get("content_type") or content_type)
                filename = str(meta.get("filename") or filename)
                updated_at = str(meta.get("updated_at") or updated_at)
            except json.JSONDecodeError:
                pass
        return Blob(
            key=normalize_key(key),
            content=data_path.read_bytes(),
            content_type=content_type,
            filename=filename,
            updated_at=updated_at,
            account_id=tenant.account_id,
        )

    def delete(self, tenant: TenantContext, key: str) -> bool:
        data_path, meta_path = self._paths(tenant, key)
        existed = data_path.is_file()
        if data_path.is_file():
            data_path.unlink()
        if meta_path.is_file():
            meta_path.unlink()
        return existed


def _put_binding(binding: Any, key: str, value: bytes, http_metadata: dict[str, str] | None) -> None:
    """Call ``put(key, value, httpMetadata?)`` on a Cloudflare R2 binding.

    Workers Python takes ``httpMetadata`` as a keyword. The JS binding's third
    argument is an options object whose ``httpMetadata`` field is optional.
    """
    try:
        binding.put(key, value, httpMetadata=http_metadata)
    except TypeError:
        binding.put(key, value, {"httpMetadata": http_metadata or {}})


def _body_bytes(obj: Any) -> bytes:
    reader = getattr(obj, "arrayBuffer", None)
    if callable(reader):
        raw = reader()
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return bytes(raw)
    reader = getattr(obj, "text", None)
    if callable(reader):
        text = reader()
        if isinstance(text, bytes):
            return text
        return str(text).encode("utf-8")
    body = getattr(obj, "body", None)
    if isinstance(body, (bytes, bytearray, memoryview)):
        return bytes(body)
    raise TypeError("R2 object does not expose arrayBuffer(), text(), or a bytes body")


def _http_metadata(obj: Any) -> dict[str, Any]:
    raw = getattr(obj, "httpMetadata", None)
    if raw is None:
        raw = getattr(obj, "http_metadata", None)
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("httpMetadata")
    if isinstance(nested, dict) and "contentType" not in raw and "content-type" not in raw:
        return nested
    return raw


def _content_type_of(meta: dict[str, Any], http_meta: dict[str, Any]) -> str:
    return str(
        meta.get("content_type")
        or http_meta.get("contentType")
        or http_meta.get("content-type")
        or "application/octet-stream"
    )


class R2BlobStore:
    """Adapter over any object with the Cloudflare R2 binding shape.

    ``put(key, value, httpMetadata?)``, ``get(key)`` returns an object with
    ``arrayBuffer`` / ``text`` or ``None``, and ``delete(key)``. Metadata that
    httpMetadata cannot carry is a sibling object, so a binding that only
    stores bytes still round-trips filename and updated_at.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("R2BlobStore requires a binding")
        self._binding = binding

    def _keys(self, tenant: TenantContext, key: str) -> tuple[str, str, str]:
        norm = normalize_key(key)
        prefix = f"{tenant.account_id}/"
        return norm, prefix + norm, prefix + "meta:" + norm

    def put(
        self,
        tenant: TenantContext,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "",
    ) -> Blob:
        norm, data_key, meta_key = self._keys(tenant, key)
        payload = bytes(content)
        content_type = content_type or "application/octet-stream"
        filename = filename or Path(norm).name
        updated_at = utc_stamp()
        _put_binding(self._binding, data_key, payload, {"contentType": content_type})
        meta = {
            "key": norm,
            "content_type": content_type,
            "filename": filename,
            "updated_at": updated_at,
            "account_id": tenant.account_id,
        }
        _put_binding(
            self._binding,
            meta_key,
            json.dumps(meta, ensure_ascii=False).encode("utf-8"),
            {"contentType": "application/json"},
        )
        return Blob(
            key=norm,
            content=payload,
            content_type=content_type,
            filename=filename,
            updated_at=updated_at,
            account_id=tenant.account_id,
        )

    def get(self, tenant: TenantContext, key: str) -> Blob | None:
        norm, data_key, meta_key = self._keys(tenant, key)
        obj = self._binding.get(data_key)
        if obj is None:
            return None
        content = _body_bytes(obj)
        http_meta = _http_metadata(obj)
        meta: dict[str, Any] = {}
        meta_obj = self._binding.get(meta_key)
        if meta_obj is not None:
            try:
                loaded = json.loads(_body_bytes(meta_obj).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                meta = loaded
        filename = str(meta.get("filename") or Path(norm).name)
        updated_at = str(meta.get("updated_at") or utc_stamp())
        account_id = str(meta.get("account_id") or tenant.account_id)
        return Blob(
            key=norm,
            content=content,
            content_type=_content_type_of(meta, http_meta),
            filename=filename,
            updated_at=updated_at,
            account_id=account_id,
        )

    def delete(self, tenant: TenantContext, key: str) -> bool:
        _norm, data_key, meta_key = self._keys(tenant, key)
        existed = self._binding.get(data_key) is not None
        self._binding.delete(data_key)
        self._binding.delete(meta_key)
        return existed


def build_blob_store(
    *,
    root: Path | None = None,
    memory: bool = False,
    adapter: str | None = None,
    binding: Any | None = None,
) -> BlobStore:
    """Pick an adapter.

    ``adapter="r2"`` with a binding returns :class:`R2BlobStore`. With no
    binding, the previous default remains: memory when asked or when ``root``
    is missing, otherwise the filesystem.
    """
    if (adapter or "").strip().lower() == "r2" and binding is not None:
        return R2BlobStore(binding)
    if memory or root is None:
        return MemoryBlobStore()
    return FilesystemBlobStore(root)
