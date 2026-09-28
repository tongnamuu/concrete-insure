# concreteInsure architecture and boundaries

The final user specification supersedes the earlier claim-screening proposal: no eligibility decision, no claim recommendation, no diagnosis inference, no paraphrase or summary of policy. The backend uses Python FastAPI, the NeMo Microservices Python SDK and native in-process NAT. A separate Python PDF process provides cancellable text-layer geometry and annotation work. JavaScript is confined to the browser and browser tests. NemoClaw remains excluded; web is the only user-facing interface.

The current technology list and user-to-NVIDIA diagrams are maintained in [README](../README.md#사용자-입력부터-nvidia-연동까지); exact versions are pinned in `pyproject.toml`. The default model is `nvidia/nemotron-3.5-lightning-30b-a3b`.

## Runtime modules

| Module | Implementation | Input/output contract |
|---|---|---|
| Intake and job API | concreteinsure/server.py,concreteinsure/store.py | Authenticated case-scoped uploads and jobs, replayable SSE |
| Product-selection continuation | concreteinsure/selection.py,concreteinsure/store.py | Server-owned facts/candidates/context → fresh consent and ingredient-stage continuation |
| Conversation context | concreteinsure/conversation.py,concreteinsure/store.py | Server-owned successful turns and bounded prior source excerpts → follow-up context |
| Document worker | concreteinsure/pdf.py,python/pdf_worker.py | Original PDF → packed glyph index; source hits; annotation bytes |
| Input extraction | concreteinsure/agents/input.py | User query/situation description/confirmed text → literal terms |
| Drug identity validation | concreteinsure/agents/drug.py,Drugs.lookup | User-selected official product → unchanged ingredient fields |
| Medicine evidence agent | concreteinsure/agents/drug_agent.py,concreteinsure/nat_drug.py | Conditional NAT tool-calling agent → candidates via lookup_products or combined ingredient/label evidence via inspect_product; application-controlled completion |
| Product source parser | concreteinsure/agents/drug_references.py | Official fields and label paragraphs → literal facts, hashes and provenance |
| Policy retrieval tools | concreteinsure/agents/retrieval.py | Grounded term IDs or known source IDs → original spans |
| Policy ReAct agent | concreteinsure/agent.py | NIM native tool calls → tools → observations → next turn |
| Skill CLI adapters | concreteinsure/skills_cli.py,skills/ | Two JSON tool adapters for drug lookup/detail and PDF operations; shared Python modules and SKILL.md contracts |
| Evidence assembly | concreteinsure/agents/verification.py | Trusted source objects → structured result; no prose generation |
| Web viewer | public/ | 1:1 split, uploads, explicit confirmation, source cards, PDF text-layer highlights |

See contracts.md for exact fields. Input is a text-layer policy PDF and a free-text query or description (up to4,000characters). Description-only requests are valid. The description remains a separate, unchanged user statement and is never labelled as a verified clinical record. Exact-substring grounding covers query and description separately. Deterministic tools perform source parsing and validation without model calls. Each has a single responsibility and testable boundary. ReAct is applied where an observation changes the next retrieval action, not to calculation of coordinates or source slices.

## Provider connections

Nemotron/NIM: AsyncNeMoMicroservices.chat.completions.create using native tool_calls and finish_reason. The official SDK1.5.0 handles inference requests; NAT1.9.0 directly invokes Python modules using a task-local invocation token. NAT and NIM are mandatory for every investigation. A missing key blocks investigation; transient inference timeouts/connection errors/5xx retry once with a 300-second per-attempt deadline; exhausted retries and control-protocol failures terminate the job. The NAT workflow has a 1200-second overall cap; cancellation interrupts both attempts and backoff. Hosted JSON extraction and native tool calls have been tested with a real key using public/synthetic data. See validation.md for full workflow results and limitations. No actual user medical document was used in cloud testing.

MFDS: official DrugPrdtPrmsnInfoService08 with getDrugPrdtPrmsnInq08, getDrugPrdtPrmsnDtlInq08 and conditional getDrugPrdtMcpnDtlInq08. A separately issued MFDS_API_KEY is required; see README for application and restart instructions. The public Swagger on data.go.kr as retrieved2026-09-27 names this v08 endpoint. Decoder preserves ITEM_INGR_NAME; no unsourced salt removal, brand alias or code-to-disease conversion. Product selection is explicit. Main-ingredient string equality or a quote match is never labelled medically/contractually suitable. Disease codes are searched literally; no KCD meanings are invented.

## Persistence and events

The current interaction assumes one user. A case ID is held in per-tab sessionStorage; the HttpOnly ownership cookie authorizes access and is independent of the conversation boundary. Reload, follow-up questions, product selection, retries and SSE reconnects keep the current `conversationId`. A new `jobId` denotes another execution, not another conversation. Confirmed **자료 삭제** cancels case jobs and removes the case and its context; the next upload starts fresh. Cancelling that confirmation preserves the existing interaction. Explicit new-conversation actions and document replacement isolate document-specific evidence.

On initialization the browser retrieves the case, PDF, current conversation and saved results. Pending product selection is restored but requires new consent before continuing. Queued/running jobs reconnect to their existing SSE endpoint; terminal events and the job-status check handle completion during restoration. Reload performs no investigation/resume POST or case DELETE and does not repeat inference. A failed read preserves the pointer and blocks new submissions until the user retries. A missing/inaccessible case clears its local pointer and opens an empty screen. Unsent drafts and unchecked/checked selection edits are not persisted. Back/forward-cache restoration rechecks server state through the same initialization.

The rename retains ownership from a legacy `insurelens_session` cookie, issuing `concreteinsure_session`. Current per-tab `concrete-insure-case` takes priority over the legacy `insure-lens-case` and old localStorage pointers. Successfully restored legacy pointers migrate to sessionStorage. No server data is deleted during migration. Independently opened tabs have separate case pointers; unrelated browser storage is untouched. Tab close alone is not a deletion guarantee, and account-based recovery after closing the tab is not provided.

SQLite stores cases, official product lookup records, job state/results, event IDs, document-scoped conversations and original user turns. The latest four successful turns and bounded source excerpts provide context; the browser cannot submit arbitrary history. Every new search and product-selection continuation requires fresh NVIDIA consent; reading previously authorized results or reconnecting to an existing job does not create a new inference request. Displayed quotes come from verified source spans, not model prose. Original PDF/index files stay under a mode0700 local data directory.

Jobs run in a bounded in-process serial queue; PDF work runs in a killable subprocess. A browser reload does not stop server jobs. A backend restart preserves completed results and records interrupted jobs as cancelled or SERVER_RESTARTED; it does not automatically resume their execution. This is not a distributed job queue. Restored failures/cancellations keep the original question available for explicit resubmission. Cookie ownership is for a local single-user demo, not production account authentication.

## PDF contract

Extracted text is rawdict reading order with explicit synthetic line-break separators. Verbatim means a byte-for-byte-equal Unicode slice of that stored extraction text, not original compressed PDF content streams. Offsets use Unicode code points. Float64 glyph quads preserve rotated/cropped geometry; no proportional splitting of text runs. Policies without a text layer are rejected; source spans must come from the original extraction layer.

Export adds native Highlight annotations, QuadPoints, source quote Contents and normal appearance streams through PyMuPDF. Original extracted text is checked in tests. This implements standard PDF annotations, not a claim of complete ISO32000 conformance certification. Digital signatures may be invalidated by PDF modification; the uploaded original stays separate. Missing glyph geometry is reported, not approximated.

## Official sources checked

- ReAct protocol: https://nvdli.github.io/NemoClawDLI/nemoclaw/01b-react.html#the-react-loop
- NAT public plugin API: https://docs.nvidia.com/nemo/agent-toolkit/latest/extend/plugin-api.html
- Drug product/ingredient API: https://www.data.go.kr/data/15095677/openapi.do
- Agent Skills: https://github.com/NVIDIA/skills and https://www.skills.sh/docs
- SkillSpector: https://github.com/NVIDIA/SkillSpector
- OpenShell: https://docs.nvidia.com/openshell/latest/how-it-works/policies/schema

No documented generic build.nvidia.com "Skill API" was verified. Therefore this application uses documented NIM model endpoints and skills.sh-compatible local SKILL.md, and does not fabricate a skill execution URL. NeMo-Skills model-training project is distinct from Agent Skills; training is not included.

## Product-reference bridge

An explicit medicine name triggers a live MFDS lookup. Unselected products yield a requiresDrugSelection result, persisted with the conversation but excluded from evidence history. The server also saves original request options, validated input facts, frozen conversation context, document hash and candidate IDs in a selection checkpoint. Selection resumes from the medicine agent with those facts, skipping input inference and candidate lookup. IDs must belong to that checkpoint, not merely the same case; details are freshly fetched for the exact ID. Resuming creates a new execution job and atomically replaces the job pointer of the same conversation turn. Repeated identical submissions return the active/completed job; failed/cancelled attempts can be retried from the saved input. Every resume requires fresh consent. New questions, conversations and document replacements invalidate earlier continuations. Saved pending turns from earlier versions can be reconstructed from server-owned grounded fields. This is application-stage persistence, not a suspended NAT/LangGraph execution or automatic background resume. MFDS failures never use static references. No branded catalog remains.

References retain source URL, retrieval timestamp, permit/change/cancellation fields, original field or XML paragraph, and document hash. XML entities/DTDs are rejected; HTML in CDATA is decoded to text without rewriting. Structured ingredient names, explicit supported prodrug-to-active-metabolite sentences, and dosage-basis wording in UD_DOC_DATA create specific terms. A dosage-basis term must also appear literally within this product’s structured ingredient; salts are never stripped by assumption. SECTION/ARTICLE title attributes and PARAGRAPH text retain XML locators and document hashes. Treatment headings and literal infection wording in indications supply source-bound context terms; prophylaxis never establishes treatment. Unsupported relations remain unresolved. A process-local verified-reference marker detects later tampering; client JSON cannot create trusted references. Previous saved results remain viewable and labelled with their original provenance.

Ingredient hits anchor nearby pages before broader product-indication terms are searched. Explicit user terms retain full-document search scope. Document timestamps are current evidence, not historical regulatory certification. Original paragraph spelling is preserved, and search terms are literal substrings. No external text is used as a PDF annotation source.

The supervisor exposes an empty-argument finish_retrieval tool so native callers can terminate after source inspection. Model protocol failures, provider errors, source-integrity failures, ungrounded terms and cancellation terminate that run. No alternate investigation path exists.

## Policy benefit and source grouping

The application can identify an expressly described benefit and distinguish direct wording from an indirect ingredient link. `policy_scope.py` reads grouped source articles after retrieval and returns source IDs, fixed connection labels and pending verification items. It never generates policy quotations or predicts a payout. `pdf_worker.sections` recognizes numbered special-rider titles, handles nested parentheses in article headings and stops at the next rider. Source spans are merged contiguously within each page without rewriting. Unknown layouts and weak/negative connections remain unresolved. Referenced general provisions/appendices are flagged for further verification, not presumed satisfied. Blank context is filtered both server-side and in the viewer; duplicated glyph highlights are suppressed.

## Conditional native medicine agent

The parent workflow binds NAT's `drug_evidence_agent` through `Builder.get_function`. After literal input extraction, Python routing calls it only for explicit medicine names or user-selected products. A disease/accident alone does not cause specialist inference or an MFDS lookup. Names found only in policy evidence cannot activate it.

`nat-workflow.yml` registers the native `tool_calling_agent`, the `medicine` Function Group, and the `concreteinsure_evidence_nim` LLM adapter. The latter delegates through the existing NeMo Microservices SDK, preserving timeout/retry/privacy rules without switching clients. NAT/LangGraph owns the medicine tool-selection/observation loop. Its `inspect_product` tool fetches one selected product’s detail and validates ingredients and every available label together. The evidence ledger is updated atomically after parsing and integrity validation, so a failed label cannot leave a completed ingredient-only observation. There is no intermediate model call between ingredient and label inspection. Before another inference, the adapter checks the request-local evidence ledger. Once every missing name is looked up OR every selected product and required label is inspected, it emits an application-authored control call to `finish_evidence` without contacting NIM. That internal tool revalidates observations and source integrity, then NAT `return_direct` ends the graph. The finish tool is excluded from the model tool schema; premature model requests to call it are rejected. Internal control messages are marked `completion_source=application`, do not increment the model-call count and contain no fabricated provider usage. The skill instructions are loaded from `skills/drug-ingredient-resolver/SKILL.md` at runtime. Per-request ContextVars isolate the allowed names/products, evidence ledger and authorized providers across tasks. Tool indexes cannot select arbitrary product IDs. Failed or fabricated final answers are rejected.

The upper policy-search loop remains application-owned ReAct, including model-selected `finish_retrieval`; the medicine agent’s application-controlled completion does not terminate policy retrieval. Input extraction, PDF parsing, source verification and annotation are not independent LLM agents. The former fixed medicine resolver orchestration has been removed; CLI lookup/detail remain deterministic adapters to the same provider/parser.

Official APIs: [NAT Tool Calling Agent](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/agents/tool-calling-agent/tool-calling-agent.html) and [Function Groups](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/functions-and-function-groups/function-groups.html). The installed 1.9.0 implementation was also inspected for typed inputs, `return_direct`, error propagation and cancellation.

## Development verification boundary

pytest covers Python modules and API contracts; Playwright covers the browser flows with explicit synthetic providers. Live-provider measurements are recorded separately in validation.md. SkillSpector is a separately installed, optional development scanner invoked with `scripts/scan-skills.sh` and `--no-llm`; it is neither a web runtime component nor a required CI check. Agent Skills are local SKILL.md instructions, not a hosted skill execution API. NIM responses are currently non-streaming (`stream=False`); application SSE carries job progress and saved results.
