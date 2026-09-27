---
name: drug-ingredient-resolver
description: Resolve medicine names to sourced ingredient references or explicitly query official MFDS product candidates. Use for evidence-backed brand and ingredient lookup, not diagnosis inference or insurance payment decisions.
---

# Sourced drug ingredients

Use `insurelens-skill drug-ingredient-resolver` with one JSON stdin object after installing the project Python runtime. Alternatively use `.venv/bin/python -m insurelens.skills_cli drug-ingredient-resolver` from the project.

- Curated local references: `{"op":"from-text","text":"조플루자를 처방받았습니다."}`. Returns the existing verified catalog entries with unchanged `source` and `facts[].quote`, plus literal search terms. This mode never performs a live lookup. Empty references mean no catalog match, not absence of a product or benefit.
- Explicit live MFDS search: `{"op":"lookup","name":"타미플루"}`. Requires `MFDS_API_KEY` in the project `.env`. Returns official product candidates, source URL, retrieval time, and `requiresSelection:true`. Keep manufacturer, strength, and formulation ambiguity visible and let the user select the actual product.

Present product/ingredient facts separately from policy quotations. Preserve source quotations and URLs; do not invent mappings, strip prodrug suffixes to fabricate a match, treat a manufacturer's reference as historical regulatory approval, or infer the user's illness. An ingredient match is not a conclusion about enrollment, benefit applicability, or payment.

The CLI delegates to the existing catalog resolver/validator and MFDS provider. The web runtime calls shared Python functions directly, not this CLI subprocess. Errors are JSON codes with nonzero exit status; never print API keys.
