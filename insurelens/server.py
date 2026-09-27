"""Local FastAPI application; PDF.js is the only JavaScript runtime UI."""
import asyncio
import base64
from contextlib import asynccontextmanager
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import time
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException

from .core import AppError, DrugLookupRequest, QueryRequest, ensure
from .pdf import pdf_operation
from .store import Queue, Store
from .nat import configured_investigation
from .diagnostics import RuntimeLog, failure_fields, log_context, record

ROOT = Path(__file__).resolve().parents[1]
SECURITY_HEADERS = {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}


class LocalBoundary:
    """ASGI middleware keeps SSE streaming while bounding request bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        host, origin = headers.get("host", ""), headers.get("origin")
        try:
            ensure(re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::\d+)?", host), "HOST_FORBIDDEN", 403)
            ensure(not origin or origin == f"http://{host}", "ORIGIN_FORBIDDEN", 403)
            ensure(scope["method"] in ("GET", "HEAD") or headers.get("x-local-request") == "1", "LOCAL_REQUEST_REQUIRED", 403)
            multipart = headers.get("content-type", "").startswith("multipart/form-data")
            limit = 20 * 1024 * 1024 + 65536 if multipart else 65536
            length = headers.get("content-length", "0")
            ensure(length.isdecimal() and int(length) <= limit, "FILE_TOO_LARGE" if multipart else "REQUEST_TOO_LARGE", 413)
        except AppError as error:
            record("request.error", status=error.status, **failure_fields(error))
            return await JSONResponse({"error": error.code}, error.status, headers=SECURITY_HEADERS)(scope, receive, send)
        cookies = Request(scope).cookies
        owner = cookies.get("insurelens_session", "")
        try:
            UUID(owner)
            new_cookie = False
        except ValueError:
            owner, new_cookie = str(uuid4()), True
        scope.setdefault("state", {})["owner"] = owner
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "FILE_TOO_LARGE" if multipart else "REQUEST_TOO_LARGE")
            return message

        async def secure_send(message):
            if message["type"] == "http.response.start":
                result_headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name.lower() != "cache-control" or name not in result_headers:
                        result_headers[name] = value
                if new_cookie:
                    result_headers.append("set-cookie", f"insurelens_session={owner}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            await send(message)

        await self.app(scope, bounded_receive, secure_send)


class RequestLogging:
    """Correlate background jobs with requests without reading bodies or URLs."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault('state', {})['request_id'] = request_id
        logger = getattr(scope['app'].state, 'diagnostics', None)
        status = 500
        started = time.monotonic()

        async def logged_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                MutableHeaders(scope=message)['X-Request-ID'] = request_id
            await send(message)

        with log_context(logger, request_id=request_id):
            try:
                await self.app(scope, receive, logged_send)
            except asyncio.CancelledError:
                status = 499
                raise
            except Exception as error:
                record('request.error', status=500, **failure_fields(error))
                raise
            finally:
                record('request.completed', method=scope['method'],
                       route=getattr(scope.get('route'), 'path', None), status=status,
                       duration_ms=(time.monotonic()-started)*1000)


