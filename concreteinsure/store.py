"""SQLite persistence compatible with existing concreteInsure local records."""
import asyncio
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from .core import ensure
from .diagnostics import failure_fields, log_context, record


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
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,document_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns(job_id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,input TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS conversation_case ON conversations(case_id,document_id);
            CREATE INDEX IF NOT EXISTS turn_conversation ON turns(conversation_id);
            CREATE TABLE IF NOT EXISTS selection_checkpoints(job_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,document_id TEXT NOT NULL,conversation_id TEXT,payload TEXT NOT NULL,resume_job_id TEXT,selected TEXT);
            CREATE INDEX IF NOT EXISTS selection_resume ON selection_checkpoints(resume_job_id);

        """)
        for row in self.db.execute("SELECT id FROM jobs WHERE state IN ('running','queued')").fetchall():
            self.state(row["id"], "failed", error="SERVER_RESTARTED")
            self.event(row["id"], "failed", {"code": "SERVER_RESTARTED"})
            record("job.finished", job_id=row["id"], state="failed", code="SERVER_RESTARTED")

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

    def conversation(self, case_id, document_id):
        row = self.db.execute("SELECT id FROM conversations WHERE case_id=? AND document_id=? ORDER BY rowid DESC LIMIT 1", (case_id, document_id)).fetchone()
        if row is None:
            return {"id": None, "turns": []}
        turns = []
        for item in self.db.execute("SELECT turns.input,jobs.* FROM turns JOIN jobs ON jobs.id=turns.job_id WHERE conversation_id=? ORDER BY turns.rowid", (row['id'],)):
            request = json.loads(item['input'])
            turns.append({"jobId": item['id'], "query": request['query'], "description": request['description'],
                          "confirmedTerms": request['confirmedTerms'], "state": item['state'], "error": item['error'],
                          "result": json.loads(item['result']) if item['result'] else None})
        for turn in turns:
            cp = self.db.execute("SELECT * FROM selection_checkpoints WHERE job_id=? OR resume_job_id=?", (turn['jobId'], turn['jobId'])).fetchone()
            pending = (turn.get('result') or {}).get('requiresDrugSelection')
            if cp and (pending or turn['state'] in ('failed', 'cancelled')):
                payload = json.loads(cp['payload'])
                turn['resume'] = {'jobId': cp['job_id'], 'products': list(payload['products'].values()),
                                  'selectedIds': json.loads(cp['selected']) if cp['selected'] else payload['request'].get('drugIds', [])}
            elif pending:
                # Older saved selection results contain the validated terms and names.
                # The resume endpoint reconstructs the snapshot using this stored turn.
                turn['resume'] = {'jobId': turn['jobId'], 'products': turn['result']['products'], 'selectedIds': []}
        return {"id": row['id'], "turns": turns}

    def new_conversation(self, case_id, document_id):
        ensure(self.db.execute("SELECT count(*) FROM conversations WHERE case_id=?", (case_id,)).fetchone()[0] < 100, "CONVERSATION_LIMIT", 429)
        identifier = str(uuid4())
        self.db.execute("INSERT INTO conversations VALUES(?,?,?)", (identifier, case_id, document_id))
        return {"id": identifier, "turns": []}

    def add_turn(self, conversation_id, job_id, request):
        # Persist user text and explicitly confirmed candidates, never credentials or consent tokens.
        self.db.execute("INSERT INTO turns VALUES(?,?,?)", (job_id, conversation_id, encoded({k: request[k] for k in ('query','description','confirmedTerms')})))

    def save_selection(self, job_id, case_id, document_id, conversation_id, payload):
        self.db.execute("INSERT INTO selection_checkpoints(job_id,case_id,document_id,conversation_id,payload) VALUES(?,?,?,?,?)",
                        (job_id, case_id, document_id, conversation_id, encoded(payload)))

    def selection(self, job_id):
        row = self.db.execute("SELECT * FROM selection_checkpoints WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), 'payload': json.loads(row['payload']), 'selected': json.loads(row['selected'] or '[]')}

    def resume_selection(self, checkpoint, selected):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            current = self.selection(checkpoint['job_id'])
            previous = current['resume_job_id']
            if previous:
                state = self.db.execute('SELECT state FROM jobs WHERE id=?', (previous,)).fetchone()['state']
                if state not in ('failed', 'cancelled'):
                    ensure(set(current['selected']) == set(selected), 'SELECTION_ALREADY_RESUMED', 409)
                    self.db.execute('COMMIT')
                    return previous, False
            job_id = self.create_job(current['case_id'], 'investigation', current['document_id'])
            updated = self.db.execute('UPDATE turns SET job_id=? WHERE job_id=?', (job_id, previous or current['job_id']))
            ensure(not current['conversation_id'] or updated.rowcount == 1, 'SELECTION_EXPIRED', 409)
            self.db.execute('UPDATE selection_checkpoints SET resume_job_id=?,selected=? WHERE job_id=?',
                            (job_id, encoded(selected), current['job_id']))
            self.db.execute('COMMIT')
            return job_id, True
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def remove(self, identifier):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("DELETE FROM selection_checkpoints WHERE case_id=?", (identifier,))
            self.db.execute("DELETE FROM turns WHERE conversation_id IN (SELECT id FROM conversations WHERE case_id=?)", (identifier,))
            self.db.execute("DELETE FROM conversations WHERE case_id=?", (identifier,))
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
        submitted = time.monotonic()

        def emit(event, data):
            self.store.event(identifier, event, data)
            if event in {'stage_started', 'stage_progress', 'stage_completed'}:
                record('job.stage', stage_event=event, stage=data.get('stage'), elapsed_seconds=data.get('elapsedSeconds'))

        async def run():
            async with self.lock:
                record("job.started", wait_ms=(time.monotonic()-submitted)*1000)
                self.store.state(identifier, "running")
                result = await fn(emit)
                self.store.state(identifier, "completed", result)
                self.store.event(identifier, "completed", {"resultUrl": f"/api/jobs/{identifier}"})

        def finished(done):
            self.controls.pop(identifier, None)
            if done.cancelled():
                state, code = "cancelled", "CANCELLED"
            elif error := done.exception():
                state, code = "failed", failure_fields(error)["code"]
                if not re.fullmatch(r"[A-Z_]{3,80}", code):
                    code = "PROCESSING_FAILED"
            else:
                record("job.finished", state="completed", duration_ms=(time.monotonic()-submitted)*1000)
                return
            record("job.finished", state=state, code=code, duration_ms=(time.monotonic()-submitted)*1000,
                   error_type=type(error).__name__ if not done.cancelled() else "CancelledError")
            self.store.state(identifier, state, error=code)
            self.store.event(identifier, state, {"code": code})

        with log_context(job_id=identifier):
            record('job.queued')
            task = asyncio.create_task(run(), name=f'concreteinsure:{identifier}')
            self.controls[identifier] = task
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
