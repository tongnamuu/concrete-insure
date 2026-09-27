"""Native in-process NAT workflow; no Node process or loopback HTTP bridge.

Only an opaque token crosses the NAT function boundary. Trusted request state,
server-owned paths, provider objects and progress callbacks stay in ContextVar.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from insurelens.core import AppError, ensure


@dataclass(frozen=True)
class Invocation:
    token: str
    arguments: dict[str, Any]


_invocation: ContextVar[Invocation | None] = ContextVar("insurelens_nat_invocation", default=None)


async def invoke_native(message: str) -> str:
    """NAT entry: resolve a token only inside the current server task context."""
    invocation = _invocation.get()
    if invocation is None or message != invocation.token:
        raise ValueError("NAT_INVOCATION_REQUIRED")
    from insurelens.agent import run_investigation

    result = await run_investigation(**invocation.arguments)
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


try:
    from nat.builder.builder import Builder
    from nat.builder.function_info import FunctionInfo
    from nat.cli.register_workflow import register_function
    from nat.data_models.function import FunctionBaseConfig
    from nat.runtime.loader import load_workflow
except ModuleNotFoundError as error:
    raise AppError("NAT_RUNTIME_MISSING", 503) from error
from pydantic import Field


class InsureLensConfig(FunctionBaseConfig, name="insurelens_python"):
    timeout_seconds: float = Field(default=1200, ge=1, le=3600)


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


async def configured_investigation(**arguments):
    """Every investigation uses NAT and NIM; failures terminate the job."""
    ensure(getattr(arguments.get("nim"), "enabled", False), "NVIDIA_KEY_REQUIRED", 409)
    ensure(arguments.get("request", {}).get("cloudConsent") is True, "NIM_CONSENT_REQUIRED", 409)

    invocation = Invocation(uuid4().hex, arguments)
    handle = _invocation.set(invocation)
    try:
        config = Path(__file__).with_name("nat-workflow.yml")
        async with load_workflow(config) as manager:
            async with manager.session() as session:
                async with session.run(invocation.token) as runner:
                    encoded = await runner.result(to_type=str)
        result = json.loads(encoded)
        if not isinstance(result, dict) or not isinstance(result.get("quotes"), list) or result.get("mode") != "nim-react":
            raise AppError("NAT_INVALID_RESULT", 502)
        return result
    finally:
        _invocation.reset(handle)
