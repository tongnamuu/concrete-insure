"""Native in-process NAT workflow; no Node process or loopback HTTP bridge.

Only an opaque token crosses the NAT function boundary. Trusted request state,
server-owned paths, provider objects and progress callbacks stay in ContextVar.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from importlib.util import find_spec
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from insurelens.core import AppError


@dataclass(frozen=True)
class Invocation:
    token: str
    arguments: dict[str, Any]


_invocation: ContextVar[Invocation | None] = ContextVar("insurelens_nat_invocation", default=None)


def nat_available() -> bool:
    return find_spec("nat") is not None


def runner_mode() -> str:
    mode = os.environ.get("AGENT_RUNNER", "auto")
    if mode not in {"auto", "nat", "direct", "local"}:
        raise AppError("INVALID_AGENT_RUNNER")
    if mode in {"direct", "local"}:
        return "direct"
    available = nat_available()
    if mode == "nat" and not available:
        raise AppError("NAT_RUNTIME_MISSING", 503)
    return "nat" if available else "direct"


async def invoke_native(message: str) -> str:
    """NAT entry: resolve a token only inside the current server task context."""
    invocation = _invocation.get()
    if invocation is None or message != invocation.token:
        raise ValueError("NAT_INVOCATION_REQUIRED")
    from insurelens.agent import run_investigation

    result = await run_investigation(**invocation.arguments)
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


if nat_available():
    from nat.builder.builder import Builder
    from nat.builder.function_info import FunctionInfo
    from nat.cli.register_workflow import register_function
    from nat.data_models.function import FunctionBaseConfig
    from pydantic import Field

    class InsureLensConfig(FunctionBaseConfig, name="insurelens_python"):
        timeout_seconds: float = Field(default=600, ge=1, le=900)

    @register_function(config_type=InsureLensConfig)
    async def register(config: InsureLensConfig, builder: Builder):
        async def run(invocation_token: str) -> str:
            try:
                async with asyncio.timeout(config.timeout_seconds):
                    return await invoke_native(invocation_token)
            except TimeoutError:
                raise AppError("AGENT_TIMEOUT", 504) from None

        yield FunctionInfo.from_fn(
            run,
            description="Run InsureLens source-evidence subagents within an authorized Python server task. Input is an opaque invocation token only.",
        )


async def _run_configured(**arguments):
    if runner_mode() == "direct":
        from insurelens.agent import run_investigation
        return await run_investigation(**arguments)
    from nat.runtime.loader import load_workflow

    invocation = Invocation(uuid4().hex, arguments)
    handle = _invocation.set(invocation)
    try:
        config = Path(__file__).with_name("nat-workflow.yml")
        async with load_workflow(config) as manager:
            async with manager.session() as session:
                async with session.run(invocation.token) as runner:
                    encoded = await runner.result(to_type=str)
        result = json.loads(encoded)
        if not isinstance(result, dict) or not isinstance(result.get("quotes"), list):
            raise AppError("NAT_INVALID_RESULT", 502)
        return result
    finally:
        _invocation.reset(handle)


async def configured_investigation(**arguments):
    from insurelens.provider_fallback import with_provider_fallback
    return await with_provider_fallback(arguments, _run_configured)
