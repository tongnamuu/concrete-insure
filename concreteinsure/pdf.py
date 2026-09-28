"""Isolated PDF process: bounded output, timeout, and actual cancellation."""
import asyncio
import json
import os
from pathlib import Path
import sys

from .core import AppError
from .diagnostics import measured

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "python" / "pdf_worker.py"


async def pdf_operation(payload, *, timeout=120, python=None, worker=None):
    async with measured('pdf', payload.get('op', 'unknown'), timeout_seconds=timeout):
        return await _pdf_operation(payload, timeout=timeout, python=python, worker=worker)


async def _pdf_operation(payload, *, timeout=120, python=None, worker=None):
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            python or os.environ.get("PDF_PYTHON") or sys.executable,
            str(worker or WORKER),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(timeout):
            process.stdin.write(json.dumps(payload, ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            chunks, size = [], 0
            while chunk := await process.stdout.read(64 * 1024):
                size += len(chunk)
                if size > 40 * 1024 * 1024:
                    raise AppError("PDF_OUTPUT_LIMIT", 413)
                chunks.append(chunk)
            await process.wait()
        try:
            result = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError):
            raise AppError("PDF_WORKER_FAILED", 500) from None
        if result.get("error"):
            raise AppError(result["error"], 422)
        if process.returncode != 0 or "value" not in result:
            raise AppError("PDF_WORKER_FAILED", 500)
        return result["value"]
    except TimeoutError:
        raise AppError("PDF_TIMEOUT", 504) from None
    except FileNotFoundError:
        raise AppError("PDF_RUNTIME_MISSING", 503) from None
    except (BrokenPipeError, ConnectionResetError):
        raise AppError("PDF_WORKER_FAILED", 500) from None
    finally:
        if process is not None and process.returncode is None:
            async def reap():
                process.kill()
                # Drain the pipe after killing: wait() alone can deadlock on backpressure.
                while await process.stdout.read(64 * 1024):
                    pass
                await process.wait()
            cleanup = asyncio.create_task(reap())
            await asyncio.shield(cleanup)
