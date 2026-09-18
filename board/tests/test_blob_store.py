"""BlobStore Seam: Filesystem + Memory Adapters, tenant-scoped keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.blob_store import FilesystemBlobStore, MemoryBlobStore, build_blob_store, normalize_key
from app.tenant import TenantContext


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
