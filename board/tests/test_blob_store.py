"""BlobStore Seam: Filesystem, Memory, and R2 Adapters, tenant-scoped keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.blob_store import (
    FilesystemBlobStore,
    MemoryBlobStore,
    R2BlobStore,
    build_blob_store,
    normalize_key,
)
from app.tenant import TenantContext


class _R2Object:
    def __init__(self, body: bytes, http_metadata: dict | None = None) -> None:
        self._body = bytes(body)
        self.httpMetadata = dict(http_metadata or {})

    def arrayBuffer(self) -> bytes:
        return self._body

    def text(self) -> str:
        return self._body.decode("utf-8")


class MemoryR2Binding:
    """In-memory Cloudflare R2 binding: put(key, value, httpMetadata?), get, delete."""

    def __init__(self) -> None:
        self.objects: dict[str, _R2Object] = {}

    def put(self, key: str, value: bytes, httpMetadata: dict | None = None) -> None:
        meta = httpMetadata or {}
        if "httpMetadata" in meta and "contentType" not in meta:
            nested = meta.get("httpMetadata")
            meta = nested if isinstance(nested, dict) else {}
        self.objects[key] = _R2Object(value, meta)

    def get(self, key: str) -> _R2Object | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _OptionsR2Binding:
    """JS-style binding: the third positional argument is the put options object."""

    def __init__(self) -> None:
        self.objects: dict[str, _R2Object] = {}

    def put(self, key: str, value: bytes, options: dict | None = None) -> None:
        options = options or {}
        meta = options.get("httpMetadata") if isinstance(options, dict) else None
        self.objects[key] = _R2Object(value, meta if isinstance(meta, dict) else {})

    def get(self, key: str) -> _R2Object | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def test_memory_blob_store_is_tenant_scoped() -> None:
    store = MemoryBlobStore()
    a = TenantContext("acc_a")
    b = TenantContext("acc_b")
    store.put(a, "resume.pdf", b"AAA", content_type="application/pdf", filename="a.pdf")
    store.put(b, "resume.pdf", b"BBB", content_type="application/pdf", filename="b.pdf")
    assert store.get(a, "resume.pdf").content == b"AAA"
    assert store.get(b, "resume.pdf").content == b"BBB"
    assert store.delete(a, "resume.pdf") is True
    assert store.get(a, "resume.pdf") is None
    assert store.get(b, "resume.pdf").content == b"BBB"


def test_filesystem_blob_store_scopes_paths(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    a = TenantContext("acc_fs_a")
    b = TenantContext("acc_fs_b")
    store.put(a, "candidate.yaml", b"name: A")
    assert store.get(b, "candidate.yaml") is None
    assert b"name: A" in store.get(a, "candidate.yaml").content
    assert (tmp_path / "blobs" / "acc_fs_a" / "candidate.yaml").is_file()


def test_build_blob_store_memory_adapter() -> None:
    store = build_blob_store(root=None, memory=True)
    assert isinstance(store, MemoryBlobStore)


def test_normalize_key_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        normalize_key("../secret")


def test_r2_blob_store_round_trips_bytes_through_fake_binding() -> None:
    binding = MemoryR2Binding()
    store = build_blob_store(root=None, adapter="r2", binding=binding)
    assert isinstance(store, R2BlobStore)
    tenant = TenantContext("acc_r2")
    payload = b"\xff\xfe%PDF-1.4\x00not-text"
    stored = store.put(
        tenant,
        "resumes/a.pdf",
        payload,
        content_type="application/pdf",
        filename="a.pdf",
    )
    assert stored.content == payload
    held = binding.get("acc_r2/resumes/a.pdf")
    assert held is not None
    assert held.arrayBuffer() == payload
    assert held.httpMetadata["contentType"] == "application/pdf"
    loaded = store.get(tenant, "resumes/a.pdf")
    assert loaded is not None
    assert loaded.content == payload
    assert loaded.content_type == "application/pdf"
    assert loaded.filename == "a.pdf"
    assert loaded.account_id == "acc_r2"
    other = TenantContext("acc_other")
    assert store.get(other, "resumes/a.pdf") is None
    assert store.delete(tenant, "resumes/a.pdf") is True
    assert store.get(tenant, "resumes/a.pdf") is None
    assert binding.get("acc_r2/resumes/a.pdf") is None
    assert store.delete(tenant, "resumes/a.pdf") is False


def test_r2_blob_store_accepts_options_object_binding() -> None:
    binding = _OptionsR2Binding()
    store = R2BlobStore(binding)
    tenant = TenantContext("acc_opts")
    store.put(tenant, "note.txt", b"hello", content_type="text/plain", filename="note.txt")
    loaded = store.get(tenant, "note.txt")
    assert loaded is not None
    assert loaded.content == b"hello"
    assert loaded.content_type == "text/plain"
    assert loaded.filename == "note.txt"


def test_build_blob_store_keeps_filesystem_without_r2_binding(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    assert isinstance(build_blob_store(root=root), FilesystemBlobStore)
    assert isinstance(build_blob_store(root=root, adapter="r2"), FilesystemBlobStore)
    assert isinstance(build_blob_store(root=root, adapter=" r2 "), FilesystemBlobStore)
