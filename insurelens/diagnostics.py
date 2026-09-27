"""Bounded, structured diagnostics. Never accept request/response bodies."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import re
import time
from uuid import UUID

from .core import AppError

_context = ContextVar('insurelens_diagnostics', default={})
EVENTS = {'app.started', 'app.stopped', 'request.completed', 'request.error',
          'job.queued', 'job.started', 'job.stage', 'job.finished',
          'operation.started', 'operation.completed', 'operation.failed',
          'operation.cancelled', 'provider.response'}
ENUMS = {
    'category': {'nim', 'ocr', 'mfds', 'pdf'},
    'operation': {'chat', 'tools', 'http', 'index', 'search', 'context', 'sections', 'annotate', 'unknown'},
    'stage': {'input', 'translation', 'planning', 'retrieval', 'drug_reference', 'policy_scope', 'verification', 'document', 'ocr'},
    'stage_event': {'stage_started', 'stage_progress', 'stage_completed'},
    'state': {'completed', 'failed', 'cancelled'},
    'method': {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'},
    'finish_reason': {'stop', 'length', 'tool_calls', 'content_filter', 'function_call'},
    'response_mode': {'schema', 'json', 'tools'},
}
ROUTES = {'/', '/vendor/pdfjs', '/api/config', '/api/cases', '/api/cases/{identifier}',
          '/api/cases/{identifier}/documents', '/api/cases/{identifier}/ocr',
          '/api/cases/{identifier}/drugs', '/api/cases/{identifier}/pdf',
          '/api/cases/{identifier}/investigations', '/api/jobs/{identifier}',
          '/api/jobs/{identifier}/cancel', '/api/jobs/{identifier}/events',
          '/api/jobs/{identifier}/annotated.pdf'}
NUMBERS = {'duration_ms', 'wait_ms', 'elapsed_seconds', 'timeout_seconds', 'status',
           'prompt_tokens', 'completion_tokens', 'total_tokens'}


def safe_fields(fields):
    result = {}
    for name, value in fields.items():
        if name in ('request_id', 'job_id') and isinstance(value, str):
            try:
                result[name] = str(UUID(value))
            except ValueError:
                pass
        elif name in ENUMS and isinstance(value, str) and value in ENUMS[name]:
            result[name] = value
        elif name in NUMBERS and type(value) in (int, float) and 0 <= value <= 1e15 and math.isfinite(value):
            result[name] = round(value, 2)
        elif name == 'route':
            result[name] = value if isinstance(value, str) and value in ROUTES else 'unmatched'
        elif name == 'code' and isinstance(value, str) and re.fullmatch(r'[A-Z_]{3,80}', value):
            result[name] = value
        elif name == 'error_type' and isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', value):
            result[name] = value
        elif name == 'model':
            result[name] = value if isinstance(value, str) and re.fullmatch(r'nvidia/[a-z0-9._-]{1,100}', value) else 'custom'
    return result


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding)


class RuntimeLog:
    def __init__(self, folder, *, max_bytes=5 * 1024 * 1024, backups=3):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        self.path = folder / 'insurelens.jsonl'
        self.logger = logging.Logger('insurelens.runtime', level=logging.INFO)
        self.logger.propagate = False
        self.handler = PrivateRotatingHandler(self.path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(self.handler)

    def write(self, event, **fields):
        if event not in EVENTS:
            return
        context = {key: value for key, value in _context.get().items() if key in ('request_id', 'job_id')}
        level = 'ERROR' if event in {'request.error', 'operation.failed'} or fields.get('state') == 'failed' else 'INFO'
        value = {'timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                 'level': level, 'event': event, **safe_fields({**context, **fields})}
        self.logger.log(logging.ERROR if level == 'ERROR' else logging.INFO, json.dumps(value, ensure_ascii=False, allow_nan=False))

    def close(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()


@contextmanager
def log_context(logger=None, **fields):
    context = {**_context.get(), **safe_fields(fields)}
    if logger is not None:
        context['logger'] = logger
    token = _context.set(context)
    try:
        yield
    finally:
        _context.reset(token)


def record(event, **fields):
    if logger := _context.get().get('logger'):
        logger.write(event, **fields)


def failure_fields(error):
    # Exception text, traceback locals and provider payloads may contain secrets.
    return {'code': error.code if isinstance(error, AppError) else 'PROCESSING_FAILED',
            'error_type': type(error).__name__}


@asynccontextmanager
async def measured(category, operation, **fields):
    started = time.monotonic()
    fields = {'category': category, 'operation': operation, **fields}
    record('operation.started', **fields)
    try:
        yield
    except asyncio.CancelledError:
        record('operation.cancelled', **fields, duration_ms=(time.monotonic()-started)*1000)
        raise
    except Exception as error:
        record('operation.failed', **fields, duration_ms=(time.monotonic()-started)*1000, **failure_fields(error))
        raise
    else:
        record('operation.completed', **fields, duration_ms=(time.monotonic()-started)*1000)
