import asyncio
import json
import sqlite3

import pytest

from concreteinsure.core import AppError
from concreteinsure.store import Queue, Store


def test_persisted_schema_and_restart_ownership(tmp_path):
    store = Store(tmp_path)
    case = store.create("owner")
    doc = {"id": "existing-node-document", "pdf": "/existing.pdf", "index": "/existing.gz"}
    store.set_document(case["id"], doc)
    job = store.create_job(case["id"], "document")
    store.state(job, "running")
    first = store.events(job)[0]["id"]
    store.event(job, "stage_started", {"stage": "document"})
    assert len(store.events(job, first)) == 1
    store.close()
    reopened = Store(tmp_path)
    try:
        assert reopened.get(case["id"], "owner")["document"] == doc
        assert reopened.job(job, "owner")["error"] == "SERVER_RESTARTED"
        assert reopened.events(job)[-1]["event"] == "failed"
        with pytest.raises(AppError, match="CASE_NOT_FOUND"):
            reopened.get(case["id"], "other")
    finally:
        reopened.close()


async def test_queue_cancel_before_start_and_serial_order(tmp_path):
    store, calls = Store(tmp_path), []
    queue = Queue(store)
    case = store.create("owner")
    ids = [store.create_job(case["id"], "investigation") for _ in range(3)]
    async def fn(emit):
        calls.append("start")
        await asyncio.sleep(0.01)
        calls.append("end")
        return {"safe": True}
    tasks = [queue.add(identifier, fn) for identifier in ids]
    queue.cancel(ids[0])
    await asyncio.gather(*tasks, return_exceptions=True)
    assert store.job(ids[0], "owner")["state"] == "cancelled"
    assert store.job(ids[0], "owner")["result"] is None
    assert calls == ["start", "end", "start", "end"]
    assert store.job(ids[-1], "owner")["state"] == "completed"
    await queue.close()
    store.close()
