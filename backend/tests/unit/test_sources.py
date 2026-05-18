from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto.server import ThreadedMotoServer

from docforge.errors import InvalidRequestError, NotFoundError, SourceUnavailableError
from docforge.sources.base import in_scope, normalize_prefix
from docforge.sources.blobs import CorruptBlobError, LocalBlobStore
from docforge.sources.fs import FsSource
from docforge.sources.s3 import S3Source


async def test_fs_source_lists_supported_files_with_stat_fingerprints(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.pdf").write_bytes(b"%PDF-1.4 one")
    (tmp_path / "two.csv").write_text("x,y\n1,2\n")
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "three.pdf").write_bytes(b"%PDF")

    source = FsSource(tmp_path)
    objects = [obj async for obj in source.list_objects()]

    assert [o.uri for o in objects] == ["a/one.pdf", "two.csv"]
    assert all(o.fingerprint.startswith("stat:") for o in objects)
    assert await source.read("a/one.pdf") == b"%PDF-1.4 one"

    before = objects[0].fingerprint
    (tmp_path / "a" / "one.pdf").write_bytes(b"%PDF-1.4 changed")
    [changed] = [o async for o in source.list_objects("a")]
    assert before != changed.fingerprint


async def test_fs_source_refuses_paths_outside_its_root(tmp_path: Path) -> None:
    with pytest.raises(SourceUnavailableError):
        await FsSource(tmp_path).read("../../etc/passwd")


async def test_fs_source_rejects_a_prefix_that_does_not_exist(tmp_path: Path) -> None:
    (tmp_path / "invoices").mkdir()
    with pytest.raises(InvalidRequestError, match="does not exist"):
        [o async for o in FsSource(tmp_path).list_objects("%")]


@pytest.mark.parametrize("bad", ["../etc", "a/../../b", "/abs", "a//b", "./a", "a\\b", "a\nb"])
def test_prefixes_must_be_relative_paths(bad: str) -> None:
    with pytest.raises(ValueError, match="prefix"):
        normalize_prefix(bad)


def test_prefix_scope_is_path_based_not_string_based() -> None:
    assert normalize_prefix(" invoices/2026-03/ ") == "invoices/2026-03"
    assert normalize_prefix("100%_done") == "100%_done"
    assert in_scope("invoices/2026-03/a.pdf", "invoices/2026-03")
    assert in_scope("invoices/2026-03", "invoices/2026-03")
    assert not in_scope("invoices/2026-03-old/a.pdf", "invoices/2026-03")
    assert in_scope("anything.pdf", "")


def _leftover_temp_files(root: Path) -> list[Path]:
    return list(root.rglob("*.tmp"))


async def test_blob_store_is_content_addressed(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    key = await store.put(b"hello")
    assert key == await store.put(b"hello")
    assert await store.get(key) == b"hello"
    assert not _leftover_temp_files(tmp_path)


async def test_blob_store_verifies_content_on_read(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    key = await store.put(b"original")
    (tmp_path / key[:2] / key).write_bytes(b"tampered")
    with pytest.raises(CorruptBlobError):
        await store.get(key)
    with pytest.raises(NotFoundError):
        await store.get("../../etc/passwd")


@pytest.fixture(scope="module")
def s3_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


async def test_s3_source_lists_with_etag_fingerprints(s3_endpoint: str) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        region_name="us-east-1",
        aws_access_key_id="k",
        aws_secret_access_key="s",
    )
    client.create_bucket(Bucket="inbox")
    client.put_object(Bucket="inbox", Key="docs/invoice.pdf", Body=b"%PDF-1.4 body")
    client.put_object(Bucket="inbox", Key="docs/readme.md", Body=b"skip")

    source = S3Source(
        bucket="inbox", prefix="docs/", endpoint_url=s3_endpoint, access_key_id="k", secret_access_key="s"
    )
    [obj] = [o async for o in source.list_objects()]

    assert obj.uri == "docs/invoice.pdf" and obj.filename == "invoice.pdf"
    assert obj.fingerprint.startswith("etag:") and obj.size_bytes == 13
    assert await source.read(obj.uri) == b"%PDF-1.4 body"


async def test_s3_prefixes_are_scoped_under_the_configured_base(s3_endpoint: str) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        region_name="us-east-1",
        aws_access_key_id="k",
        aws_secret_access_key="s",
    )
    client.create_bucket(Bucket="scoped")
    for key in ("base/a/one.pdf", "base/ab/two.pdf", "base/b/three.pdf", "other/a/four.pdf"):
        client.put_object(Bucket="scoped", Key=key, Body=b"%PDF-1.4")

    source = S3Source(
        bucket="scoped", prefix="base", endpoint_url=s3_endpoint, access_key_id="k", secret_access_key="s"
    )

    assert source.uri_scope("a") == "base/a"
    assert [o.uri async for o in source.list_objects("a")] == ["base/a/one.pdf"]
    assert len([o async for o in source.list_objects()]) == 3


async def test_s3_source_wraps_errors_as_transient(s3_endpoint: str) -> None:
    source = S3Source(bucket="missing", endpoint_url=s3_endpoint, access_key_id="k", secret_access_key="s")
    with pytest.raises(SourceUnavailableError):
        await source.read("nope.pdf")
