# InsureLens architecture and boundaries

The final user specification supersedes the earlier claim-screening proposal: no eligibility decision, no claim recommendation, no diagnosis inference, no paraphrase or summary of policy. Latest language request is Node.js; a Python PDF subprocess is used for exact text-layer glyph geometry and standards-based annotation. Native NAT is a Python integration, not a fictitious JS package. NemoClaw remains excluded; web is the only user-facing interface.

## Runtime modules

| Module | Implementation | Input/output contract |
|---|---|---|
| Intake and job API | src/server.js,src/store.js | Authenticated case-scoped uploads and jobs, replayable SSE |
| Document worker | src/pdf.js,python/pdf_worker.py | Original PDF → packed glyph index; source hits; annotation bytes |
| Prescription reading | Nvidia.ocr, PDF text/render tools | Image or prescription PDF → draft text requiring confirmation |
| Input subagent | src/agents/input.js | User query/situation description/confirmed text → literal terms |
| Drug identity subagent | src/agents/drug.js,Drugs.lookup | User-selected official product → unchanged ingredient fields |
| Product reference resolver | src/agents/drug-references.js,data/drug-references.json | Explicit brand → cited manufacturer facts → grounded retrieval terms; never a clinical fact |
| Policy retrieval subagent | src/agents/retrieval.js | Grounded term IDs or known source IDs → original spans |
| ReAct supervisor | src/agent.js | NIM native tool calls → tools → observations → next turn |
| Evidence assembly | src/agents/verification.js | Trusted source objects → structured result; no prose generation |
| Web viewer | public/ | 1:1 split, uploads, explicit confirmation, source cards, PDF text-layer highlights |

See contracts.md for exact fields. A prescription can be replaced by a free-text description (up to4,000characters). Description-only requests are valid. The description remains a separate, unchanged user statement and is never labelled as a verified clinical record. Exact-substring grounding covers query and description separately. Deterministic subagents deliberately do not make needless model calls. Each has a single responsibility and testable boundary. ReAct is applied where an observation changes the next retrieval action, not to calculation of coordinates or source slices.

## Provider connections

Nemotron/NIM: OpenAI-compatible chat completions using native tool_calls and finish_reason. No key means explicitly labelled deterministic local mode. Never substitute fabricated cloud results. Hosted OCR uses its distinct documented input/image_url schema, not chat-completions messages. Configure the actual multilingual OCR endpoint after verifying account/model access. Hosted JSON extraction and native tool calls have been tested with a real key using public/synthetic data. See validation.md for full workflow results and limitations. No actual user medical document was used in cloud testing.

MFDS: official DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08. The public Swagger on data.go.kr as retrieved2026-09-27 names this v08 endpoint. Decoder preserves ITEM_INGR_NAME; no unsourced salt removal, brand alias or code-to-disease conversion. Product selection is explicit. Main-ingredient string equality or a quote match is never labelled medically/contractually suitable. Disease codes are searched literally; no KCD meanings are invented.

Translation: optional separately configured model supplies English glosses to the supervisor. Original term IDs, user input and quotes remain immutable. Glosses do not become search terms or source evidence. General Korean↔English free-text translation is not lossless, so no automatic round-trip translation of policy is implemented. A lighter model can be configured; it is not presumed faster without benchmark.

## Persistence and events

SQLite stores cases, official product lookup records, job state/results and event IDs. Original PDF/index files stay under a mode0700 local data directory. Browser reconnect replays SSE event IDs; completion fetches persisted results. Jobs run in a bounded in-process serial queue; PDF work runs in a killable subprocess. A process restart preserves completed results and marks interrupted jobs SERVER_RESTARTED for explicit retry. This is not a distributed, automatically resumed queue. User deletion removes case files and persisted results. Cookie ownership is for a local single-user demo, not production account authentication.

## PDF contract

Extracted text is rawdict reading order with explicit synthetic line-break separators. Verbatim means a byte-for-byte-equal Unicode slice of that stored extraction text, not original compressed PDF content streams. Offsets use Unicode code points. Float64 glyph quads preserve rotated/cropped geometry; no proportional splitting of text runs. OCR results never silently replace policy text. Policies without text layer are rejected, because OCR cannot promise verbatim source fidelity.

Export adds native Highlight annotations, QuadPoints, source quote Contents and normal appearance streams through PyMuPDF. Original extracted text is checked in tests. This implements standard PDF annotations, not a claim of complete ISO32000 conformance certification. Digital signatures may be invalidated by PDF modification; the uploaded original stays separate. Missing glyph geometry is reported, not approximated.

## Official sources checked

- ReAct protocol: https://nvdli.github.io/NemoClawDLI/nemoclaw/01b-react.html#the-react-loop
- NAT public plugin API: https://docs.nvidia.com/nemo/agent-toolkit/latest/extend/plugin-api.html
- OCR API: https://docs.nvidia.com/nim/ingestion/image-ocr/latest/use-the-api.html
- OCR multilingual model: https://huggingface.co/nvidia/nemotron-ocr-v2
- Drug product/ingredient API: https://www.data.go.kr/data/15095677/openapi.do
- Agent Skills: https://github.com/NVIDIA/skills and https://www.skills.sh/docs
- SkillSpector: https://github.com/NVIDIA/SkillSpector
- OpenShell: https://docs.nvidia.com/openshell/latest/how-it-works/policies/schema

No documented generic build.nvidia.com "Skill API" was verified. Therefore this application uses documented NIM model endpoints and skills.sh-compatible local SKILL.md, and does not fabricate a skill execution URL. NeMo-Skills model-training project is distinct from Agent Skills; training is not included.

## Product-reference bridge

A literal brand absent from a policy is not a negative coverage result. The reviewed catalog currently covers Xofluza and Tamiflu only. Xofluza's manufacturer document distinguishes the prodrug ingredient from active metabolite baloxavir; separate short verbatim citations support the relationship. Search terms must be substrings of catalog citations and catalog facts must pass exact verification. The catalog is dated reference data, not a live MFDS response or historical approval certification.

Ingredient hits anchor nearby pages before broader product-indication terms are searched. Explicit user terms retain full-document search scope. This keeps related influenza sections visible without searching the entire policy for every product-indication word. Source spans and quads still come only from the PDF worker. Conversational fillers are excluded from candidate terms; explicitly confirmed terms are preserved.

Official source: https://www.roche.co.kr/solutions/pharma-solutions/xofluza and the linked 2026-09-09 product document; catalog records checked2026-09-27. Structured generation reference: https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html .

The supervisor exposes an empty-argument finish_retrieval tool so native callers can terminate after source inspection. A model protocol failure ends that run; the adapter can launch a fresh deterministic investigation and label its result local with warning codes. Source-integrity failures, ungrounded terms and cancellation are not silently recovered.

## Policy benefit and source grouping

The application can identify an expressly described benefit and distinguish direct wording from an indirect ingredient link. `policy-scope.js` reads grouped source articles after retrieval and returns source IDs, fixed connection labels and pending verification items. It never generates policy quotations or predicts a payout. `pdf_worker.sections` recognizes numbered special-rider titles, handles nested parentheses in article headings and stops at the next rider. Source spans are merged contiguously within each page without rewriting. Unknown layouts and weak/negative connections remain unresolved. Referenced general provisions/appendices are flagged for further verification, not presumed satisfied. Blank context is filtered both server-side and in the viewer; duplicated glyph highlights are suppressed.
