"""Registered NAT bridge. Planning stays in the Node bounded ReAct harness."""
import asyncio
import json
import os
import re
from urllib.parse import urlparse

import httpx
from pydantic import Field
from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig


class InsureLensConfig(FunctionBaseConfig, name="insurelens_evidence"):
    base_url: str = "http://127.0.0.1:8000"
    cookie_env: str = "INSURELENS_SESSION_COOKIE"
    timeout_seconds: float = Field(default=180, ge=1, le=600)


async def invoke_bridge(message: str, config: InsureLensConfig, transport=None) -> str:
    value = json.loads(message)
    if not isinstance(value, dict) or set(value) != {"caseId", "request"}:
        raise ValueError("Expected only caseId and request")
    case_id = value["caseId"]
    if not isinstance(case_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", case_id):
        raise ValueError("Invalid caseId")
    parsed = urlparse(config.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Only local InsureLens URLs are supported")
    cookie = os.environ.get(config.cookie_env)
    if not cookie:
        raise ValueError("Local session cookie environment variable is required")
    async with asyncio.timeout(config.timeout_seconds):
        async with httpx.AsyncClient(base_url=config.base_url, headers={"Cookie": cookie, "X-Local-Request": "1"}, transport=transport, follow_redirects=False) as client:
            submitted = await client.post(f"/api/cases/{case_id}/investigations", json=value["request"])
            submitted.raise_for_status()
            job_id = submitted.json()["jobId"]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", job_id):
                raise ValueError("Invalid jobId")
            while True:
                response = await client.get(f"/api/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if job["state"] == "completed":
                    # Return API-owned source results; no model paraphrase here.
                    return json.dumps(job["result"], ensure_ascii=False)
                if job["state"] in {"failed", "cancelled"}:
                    raise ValueError("Investigation failed or was cancelled")
                await asyncio.sleep(0.25)


@register_function(config_type=InsureLensConfig)
async def register(config: InsureLensConfig, builder: Builder):
    async def run(message: str) -> str:
        return await invoke_bridge(message, config)
    yield FunctionInfo.from_fn(run, description="Retrieve verbatim insurance source evidence through the local InsureLens API; never judge eligibility.")


class InsureLensLocalConfig(FunctionBaseConfig, name="insurelens_local"):
    timeout_seconds: float = Field(default=600, ge=1, le=900)


@register_function(config_type=InsureLensLocalConfig)
async def register_local(config: InsureLensLocalConfig, builder: Builder):
    async def run(message: str) -> str:
        from pathlib import Path
        value = json.loads(message)
        if not isinstance(value, dict) or set(value) != {"document", "request", "products"}:
            raise ValueError("Invalid internal workflow payload")
        project = Path(__file__).resolve().parents[4]
        # Internal-only stdin supplied by API server. Never expose this process runner as a public endpoint.
        process = await asyncio.create_subprocess_exec(
            os.environ.get("NODE_EXECUTABLE", "node"), str(project / "src" / "runner.js"),
            cwd=str(project), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(config.timeout_seconds):
                stdout, _ = await process.communicate(message.encode())
            if process.returncode != 0:
                raise ValueError("NODE_WORKFLOW_FAILED")
            if len(stdout) > 8_000_000:
                raise ValueError("WORKFLOW_OUTPUT_LIMIT")
            result = json.loads(stdout)
            if not isinstance(result, dict) or set(result) != {"quotes", "mappings", "references", "terms", "notice", "mode", "truncated", "coverage"}:
                raise ValueError("INVALID_WORKFLOW_RESULT")
            return json.dumps(result, ensure_ascii=False)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    yield FunctionInfo.from_fn(run, description="Run the InsureLens structured source-retrieval subagents through the local Node ReAct harness.")
