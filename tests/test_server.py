import asyncio
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
import pytest_asyncio

from insurelens.core import AppError
from insurelens.server import create_app


def fixture_pdf(text="보험약관 독감 항바이러스제 오셀타미비르"):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 100), text, fontname="korea")
        return doc.tobytes()


@pytest_asyncio.fixture
async def web(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER", "direct")
    app = create_app(root=tmp_path, nim=SimpleNamespace(enabled=False), drugs=SimpleNamespace(enabled=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:9876", headers={"X-Local-Request": "1"}) as client:
            yield app, client


async def wait(client, identifier):
    async with asyncio.timeout(20):
        while True:
            result = (await client.get(f"/api/jobs/{identifier}")).json()
            if result["state"] in {"completed", "failed", "cancelled"}:
                return result
            await asyncio.sleep(0.02)


async def upload(client, case, data=None):
    response = await client.post(f"/api/cases/{case}/documents", files={"file": ("my.pdf", data or fixture_pdf(), "application/pdf")})
    assert response.status_code == 202, response.text
    result = await wait(client, response.json()["jobId"])
    assert result["state"] == "completed", result
    return result


async def test_full_api_and_persisted_events(web):
    app, client = web
    config = (await client.get("/api/config")).json()
    assert config["backend"] == "python"
    response = await client.post("/api/cases")
    assert response.status_code == 201
    case = response.json()["id"]
    assert "HttpOnly" in response.headers.get("set-cookie", "") or "insurelens_session" in client.cookies
    indexed = await upload(client, case)
    doc = indexed["result"]["document"]
    assert doc["pages"] == 1 and "pdf" not in doc and "index" not in doc
    replay = await client.get(f"/api/jobs/{indexed['id']}/events")
    assert "event: completed" in replay.text and "id: " in replay.text
    event_ids = [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")]
    resumed = await client.get(f"/api/jobs/{indexed['id']}/events", headers={"Last-Event-ID": str(event_ids[-2])})
    assert resumed.text.count("id: ") == 1
    response = await client.post(f"/api/cases/{case}/investigations", json={"description": "조카가 독감 진단을 받았어요. 처방전은 없어요."})
    assert response.status_code == 202
    job = await wait(client, response.json()["jobId"])
    assert job["state"] == "completed", job
    assert any("독감" in q["quote"] for q in job["result"]["quotes"])
    assert all(q["quote"].strip() for q in job["result"]["quotes"])
    assert "answer" not in job["result"]
    download = await client.get(f"/api/jobs/{job['id']}/annotated.pdf")
    assert download.status_code == 200
    with pymupdf.open(stream=download.content) as marked, pymupdf.open(stream=fixture_pdf()) as original:
        assert marked[0].get_text() == original[0].get_text()
        assert len(list(marked[0].annots())) > 0
    partial = await client.get(f"/api/cases/{case}/pdf", headers={"Range": "bytes=0-4"})
    assert partial.status_code == 206 and partial.content == b"%PDF-"
    await upload(client, case, fixture_pdf("새 약관 치과"))
    assert (await client.get(f"/api/jobs/{job['id']}/annotated.pdf")).status_code == 409
    assert job["id"] not in {j["id"] for j in (await client.get(f"/api/cases/{case}")).json()["jobs"]}
    assert (await client.delete(f"/api/cases/{case}")).status_code == 204
    assert (await client.get(f"/api/jobs/{job['id']}")).status_code == 404
    assert not (app.state.store.root / case).exists()


async def test_upload_drafts_and_source_guards(web):
    app, client = web
    case = (await client.post("/api/cases")).json()["id"]
    bad = await client.post(f"/api/cases/{case}/documents", files={"file": ("bad.pdf", b"not pdf")})
    assert bad.json()["error"] == "INVALID_PDF"
    result = await client.post(f"/api/cases/{case}/ocr", files={"file": ("rx.pdf", fixture_pdf("약품명: 조플루자\n질병코드: J10.1"))})
    draft = (await wait(client, result.json()["jobId"]))["result"]
    assert draft["requiresConfirmation"] is True
    assert "조플루자" in draft["candidates"] and "J10.1" in draft["candidates"]
    assert (await client.post(f"/api/cases/{case}/ocr", files={"file": ("rx.png", b"image")})).status_code == 409
    await upload(client, case)
    for payload in ({"query": "   "}, {"query": "독감", "cloudConsent": "true"}, {"query": "독감", "injected": 1}, {"query": "독감", "drugIds": ["200001234"]}):
        assert (await client.post(f"/api/cases/{case}/investigations", json=payload)).status_code == 400


async def test_ownership_origin_and_bounded_request(web):
    app, client = web
    case = (await client.post("/api/cases")).json()["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:9876") as other:
        assert (await other.get(f"/api/cases/{case}")).status_code == 404
        assert (await other.post("/api/cases")).status_code == 403
    assert (await client.get("/api/config", headers={"Host": "attacker.invalid"})).status_code == 403
    assert (await client.post("/api/cases", headers={"Origin": "https://attacker.invalid"})).status_code == 403
    assert (await client.post("/api/cases", content=b"x" * 65537)).status_code == 413
    response = await client.get("/api/jobs/invalid")
    assert response.status_code == 400 and response.json() == {"error": "INVALID_REQUEST"}


async def test_key_does_not_bypass_cloud_consent(tmp_path):
    called = False
    async def investigate(**kwargs):
        nonlocal called
        called = True
        return {}
    app = create_app(root=tmp_path, nim=SimpleNamespace(enabled=True), drugs=SimpleNamespace(enabled=False), investigate=investigate)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"X-Local-Request": "1"}) as client:
        case = (await client.post("/api/cases")).json()["id"]
        await upload(client, case)
        response = await client.post(f"/api/cases/{case}/investigations", json={"query": "독감"})
        assert response.status_code == 409 and response.json()["error"] == "NIM_CONSENT_REQUIRED"
        assert called is False


async def test_running_pdf_cancel_and_delete(tmp_path):
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def pdf(payload):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    app = create_app(root=tmp_path, nim=SimpleNamespace(enabled=False), drugs=SimpleNamespace(enabled=False), pdf=pdf)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"X-Local-Request": "1"}) as client:
        case = (await client.post("/api/cases")).json()["id"]
        response = await client.post(f"/api/cases/{case}/documents", files={"file": ("x.pdf", fixture_pdf())})
        await started.wait()
        assert (await client.delete(f"/api/cases/{case}")).status_code == 204
        assert cancelled.is_set()
        assert not (tmp_path / case).exists()

