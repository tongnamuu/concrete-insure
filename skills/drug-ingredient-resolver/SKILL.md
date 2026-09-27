---
name: drug-ingredient-resolver
description: Query official MFDS product candidates and retrieve source-bound ingredient and label references for an explicitly selected product. Never infer diagnosis or insurance eligibility.
---

# MFDS medicine evidence

Run `insurelens-skill drug-ingredient-resolver` with one JSON stdin object. The project `.env` must contain `MFDS_API_KEY`, issued after applying for [MFDS Drug Product Approval Information](https://www.data.go.kr/data/15095677/openapi.do). There is no local product catalog or no-key substitute.

- Product lookup: `{"op":"lookup","name":"제품명"}`. Sends the name to MFDS and returns candidates, total, truncated and requiresSelection. Ask the user to select the actual product, including strength and formulation. A single candidate still requires confirmation.
- Selected product detail: `{"op":"detail","itemId":"202012345"}`. Use a confirmed item ID from lookup, never an invented ID. Returns the product and references with original quotes, field/paragraph identifiers, document hashes, official URL, retrieval time and document change date. The numeric value above is a schema example, not a product recommendation.
- `from-text` has been removed. The web input agent selects only literal drug names, then calls these shared Python tools. The web runtime does not spawn the CLI.

Use `DrugPrdtPrmsnInfoService08`: list via `getDrugPrdtPrmsnInq08`, detail via `getDrugPrdtPrmsnDtlInq08`, missing ingredient fields via `getDrugPrdtMcpnDtlInq08`. Keep API keys out of prompts, output and logs. Failed authentication, missing records, malformed documents and timeouts must remain explicit failures.

Preserve source quotes, ingredient salts and formulation qualifiers. An explicit supported active-metabolite sentence may supply a literal search term; never infer a relationship by stripping suffixes. Keep treatment and prophylaxis evidence distinct. Product facts are not patient facts. Current records do not establish historical approval or insurance coverage. Selected text must remain a literal portion of official fields or parsed document paragraphs. Do not fabricate evidence when a relation cannot be established.
