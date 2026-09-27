# OpenShell integration boundary

`policy.yaml` is a deployment template based on the official [policy schema](https://docs.nvidia.com/openshell/latest/how-it-works/policies/schema). It is not automatically enabled by the local Python server. No NemoClaw dependency is used.

The Python executable is allowed to reach configured NIM chat/OCR and MFDS destinations. This process-level policy does not isolate the PDF worker from network access when it uses the same interpreter. Stronger separation requires a distinct worker image/executable and policy. `/app` is read-only except `/app/.local-data`; original user folders are not mounted. The concrete Linux image must contain the application and dependencies, nonroot UID1000, `/app/.venv/bin/python`, and the configured Python runtime. Match binary paths to that image and validate the policy against the installed OpenShell release before claiming enforcement.

Official application pattern:

```sh
openshell sandbox create --from YOUR_PREBUILT_INSURELENS_IMAGE --policy integrations/openshell/policy.yaml -- /app/.venv/bin/python -m insurelens.server
```

The image is intentionally not built/published in this task. Configure gateway/provider credentials and web port forwarding using your installed OpenShell documentation; do not embed keys in images or policy. The current app binds localhost and validates Host/Origin; production reverse proxy/account support is outside this local demo. A self-hosted GPU OCR endpoint requires a separately reviewed destination rule. This template has not been executed in an OpenShell sandbox on this Mac and is not represented as a verified deployment.
