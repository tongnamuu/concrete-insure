# InsureLens architecture and boundaries

The final user specification supersedes the earlier claim-screening proposal: no eligibility decision, no claim recommendation, no diagnosis inference, no paraphrase or summary of policy. The backend uses Python FastAPI, the NeMo Microservices Python SDK and native in-process NAT. A separate Python PDF process provides cancellable text-layer geometry and annotation work. JavaScript is confined to the browser and browser tests. NemoClaw remains excluded; web is the only user-facing interface.

## Runtime modules

| Module | Implementation | Input/output contract |
|---|---|---|
| Intake and job API | insurelens/server.py,insurelens/store.py | Authenticated case-scoped uploads and jobs, replayable SSE |
| Conversation context | insurelens/conversation.py,insurelens/store.py | Server-owned successful turns and bounded prior source excerpts → follow-up context |
| Document worker | insurelens/pdf.py,python/pdf_worker.py | Original PDF → packed glyph index; source hits; annotation bytes |
| Prescription reading | Nvidia.ocr, PDF text/render tools | Image or prescription PDF → draft text requiring confirmation |
| Input extraction | insurelens/agents/input.py | User query/situation description/confirmed text → literal terms |
| Drug identity validation | insurelens/agents/drug.py,Drugs.lookup | User-selected official product → unchanged ingredient fields |
| Medicine evidence agent | insurelens/agents/drug_agent.py,insurelens/nat_drug.py | Conditional NAT tool-calling agent → MFDS candidates/user selection or verified product evidence |
| Product source parser | insurelens/agents/drug_references.py | Official fields and label paragraphs → literal facts, hashes and provenance |
| Policy retrieval tools | insurelens/agents/retrieval.py | Grounded term IDs or known source IDs → original spans |
| Policy ReAct agent | insurelens/agent.py | NIM native tool calls → tools → observations → next turn |
| Evidence assembly | insurelens/agents/verification.py | Trusted source objects → structured result; no prose generation |
| Web viewer | public/ | 1:1 split, uploads, explicit confirmation, source cards, PDF text-layer highlights |

See contracts.md for exact fields. A prescription can be replaced by a free-text description (up to4,000characters). Description-only requests are valid. The description remains a separate, unchanged user statement and is never labelled as a verified clinical record. Exact-substring grounding covers query and description separately. Deterministic tools perform source parsing and validation without model calls. Each has a single responsibility and testable boundary. ReAct is applied where an observation changes the next retrieval action, not to calculation of coordinates or source slices.

## Provider connections

Nemotron/NIM: AsyncNeMoMicroservices.chat.completions.create using native tool_calls and finish_reason. The official SDK1.5.0 handles inference requests; NAT1.9.0 directly invokes Python modules using a task-local invocation token. NAT and NIM are mandatory for every investigation. A missing key blocks investigation; transient inference timeouts/connection errors/5xx retry once with a 300-second per-attempt deadline; exhausted retries and control-protocol failures terminate the job. The NAT workflow has a 1200-second overall cap; cancellation interrupts both attempts and backoff. Hosted OCR uses its distinct documented input/image_url schema, not chat-completions messages. Configure the actual multilingual OCR endpoint after verifying account/model access. Hosted JSON extraction and native tool calls have been tested with a real key using public/synthetic data. See validation.md for full workflow results and limitations. No actual user medical document was used in cloud testing.

MFDS: official DrugPrdtPrmsnInfoService08 with getDrugPrdtPrmsnInq08, getDrugPrdtPrmsnDtlInq08 and conditional getDrugPrdtMcpnDtlInq08. A separately issued MFDS_API_KEY is required; see README for application and restart instructions. The public Swagger on data.go.kr as retrieved2026-09-27 names this v08 endpoint. Decoder preserves ITEM_INGR_NAME; no unsourced salt removal, brand alias or code-to-disease conversion. Product selection is explicit. Main-ingredient string equality or a quote match is never labelled medically/contractually suitable. Disease codes are searched literally; no KCD meanings are invented.

Translation: optional separately configured model supplies English glosses to the supervisor. Original term IDs, user input and quotes remain immutable. Glosses do not become search terms or source evidence. General Korean↔English free-text translation is not lossless, so no automatic round-trip translation of policy is implemented. A lighter model can be configured; it is not presumed faster without benchmark.

## Persistence and events