@pytest.mark.parametrize('route', ['documents', 'ocr'])
async def test_delete_during_streaming_upload_leaves_no_orphan(web, route):
    app, client = web
    case = (await client.post('/api/cases')).json()['id']
    waiting, release = asyncio.Event(), asyncio.Event()
    async def body():
        yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        waiting.set()
        await release.wait()
        yield fixture_pdf() + b'\r\n--boundary--\r\n'
    task = asyncio.create_task(client.post(f'/api/cases/{case}/{route}', content=body(), headers={'Content-Type': 'multipart/form-data; boundary=boundary'}))
    await waiting.wait()
    assert (await client.delete(f'/api/cases/{case}')).status_code == 204
    release.set()
    assert (await task).status_code == 404
    assert app.state.store.jobs(case) == []
    assert not (app.state.store.root / case).exists()

async def test_old_file_cleanup_failure_preserves_new_document(web, monkeypatch):
    from pathlib import Path
    app, client = web
    case = (await client.post('/api/cases')).json()['id']
    await upload(client, case)
    owner = client.cookies.get('insurelens_session')
    old = app.state.store.get(case, owner)['document']['pdf']
    unlink = Path.unlink
    def failing_unlink(path, *args, **kwargs):
        if str(path) == old:
            raise PermissionError('synthetic locked old file')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', failing_unlink)
    latest = await upload(client, case, fixture_pdf('새 문서'))
    new = app.state.store.get(case, owner)['document']
    assert new['id'] == latest['result']['document']['id']
    assert Path(new['pdf']).exists() and Path(new['index']).exists()
