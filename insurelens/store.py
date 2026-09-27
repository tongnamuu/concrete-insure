"""SQLite persistence compatible with existing InsureLens local records."""
import asyncio
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from .core import ensure


def encoded(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.db = sqlite3.connect(self.root / "store.sqlite", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,owner TEXT NOT NULL,created INTEGER NOT NULL,document TEXT,products TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,result TEXT,error TEXT,created INTEGER NOT NULL,document_id TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,event TEXT NOT NULL,data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_job ON events(job_id,id);
        """)
        for row in self.db.execute("SELECT id FROM jobs WHERE state IN ('running','queued')").fetchall():
            self.state(row["id"], "failed", error="SERVER_RESTARTED")
            self.event(row["id"], "failed", {"code": "SERVER_RESTARTED"})

    def create(self, owner):
        ensure(self.db.execute("SELECT count(*) FROM cases").fetchone()[0] < 30, "CASE_LIMIT", 429)
        identifier = str(uuid4())
        self.db.execute("INSERT INTO cases(id,owner,created) VALUES(?,?,?)", (identifier, owner, int(time.time() * 1000)))
        return self.get(identifier, owner)

    def get(self, identifier, owner):
        row = self.db.execute("SELECT * FROM cases WHERE id=? AND owner=?", (identifier, owner)).fetchone()
        ensure(row, "CASE_NOT_FOUND", 404)
        result = dict(row)
        result["document"] = json.loads(row["document"]) if row["document"] else None
        result["products"] = json.loads(row["products"])
        return result

    def set_document(self, identifier, document):
        self.db.execute("UPDATE cases SET document=? WHERE id=?", (encoded(document), identifier))

    def set_products(self, identifier, products):
        self.db.execute("UPDATE cases SET products=? WHERE id=?", (encoded(products), identifier))

    def jobs(self, case_id):
        return [dict(r) for r in self.db.execute("SELECT id,state,kind,document_id AS documentId FROM jobs WHERE case_id=? ORDER BY created DESC,rowid DESC", (case_id,))]

    def job(self, identifier, owner):
        row = self.db.execute("SELECT jobs.* FROM jobs JOIN cases ON jobs.case_id=cases.id WHERE jobs.id=? AND cases.owner=?", (identifier, owner)).fetchone()
        ensure(row, "JOB_NOT_FOUND", 404)
        return {"id": row["id"], "caseId": row["case_id"], "kind": row["kind"], "state": row["state"], "result": json.loads(row["result"]) if row["result"] else None, "error": row["error"], "documentId": row["document_id"]}

    def create_job(self, case_id, kind, document_id=None):
        ensure(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] < 500, "JOB_LIMIT", 429)
        ensure(self.db.execute("SELECT count(*) FROM jobs WHERE case_id=? AND state IN ('queued','running')", (case_id,)).fetchone()[0] < 3, "CASE_BUSY", 429)
        identifier = str(uuid4())
        self.db.execute("INSERT INTO jobs(id,case_id,kind,state,created,document_id) VALUES(?,?,?,?,?,?)", (identifier, case_id, kind, "queued", int(time.time() * 1000), document_id))
        self.event(identifier, "queued", {})
        return identifier

    def state(self, identifier, state, result=None, error=None):
        self.db.execute("UPDATE jobs SET state=?,result=?,error=? WHERE id=?", (state, encoded(result), error, identifier))

    def event(self, identifier, event, data):
        self.db.execute("INSERT INTO events(job_id,event,data) VALUES(?,?,?)", (identifier, event, encoded(data)))

    def events(self, identifier, after=0):
        return [{**dict(r), "data": json.loads(r["data"])} for r in self.db.execute("SELECT id,event,data FROM events WHERE job_id=? AND id>? ORDER BY id", (identifier, after))]

    def remove(self, identifier):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE case_id=?)", (identifier,))
            self.db.execute("DELETE FROM jobs WHERE case_id=?", (identifier,))
            self.db.execute("DELETE FROM cases WHERE id=?", (identifier,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()


class Queue:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.controls = {}

    def add(self, identifier, fn):
        async def run():
            async with self.lock:
                self.store.state(identifier, "running")
                result = await fn(lambda event, data: self.store.event(identifier, event, data))
                self.store.state(identifier, "completed", result)
                self.store.event(identifier, "completed", {"resultUrl": f"/api/jobs/{identifier}"})

        task = asyncio.create_task(run(), name=f"insurelens:{identifier}")
        self.controls[identifier] = task

        def finished(done):
            self.controls.pop(identifier, None)
            if done.cancelled():
                state, code = "cancelled", "CANCELLED"
            elif error := done.exception():
                state, code = "failed", str(error)
                if not re.fullmatch(r"[A-Z_]{3,80}", code):
                    code = "PROCESSING_FAILED"
            else:
                return
            self.store.state(identifier, state, error=code)
            self.store.event(identifier, state, {"code": code})

        task.add_done_callback(finished)
        return task

    def cancel(self, identifier):
        if task := self.controls.get(identifier):
            task.cancel()

    async def cancel_case(self, case_id):
        tasks = [self.controls[j["id"]] for j in self.store.jobs(case_id) if j["id"] in self.controls]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        tasks = list(self.controls.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
