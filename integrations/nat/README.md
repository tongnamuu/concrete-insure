# Native Python NAT integration

Install from the project root: `uv pip install --python .venv/bin/python -e '.[nat]'`.
The root package registers `insurelens.nat` in `nat.components`; `_type: insurelens_python` runs the Python evidence agent directly.

`AGENT_RUNNER=auto` uses NAT when installed, otherwise direct Python execution. `nat` requires NAT; `direct` (alias `local`) bypasses NAT. These control orchestration, not model choice: NIM still follows consent and provider configuration.

Flow: FastAPI job → configured_investigation → provider fallback wrapper → native NAT load_workflow/session → Python run_investigation → source result.

Only an unpredictable invocation token enters the NAT function schema. Server-owned paths, request and provider objects, and the synchronous SSE emit callback stay in an asyncio ContextVar. The function refuses calls outside an authorized task. Concurrent tasks remain isolated, and cancellation propagates through await to the agent. There is no Node subprocess, stdin JSON relay, session-cookie bridge, or local HTTP roundtrip.

The YAML describes an internal workflow, not a public CLI accepting file paths. Use the web app/API to start work. The custom registered NAT function hosts the application's bounded ReAct loop; it does not claim to be NAT's generic ReAct agent.

Run `python -m pytest tests/test_nat.py` from the project root after installing test dependencies. Tests exercise actual NAT runtime, token isolation, callback propagation, cancellation, and direct mode.