SQLite stores cases, official product lookup records, job state/results, event IDs, document-scoped conversations and original user turns. A single composer sends new messages. The latest four successful turns and bounded source excerpts provide context; the browser cannot submit arbitrary history. Every follow-up requires fresh NVIDIA consent. Refresh restores the active conversation, while new conversation/PDF replacement isolates subsequent messages. Prior excerpts are context only; displayed quotes must be freshly retrieved and verified. Original PDF/index files stay under a mode0700 local data directory. Browser reconnect replays SSE event IDs; completion fetches persisted results. Jobs run in a bounded in-process serial queue; PDF work runs in a killable subprocess. A process restart preserves completed results and marks interrupted jobs SERVER_RESTARTED for explicit retry. This is not a distributed, automatically resumed queue. User deletion removes case files and persisted results. Cookie ownership is for a local single-user demo, not production account authentication.

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

An explicit medicine name triggers a live MFDS lookup. Unselected products yield a requiresDrugSelection result, persisted with the conversation but excluded from evidence history. Selection must use case-owned candidate IDs; details are freshly fetched for the exact ID. MFDS failures never use static references. No branded catalog remains.

References retain source URL, retrieval timestamp, permit/change/cancellation fields, original field or XML paragraph, and document hash. XML entities/DTDs are rejected; HTML in CDATA is decoded to text without rewriting. Only structured ingredient names and explicit supported prodrug-to-active-metabolite sentences create specific terms. Treatment headings supply source-bound context terms; prophylaxis never establishes treatment. Unsupported relations remain unresolved. A process-local verified-reference marker detects later tampering; client JSON cannot create trusted references. Previous saved results remain viewable and labelled with their original provenance.

Ingredient hits anchor nearby pages before broader product-indication terms are searched. Explicit user terms retain full-document search scope. Document timestamps are current evidence, not historical regulatory certification. Original paragraph spelling is preserved, and search terms are literal substrings. No external text is used as a PDF annotation source.

The supervisor exposes an empty-argument finish_retrieval tool so native callers can terminate after source inspection. Model protocol failures, provider errors, source-integrity failures, ungrounded terms and cancellation terminate that run. No alternate investigation path exists.

## Policy benefit and source grouping

The application can identify an expressly described benefit and distinguish direct wording from an indirect ingredient link. `policy_scope.py` reads grouped source articles after retrieval and returns source IDs, fixed connection labels and pending verification items. It never generates policy quotations or predicts a payout. `pdf_worker.sections` recognizes numbered special-rider titles, handles nested parentheses in article headings and stops at the next rider. Source spans are merged contiguously within each page without rewriting. Unknown layouts and weak/negative connections remain unresolved. Referenced general provisions/appendices are flagged for further verification, not presumed satisfied. Blank context is filtered both server-side and in the viewer; duplicated glyph highlights are suppressed.

## Conditional native medicine agent

The parent workflow binds NAT's `drug_evidence_agent` through `Builder.get_function`. After literal input extraction, Python routing calls it only for explicit medicine names or user-selected products. A disease/accident alone does not cause specialist inference or an MFDS lookup. Names found only in policy evidence cannot activate it.

`nat-workflow.yml` registers the native `tool_calling_agent`, the `medicine` Function Group, and the `insurelens_evidence_nim` LLM adapter. The latter delegates through the existing NeMo Microservices SDK, preserving timeout/retry/privacy rules without switching clients. NAT/LangGraph owns the medicine tool-selection/observation loop; `return_direct` terminates through `finish_evidence` without another model call. The skill instructions are loaded from `skills/drug-ingredient-resolver/SKILL.md` at runtime. Per-request ContextVars isolate the allowed names/products, evidence ledger and authorized providers across tasks. Tool indexes cannot select arbitrary product IDs. Failed or fabricated final answers are rejected.

The upper policy-search loop remains application-owned ReAct. Input extraction, PDF parsing, source verification and annotation are not independent LLM agents. The former fixed medicine resolver orchestration has been removed; CLI lookup/detail remain deterministic adapters to the same provider/parser.

Official APIs: [NAT Tool Calling Agent](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/agents/tool-calling-agent/tool-calling-agent.html) and [Function Groups](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/functions-and-function-groups/function-groups.html). The installed 1.9.0 implementation was also inspected for typed inputs, `return_direct`, error propagation and cancellation.
