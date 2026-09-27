import asyncio
import os
import sys

import pytest

from insurelens.core import AppError
from insurelens.pdf import pdf_operation


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancel_reaps_worker(tmp_path, cancel):
    worker = tmp_path / "sleep.py"
    pidfile = tmp_path / "pid"
    worker.write_text("import os,time\nfrom pathlib import Path\nPath(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\ntime.sleep(60)\n")
    task = asyncio.create_task(pdf_operation({}, timeout=10 if cancel else 0.3, worker=worker))
    async with asyncio.timeout(5):
        while not pidfile.exists():
            await asyncio.sleep(0.01)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(AppError, match="PDF_TIMEOUT"):
            await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)

async def test_worker_stdout_backpressure_cannot_block_timeout(tmp_path):
    worker = tmp_path / 'blocked.py'
    worker.write_text("import sys,time\nsys.stdout.buffer.write(b'x'*(64*1024*1024))\nsys.stdout.flush()\nsys.stdin.buffer.read()\ntime.sleep(60)\n")
    async with asyncio.timeout(5):
        with pytest.raises(AppError, match='PDF_TIMEOUT'):
            await pdf_operation({'large': 'x' * (4 * 1024 * 1024)}, timeout=0.1, worker=worker)
