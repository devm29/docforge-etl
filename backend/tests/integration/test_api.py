from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from docforge.api.app import create_app
from docforge.cli import InlinePipeline
from docforge.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(settings: Settings, inline: InlinePipeline) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, container=inline.container, queue=inline.queue)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_run_lifecycle_over_http(client: httpx.AsyncClient, inline: InlinePipeline) -> None:
    created = await client.post("/api/runs", json={"source": "fs"})
    assert created.status_code == 202
    run_id = created.json()["id"]
    await inline.queue.drain()

    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["run"]["status"] == "partial"
    assert [s["stage"] for s in detail["stages"]] == ["detect", "parse", "chunk", "embed", "extract", "load"]
    assert len(detail["dead_letters"]) == 1

    timeline = (await client.get(f"/api/runs/{run_id}/timeline")).json()
    assert len(timeline["documents"]) == 14

    export = await client.get(f"/api/runs/{run_id}/export/chunks.parquet")
    assert export.status_code == 200 and export.content[:4] == b"PAR1"

    overview = (await client.get("/api/overview")).json()
    assert overview["documents_total"] == 14 and overview["pending_reviews"] == 4


async def test_document_provenance_endpoints(client: httpx.AsyncClient, inline: InlinePipeline) -> None:
    await client.post("/api/runs", json={})
    await inline.queue.drain()

    page = (await client.get("/api/documents", params={"kind": "invoice", "limit": 3})).json()
    assert page["total"] == 8 and len(page["items"]) == 3
    northwind = next(
        d for d in (await client.get("/api/documents", params={"q": "northwind"})).json()["items"]
    )
    doc_id = northwind["id"]

    detail = (await client.get(f"/api/documents/{doc_id}")).json()
    assert detail["pages"][0]["width"] == pytest.approx(612)
    extraction = (await client.get(f"/api/documents/{doc_id}/extraction")).json()
    number = next(f for f in extraction["fields"] if f["path"] == "invoice_number")
    assert number["value"] == "INV-24017" and number["match"] == "exact" and number["bbox"]["x1"] > 0

    blocks = (await client.get(f"/api/documents/{doc_id}/blocks")).json()
    assert any(b["id"] == number["block_key"] for b in blocks)
    chunks = (await client.get(f"/api/documents/{doc_id}/chunks")).json()
    assert chunks and chunks[0]["spans"]

    file = await client.get(f"/api/documents/{doc_id}/file")
    assert file.headers["content-type"] == "application/pdf" and file.content.startswith(b"%PDF")


async def test_review_and_search_endpoints(client: httpx.AsyncClient, inline: InlinePipeline) -> None:
    await client.post("/api/runs", json={})
    await inline.queue.drain()

    reviews = (await client.get("/api/reviews")).json()
    item = next(i for i in reviews["items"] if i["field"]["path"] == "due_date")
    approved = await client.post(f"/api/reviews/{item['id']}/approve", json={"note": "qa"})
    assert approved.status_code == 200 and approved.json()["extraction_status"] == "approved"
    again = await client.post(f"/api/reviews/{item['id']}/approve", json={})
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"

    total = next(i for i in reviews["items"] if i["field"]["path"] == "total")
    rejected = await client.post(f"/api/reviews/{total['id']}/approve", json={})
    assert rejected.status_code == 422

    hits = (
        await client.get("/api/search", params={"q": "governing law california", "kind": "contract"})
    ).json()
    assert hits["hits"] and all(h["document"]["kind"] == "contract" for h in hits["hits"])


async def test_errors_use_a_consistent_envelope(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/runs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    bad = await client.post("/api/runs", json={"source": "ftp"})
    assert bad.status_code == 422 and "unknown source" in bad.json()["error"]["message"]
    invalid = await client.get("/api/documents", params={"limit": 0})
    assert invalid.status_code == 422 and invalid.json()["error"]["details"]
    health = (await client.get("/api/health")).json()
    assert health["status"] == "ok" and health["provider"] == "offline"


async def test_writes_need_a_token_once_tokens_are_configured(
    settings: Settings, inline: InlinePipeline
) -> None:
    secured = settings.model_copy(update={"api_tokens": {"s3cret-token": "maya.chen"}})
    app = create_app(secured, container=inline.container, queue=inline.queue)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            anonymous = await http.post("/api/runs", json={})
            wrong = await http.post("/api/runs", json={}, headers={"Authorization": "Bearer nope"})
            assert (anonymous.status_code, wrong.status_code) == (401, 401)
            assert anonymous.json()["error"]["code"] == "unauthorized"

            auth = {"Authorization": "Bearer s3cret-token"}
            assert (await http.post("/api/runs", json={}, headers=auth)).status_code == 202
            await inline.queue.drain()
            assert (await http.get("/api/reviews")).status_code == 200

            item = next(
                i
                for i in (await http.get("/api/reviews")).json()["items"]
                if i["field"]["path"] == "due_date"
            )
            spoofed = await http.post(
                f"/api/reviews/{item['id']}/approve", json={"reviewer": "someone-else"}, headers=auth
            )
            assert spoofed.status_code == 422
            approved = await http.post(f"/api/reviews/{item['id']}/approve", json={}, headers=auth)
            assert approved.json()["item"]["reviewer"] == "maya.chen"


async def test_without_tokens_only_loopback_callers_may_write(
    settings: Settings, inline: InlinePipeline
) -> None:
    app = create_app(settings, container=inline.container, queue=inline.queue)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("10.1.2.3", 51000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            assert (await http.post("/api/runs", json={})).status_code == 401
            assert (await http.get("/api/overview")).status_code == 200


async def test_a_second_run_for_the_same_source_is_rejected(
    client: httpx.AsyncClient, inline: InlinePipeline
) -> None:
    first = await client.post("/api/runs", json={})
    second = await client.post("/api/runs", json={"force": True})
    assert (first.status_code, second.status_code) == (202, 409)
    await inline.queue.drain()
    assert (await client.post("/api/runs", json={})).status_code == 202
    await inline.queue.drain()


async def test_prefixes_are_validated(client: httpx.AsyncClient) -> None:
    for prefix in ("../etc", "/abs", "a//b"):
        response = await client.post("/api/runs", json={"prefix": prefix})
        assert response.status_code == 422, prefix


async def test_timeline_is_paginated_and_files_are_served_safely(
    client: httpx.AsyncClient, inline: InlinePipeline
) -> None:
    run_id = (await client.post("/api/runs", json={})).json()["id"]
    await inline.queue.drain()

    page = (await client.get(f"/api/runs/{run_id}/timeline", params={"limit": 5, "offset": 10})).json()
    assert (page["total"], page["limit"], page["offset"], len(page["documents"])) == (14, 5, 10, 4)
    assert all(d["stages"] for d in page["documents"])

    document = (await client.get("/api/documents", params={"q": "northwind"})).json()["items"][0]
    file = await client.get(f"/api/documents/{document['id']}/file")
    assert file.headers["x-content-type-options"] == "nosniff"
    assert file.headers["content-disposition"] == "inline; filename*=UTF-8''northwind-INV-24017.pdf"


async def test_document_search_treats_wildcards_literally(
    client: httpx.AsyncClient, inline: InlinePipeline
) -> None:
    await client.post("/api/runs", json={})
    await inline.queue.drain()
    assert (await client.get("/api/documents", params={"q": "%"})).json()["total"] == 0
    assert (await client.get("/api/documents", params={"q": "_"})).json()["total"] == 0