def create_app(*, root=None, nim=None, drugs=None, pdf=pdf_operation, investigate=None):
    from .providers import Nvidia, Drugs
    if nim is None:
        load_dotenv(ROOT / ".env", override=False)
        nim = Nvidia()
    if drugs is None:
        drugs = Drugs()
    root = Path(root or os.environ.get("DATA_DIR") or ROOT / ".local-data").resolve()

    if investigate is None:
        async def investigate(**kwargs):
            return await configured_investigation(**kwargs)

    @asynccontextmanager
    async def lifespan(application):
        diagnostics = RuntimeLog()
        application.state.diagnostics = diagnostics
        try:
            with log_context(diagnostics):
                store = Store(root)
        except BaseException:
            diagnostics.close()
            raise
        diagnostics.write('app.started')
        application.state.store = store
        application.state.queue = Queue(store)
        application.state.exports = 0
        application.state.deleting = set()
        try:
            yield
        finally:
            await application.state.queue.close()
            for provider in (nim, drugs):
                if hasattr(provider, "close"):
                    outcome = provider.close()
                    if inspect.isawaitable(outcome):
                        await outcome
            store.close()
            diagnostics.write("app.stopped")
            diagnostics.close()

    app = FastAPI(title="InsureLens", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(LocalBoundary)
    app.add_middleware(RequestLogging)

    @app.exception_handler(AppError)
    async def app_error(request, error):
        record("request.error", status=error.status, **failure_fields(error))
        return JSONResponse({"error": error.code}, error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        record("request.error", status=400, code="INVALID_REQUEST")
        return JSONResponse({"error": "INVALID_REQUEST"}, 400)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        code = error.detail if isinstance(error.detail, str) and re.fullmatch(r"[A-Z_]{3,80}", error.detail) else "REQUEST_FAILED"
        record("request.error", status=error.status_code, code=code)
        return JSONResponse({"error": code}, error.status_code)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({"error": "REQUEST_FAILED"}, 500, headers={"X-Request-ID": request.state.request_id})

    def case_for(identifier, request):
        ensure(str(identifier) not in app.state.deleting, "CASE_BUSY", 409)
        return app.state.store.get(str(identifier), request.state.owner)

    def public_case(case):
        document = case["document"]
        return {"id": case["id"], "document": {k: v for k, v in document.items() if k not in ("pdf", "index")} if document else None, "jobs": [j for j in app.state.store.jobs(case["id"]) if j["kind"] != "investigation" or j["documentId"] == (document or {}).get("id")], "products": list(case["products"].values())}

    async def uploaded(request, limit):
        async with request.form(max_files=1, max_fields=1, max_part_size=limit) as form:
            file = form.get("file")
            ensure(file is not None and hasattr(file, "read"), "FILE_REQUIRED")
            data = await file.read(limit + 1)
            ensure(len(data) <= limit, "FILE_TOO_LARGE", 413)
            return data, (file.filename or "document.pdf")[:255], file.content_type

    @app.get("/api/config")
    async def config():
        return {"nimEnabled": nim.enabled, "ocrEnabled": bool(getattr(nim, "ocr_enabled", False)), "mfdsEnabled": bool(getattr(drugs, "enabled", False)), "translationEnabled": bool(nim.enabled and getattr(nim, "translation_model", "")), "mode": "nim-react", "orchestrator": "nat", "ready": bool(nim.enabled), "backend": "python", "inferenceClient": "nemo-microservices"}

    @app.post("/api/cases", status_code=201)
    async def create_case(request: Request):
        return {"id": app.state.store.create(request.state.owner)["id"]}

    @app.get("/api/cases/{identifier}")
    async def get_case(identifier: UUID, request: Request):
        return public_case(case_for(identifier, request))

    @app.get("/api/cases/{identifier}/conversation")
    async def get_conversation(identifier: UUID, request: Request):
        case = case_for(identifier, request)
        return app.state.store.conversation(case['id'], case['document']['id']) if case['document'] else {"id": None, "turns": []}

    @app.post("/api/cases/{identifier}/conversation", status_code=201)
    async def new_conversation(identifier: UUID, request: Request):
        case = case_for(identifier, request)
        ensure(case['document'], "DOCUMENT_REQUIRED", 409)
        ensure(all(j['state'] not in ('queued','running') for j in app.state.store.jobs(case['id'])), "CASE_BUSY", 429)
        return app.state.store.new_conversation(case['id'], case['document']['id'])

    @app.delete("/api/cases/{identifier}", status_code=204)
    async def remove_case(identifier: UUID, request: Request):
        case = case_for(identifier, request)
        ensure(app.state.exports == 0, "PDF_BUSY", 429)
        app.state.deleting.add(case["id"])
        try:
            await app.state.queue.cancel_case(case["id"])
            app.state.store.remove(case["id"])
            shutil.rmtree(root / case["id"], ignore_errors=True)
        finally:
            app.state.deleting.discard(case["id"])
        return Response(status_code=204)

    @app.post("/api/cases/{identifier}/documents", status_code=202)
    async def upload_document(identifier: UUID, request: Request):
        case = case_for(identifier, request)
        data, name, _ = await uploaded(request, 20 * 1024 * 1024)
        case = case_for(identifier, request)
        ensure(data.startswith(b"%PDF-"), "INVALID_PDF")
        store, queue = app.state.store, app.state.queue
        ensure(not app.state.exports and all(j["state"] not in ("queued", "running") for j in store.jobs(case["id"])), "CASE_BUSY", 429)
        doc_id = str(uuid4())
        folder = root / case["id"]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        pdf_path, index = folder / f"{doc_id}.pdf", folder / f"{doc_id}.json.gz"
        job_id = store.create_job(case["id"], "document", doc_id)

        async def index_document(emit):
            committed = False
            try:
                pdf_path.write_bytes(data)
                pdf_path.chmod(0o600)
                emit("stage_started", {"stage": "document", "message": "약관의 원문과 문자 위치를 읽고 있습니다."})
                meta = await pdf({"op": "index", "pdf": str(pdf_path), "index": str(index)})
                ensure(meta["textPages"] > 0, "TEXT_LAYER_REQUIRED", 422)
                old = store.get(case["id"], request.state.owner)["document"]
                store.set_document(case["id"], {"id": doc_id, "name": name, "pdf": str(pdf_path), "index": str(index), **meta})
                committed = True
                if old:
                    for old_path in (old["pdf"], old["index"]):
                        try:
                            Path(old_path).unlink(missing_ok=True)
                        except OSError:
                            pass  # The committed new document must survive cleanup failure.
                emit("stage_completed", {"stage": "document"})
                return {"document": public_case(store.get(case["id"], request.state.owner))["document"]}
            except BaseException:
                if not committed:
                    pdf_path.unlink(missing_ok=True)
                    index.unlink(missing_ok=True)
                raise

        queue.add(job_id, index_document)
        return {"jobId": job_id}

    @app.get("/api/cases/{identifier}/pdf")
    async def original_pdf(identifier: UUID, request: Request):
        case = case_for(identifier, request)
        ensure(case["document"], "DOCUMENT_REQUIRED", 409)
        return FileResponse(case["document"]["pdf"], media_type="application/pdf")

    @app.post("/api/cases/{identifier}/ocr", status_code=202)
    async def upload_prescription(identifier: UUID, request: Request):
        from .agents.prescription import prescription_candidates
        case = case_for(identifier, request)
        data, _, mime = await uploaded(request, 8 * 1024 * 1024)
        case = case_for(identifier, request)
        is_pdf, consent = data.startswith(b"%PDF-"), request.headers.get("x-cloud-consent") == "yes"
        if not is_pdf:
            ensure(consent and getattr(nim, "ocr_enabled", False), "OCR_CONSENT_OR_CONFIG_REQUIRED", 409)
        folder = root / case["id"]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        input_path = folder / f"{uuid4()}.input"
        index = Path(str(input_path) + ".json.gz")
        job_id = app.state.store.create_job(case["id"], "ocr")

        async def read_prescription(emit):
            emit("stage_started", {"stage": "ocr", "message": "진료·처방 자료의 글자를 읽고 있습니다."})
            try:
                if not is_pdf:
                    value = await nim.ocr(data, mime)
                    return {**value, "candidates": await prescription_candidates(value["text"], nim=nim, consent=consent)}
                input_path.write_bytes(data)
                input_path.chmod(0o600)
                meta = await pdf({"op": "index", "pdf": str(input_path), "index": str(index)})
                ensure(meta["pages"] <= 8, "PRESCRIPTION_PAGE_LIMIT")
                if meta["textPages"] == meta["pages"]:
                    value = await pdf({"op": "text", "pdf": str(input_path), "index": str(index)})
                    text, method = value["text"], "pdf-text-layer"
                else:
                    ensure(consent and getattr(nim, "ocr_enabled", False), "OCR_CONSENT_OR_CONFIG_REQUIRED", 409)
                    images = await pdf({"op": "render", "pdf": str(input_path)})
                    results = [await nim.ocr(base64.b64decode(image), "image/png") for image in images["images"]]
                    text, method = "\n".join(x["text"] for x in results), "ocr"
                return {"text": text, "candidates": await prescription_candidates(text, nim=nim, consent=consent), "requiresConfirmation": True, "method": method}
            finally:
                input_path.unlink(missing_ok=True)
                index.unlink(missing_ok=True)

        app.state.queue.add(job_id, read_prescription)
        return {"jobId": job_id}

    @app.post("/api/cases/{identifier}/drugs")
    async def lookup_drug(identifier: UUID, request: Request, body: DrugLookupRequest):
        case = case_for(identifier, request)
        result = await drugs.lookup(body.name)
        # Read again after awaiting the provider to avoid losing concurrent results.
        products = case_for(identifier, request)["products"]
        products.update({p["id"]: p for p in result["products"]})
        ensure(len(products) <= 300, "DRUG_RESULT_LIMIT", 429)
        app.state.store.set_products(case["id"], products)
        return result

    @app.post("/api/cases/{identifier}/investigations", status_code=202)
    async def investigate_case(identifier: UUID, request: Request, body: QueryRequest):
        case = case_for(identifier, request)
        ensure(case["document"], "DOCUMENT_REQUIRED", 409)
        ensure(nim.enabled, "NVIDIA_KEY_REQUIRED", 409)
        ensure(body.cloudConsent, "NIM_CONSENT_REQUIRED", 409)
        ensure(all(i in case["products"] for i in body.drugIds), "DRUG_SELECTION_REQUIRED")
        products = [case["products"][i] for i in body.drugIds]
        store = app.state.store
        ensure(all(j['state'] not in ('queued','running') for j in store.jobs(case['id'])), "CASE_BUSY", 429)
        context = None
        if body.conversationId:
            from insurelens.conversation import model_context
            conversation = store.conversation(case['id'], case['document']['id'])
            ensure(conversation['id'] == body.conversationId, "CONVERSATION_CHANGED", 409)
            ensure(len(conversation['turns']) < 50, "CONVERSATION_TURN_LIMIT", 429)
            context = model_context(conversation['turns'])
        job_id = store.create_job(case["id"], "investigation", case["document"]["id"])
        if body.conversationId:
            store.add_turn(body.conversationId, job_id, body.model_dump())

        async def run(emit):
            return await investigate(document=case["document"], request=body.model_dump(), products=products, nim=nim, emit=emit, operation=pdf, **({'conversation': context} if context is not None else {}))

        app.state.queue.add(job_id, run)
        return {"jobId": job_id}

    @app.get("/api/jobs/{identifier}")
    async def job(identifier: UUID, request: Request):
        return app.state.store.job(str(identifier), request.state.owner)

    @app.post("/api/jobs/{identifier}/cancel")
    async def cancel_job(identifier: UUID, request: Request):
        item = app.state.store.job(str(identifier), request.state.owner)
        app.state.queue.cancel(item["id"])
        return {"ok": True}

    @app.get("/api/jobs/{identifier}/events")
    async def job_events(identifier: UUID, request: Request):
        identifier = str(identifier)
        app.state.store.job(identifier, request.state.owner)
        cursor = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
        ensure(cursor.isascii() and cursor.isdecimal() and int(cursor) <= 2**53 - 1, "INVALID_EVENT_ID")

        async def events():
            after, ticks = int(cursor), 0
            while True:
                try:
                    for event in app.state.store.events(identifier, after):
                        yield f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                        after = event["id"]
                    item = app.state.store.job(identifier, request.state.owner)
                    if item["state"] in ("completed", "failed", "cancelled"):
                        return
                except AppError:
                    return
                ticks += 1
                if ticks % 50 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.3)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/jobs/{identifier}/annotated.pdf")
    async def annotated_pdf(identifier: UUID, request: Request):
        item = app.state.store.job(str(identifier), request.state.owner)
        case = app.state.store.get(item["caseId"], request.state.owner)
        ensure(item["state"] == "completed" and item["kind"] == "investigation", "RESULT_REQUIRED", 409)
        ensure(item["documentId"] == (case["document"] or {}).get("id"), "DOCUMENT_REPLACED", 409)
        ensure(app.state.exports < 2, "PDF_BUSY", 429)
        app.state.exports += 1
        output = root / case["id"] / f"{item['id']}.annotated.pdf"
        temporary = root / case["id"] / f"{uuid4()}.export.pdf"
        headers = {}
        try:
            if not output.exists():
                value = await pdf({"op": "annotate", "pdf": case["document"]["pdf"], "index": case["document"]["index"], "hits": item["result"]["quotes"], "output": str(temporary)})
                temporary.replace(output)
                headers = {"X-Highlight-Count": str(value["count"]), "X-Highlight-Skipped": str(value["skipped"])}
            # Bounded local PDF read keeps the download independent of a following case delete.
            return Response(output.read_bytes(), media_type="application/pdf", headers={**headers, "Content-Disposition": 'attachment; filename="insurelens-highlighted.pdf"'})
        finally:
            temporary.unlink(missing_ok=True)
            app.state.exports -= 1

    app.mount("/vendor/pdfjs", StaticFiles(directory=ROOT / "node_modules/pdfjs-dist", check_dir=False), name="pdfjs")
    app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="ui")
    return app


app = create_app()


def main():
    import uvicorn
    load_dotenv(ROOT / ".env", override=False)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), access_log=False)


if __name__ == "__main__":
    main()
