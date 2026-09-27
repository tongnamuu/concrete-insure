"""Internal server -> native NAT -> Node subagent workflow. stdin JSON / stdout JSON."""
import asyncio
import contextlib
import json
import sys
from pathlib import Path
from nat.runtime.loader import load_workflow

async def main():
    raw = sys.stdin.buffer.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("WORKFLOW_INPUT_LIMIT")
    message = json.dumps(json.loads(raw), ensure_ascii=False)
    with contextlib.redirect_stdout(sys.stderr):
        async with load_workflow(Path(__file__).with_name("local-workflow.yml")) as manager:
            async with manager.session() as session:
                async with session.run(message) as runner:
                    result = await runner.result(to_type=str)
    sys.stdout.write(result)

if __name__ == '__main__':
    asyncio.run(main())
