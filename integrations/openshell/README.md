# OpenShell integration boundary

`policy.yaml` is a deployment template based on the official [policy schema](https://docs.nvidia.com/openshell/latest/how-it-works/policies/schema). It is not automatically enabled by the local Node server. No NemoClaw dependency is used.

Only Node's configured NIM chat/OCR and MFDS API destinations are allowed. PDF Python has no network rule. `/app` is read-only except `/app/.local-data`; original user folders are not mounted. The concrete Linux image must contain the application and dependencies, nonroot UID1000, `/usr/local/bin/node`, and the configured Python runtime. Match binary paths to that image and validate the policy against the installed OpenShell release before claiming enforcement.

Official application pattern:

```sh
openshell sandbox create --from YOUR_PREBUILT_INSURELENS_IMAGE --policy integrations/openshell/policy.yaml -- node /app/src/server.js
```

The image is intentionally not built/published in this task. Configure gateway/provider credentials and web port forwarding using your installed OpenShell documentation; do not embed keys in images or policy. The current app binds localhost and validates Host/Origin; production reverse proxy/account support is outside this local demo. A self-hosted GPU OCR endpoint requires a separately reviewed destination rule. This template has not been executed in an OpenShell sandbox on this Mac and is not represented as a verified deployment.
