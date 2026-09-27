# Native NVIDIA NeMo Agent Toolkit integration

This is an actual Python NAT registered workflow (`insurelens_evidence`), not a JavaScript imitation of NAT. It bridges to the running Node application; **the bounded Nemotron ReAct planner runs in Node**, not in NAT's generic agent. NAT provides workflow registration, configuration, execution and surrounding profiling integration. Browser SSE remains the primary UI.

```sh
uv venv integrations/nat/.venv --python 3.13
uv pip install --python integrations/nat/.venv/bin/python -e integrations/nat
integrations/nat/.venv/bin/python integrations/nat/test_bridge.py
NAT_CONFIG_DIR=/tmp/insurelens-nat integrations/nat/.venv/bin/nat info components -t function
```

For a real invocation start the web app, upload a policy, and use a case owned by that session. Supply the local session cookie securely through environment variable `INSURELENS_SESSION_COOKIE` (the full `insurelens_session=…` cookie string). Do not put it in YAML, source control, a shared command transcript, or the downloadable project. A wrong session cannot access the case.

```sh
integrations/nat/.venv/bin/nat run --config_file integrations/nat/workflow.yml --input '{"caseId":"YOUR_CASE_ID","request":{"query":"독감 관련 원문을 찾아줘","confirmedTerms":[],"drugIds":[],"cloudConsent":false,"translation":false}}'
```

No NVIDIA key is required for the local bridge tests or deterministic retrieval. Cloud ReAct additionally requires server-side NVIDIA configuration and explicit cloudConsent. Cancellation/timeout of a NAT client does not automatically cancel the shared browser job; use the web cancel control if required. Only loopback HTTP endpoints are accepted. Remote deployment would need a separately designed authenticated service API.

Official API basis: [NAT custom function registration](https://docs.nvidia.com/nemo/agent-toolkit/1.5/extend/custom-components/custom-functions/functions.html). Runtime dependency pinned to `nvidia-nat==1.9.0`; the older 1.5 documentation demonstrates the same registration API, verified against the installed version by tests.

## Web-native NAT execution

`AGENT_RUNNER=nat` selects `run_local.py`, which loads the native `insurelens_local` registered workflow with NAT `load_workflow`. Its function launches the Node subagent harness through private stdin/stdout. The API never forwards arbitrary paths from HTTP users: document paths belong to server-owned case records. This is real NAT workflow execution around the custom ReAct implementation; it does not claim to use NAT’s built-in generic ReAct agent. `NODE_EXECUTABLE` can select the Node binary. Outer process-group cancellation stops both NAT and the child.
