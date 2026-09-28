# concreteInsure contracts v3 (policy PDF and text input)

Runtime: Python FastAPI web/API, no diagnosis inference, no insurance eligibility/claim recommendation, no policy paraphrase or summary. Nemotron output is control data only. Human-readable policy quotes are assembled by application code from PDF source spans. NVIDIA credentials are read only by the runtime from the user-configured .env; never log or package them. Web only; NemoClaw excluded per prior explicit decision. OpenShell optional sandbox integration. No finetuning.

## Shared core

`concreteinsure/core.py`: AppError(code,status), ensure, QueryRequest, literal_terms(query,confirmed), grounded_terms(raw,query,confirmed,description), NOTICE. All public request schemas strict. Offset encoding is Unicode code points, not JS UTF-16. Python string offsets use code points directly; browser code must use Array.from(text) when slicing source offsets. The request must contain non-whitespace query or description. Description is an unchanged user statement, never a verified diagnosis. Term grounding validates each input field separately to prevent cross-field fabricated substrings.

Request: `{query:string(0..4000,default:""),description:string(0..4000,default:""),confirmedTerms:string[](<=20,1..120),drugIds:string[](<=5,numeric MFDS IDs),cloudConsent:boolean,conversationId?:UUID-string}`.
An investigation requires a text-layer policy PDF and a non-empty user query or description. confirmedTerms and selected products are optional. User-entered facts remain user assertions, not verified diagnoses. Non-medical accident narratives are valid: explicit vehicles, locations, actions, events and insurance/rider names may be selected as exact input substrings. Do not infer injuries, fault, liability or who was driving. Medical facts or prescription documents are never a prerequisite for this path.

confirmedTerms are supplementary text facts explicitly entered by an API client; the web uses the conversation input. Drug IDs must be selected from server-owned MFDS lookup records belonging to this case. Official ingredients may expand only to literal strings contained in the selected official fields; never infer a disease from a medicine.

SourceHit: `{id:'page:start:end',page:1-based,start,end,sourceStart,sourceEnd,quote,matchedText,segments:[{index,start,end,quad:number[8]|null}],documentHash,offsetEncoding:'unicode-code-points'}`. quad is PDF user-space polygon [LL,LR,UR,UL]. Every value derived from original PDF. quote contains exact contiguous text-layer source span. Synthetic newlines mark extracted line boundaries, no normalization. Quote boundaries are explicitly extraction-layer, not original PDF binary byte offsets.

## PDF worker

`concreteinsure/pdf.py` exports `await pdf_operation(payload, timeout=120, python=None) -> dict`. Timeout is in seconds. asyncio task cancellation kills and reaps the worker.
Input operations: index `{op:'index',pdf:absolute,index:absolute}` -> `{hash,pages,characters,textPages}`;
search `{op:'search',pdf,index,terms:string[],pages?:number[]}` -> `{hits:SourceHit[],truncated:boolean}`;
text `{op:'text',pdf,index}` -> `{text:string}` for prescription text PDFs;
render `{op:'render',pdf}` -> `{images:base64 PNG[]}` max8pages;
annotate `{op:'annotate',pdf,index,hits:SourceHit[],output:absolute}` -> `{count,skipped}`.
Optional search pages are at most20 unique, valid1-based integer pages. Omission searches all pages; an empty list searches none. Results preserve document order and original geometry.
Paths are server-owned, never supplied by public clients. Original hash/source/coordinates revalidated before annotation. Actual 230/412-page PDFs supported. No user PDFs in repo.

## Providers

`Nvidia` in concreteinsure/providers.py: `.enabled`, `await chat(messages,model=None) -> str`, `await complete(messages,tools) -> {finish_reason,message}`. Search and quote original strings only.
`Drugs.lookup(name)->{products:[{id,name,ingredients,manufacturer,permitDate,cancelDate,url,retrievedAt}],total,requiresSelection:true,source}`.

## Investigation subagents

`concreteinsure/agent.py`: `await run_investigation(document=..., request=..., products=..., nim=..., emit=callback, operation=pdf_operation, conversation?:server-owned-context, resume_facts?:server-owned-facts, on_selection?:callback) -> Result`. emit(event,data) is synchronous. asyncio cancellation propagates across all awaits; public result keys retain camelCase.
Core Result strict shape `{quotes:SourceHit[],mappings:Product[],references:DrugReference[],terms:string[],notice:string,mode:'nim-react',truncated:boolean,coverage:PolicyScope}`. Provider/control-protocol failures return a failed job with an error code and no result. No free LLM final answer. Server renders only this result. Fail closed on injected actions or unsupported tools. Model may choose IDs from grounded terms only, not arbitrary search strings. Refuse response length/content_filter/unknown tool/invalid IDs. Step limit, repeated-call limits, cancellation.
Module boundaries: input extraction (literal facts only), conditional native medicine agent (verified official data only), policy ReAct agent (source hits), source verification/output assembly. The medicine and policy agents observe tool results to select subsequent actions; parsing and verification are deterministic tools. Short event summaries, no hidden chain-of-thought streaming. NAT, a configured NVIDIA key and explicit cloud consent are required before every investigation.
The root package registers concreteinsure.nat with nat.components. NAT invokes the Python agent in-process. Paths, provider objects and SSE callbacks stay in ContextVar; only an opaque token crosses the NAT function schema. The application implements the bounded policy ReAct loop inside the registered workflow. The medicine specialist uses NAT’s built-in `tool_calling_agent`, registered as a separate function with the `medicine` Function Group and a request-scoped SDK client adapter. The agent takes only local name/product indexes, never a path, API key or arbitrary URL. Model tool arguments are strictly validated before NAT executes them. Its only successful exit is `medicine__finish_evidence` with `return_direct`; generated final prose is an error. Verified references stay in process-local state, not deserialized model output.

## Web API

All APIs same-origin; write requests have X-Local-Request:1. HttpOnly session cookie. GET /api/config -> `{nimEnabled,mfdsEnabled,mode,orchestrator,ready,backend,inferenceClient}`. POST /api/cases -> `{id}`. GET /api/cases/:id -> `{id,document:null|{id,name,pages,characters,textPages,hash},jobs:[{id,state}],products:Product[]}`.
POST /api/cases/:id/documents multipart `file`: async returns202 `{jobId}`. Job completed result `{document:{id,name,pages,characters,textPages,hash}}`. PDF20MiB/1000pages/2mchars.
GET /api/cases/:id/pdf -> original PDF bytes.
POST /api/cases/:id/drugs JSON `{name}` -> lookup response above; records saved server-side. User selects exact product id from results for investigation.
POST /api/cases/:id/investigations JSON Request ->202 `{jobId}`. GET /api/jobs/:id -> `{id,caseId,state,result,error}`. GET /api/jobs/:id/events SSE, event id monotonic; names `queued`, `stage_started`, `stage_completed`, `completed`, `failed`, `cancelled`. completed.data `{resultUrl:'/api/jobs/:id'}`. Last-Event-ID or `?after=N` replay. Events carry `{stage?,message?,code?,resultUrl?}`. EventSource reconnect + server event storage. Never SSE quotes or private reasoning. On completed fetch job result.
POST /api/jobs/:id/resume JSON `{drugIds:string[](1..5,unique),cloudConsent:boolean}` ->202 `{jobId}`. Only the original completed product-selection job can be resumed; any query/history/facts/extra fields are rejected. Require ownership, fresh consent, current document/hash/conversation and latest logical turn. IDs must be saved checkpoint candidates and cover each extracted medicine name. Saved input facts are revalidated against the original fields/context; no new input inference or candidate lookup occurs. Selected product detail is freshly fetched through NAT. Same IDs on an active/completed continuation return the same job; different IDs return409. Failed/cancelled continuation retries create a new job and replace the same turn pointer. The checkpoint survives a backend restart, stores no consent grant, and is deleted only with its case. The browser restores pending selection after refresh; continuation still requires a fresh consent grant. Missing legacy snapshots may be reconstructed only from the latest server-owned pending turn.
POST /api/jobs/:id/cancel -> `{ok:true}`. GET /api/jobs/:id/annotated.pdf -> saved standard highlight annotations with original quote as annotation content. DELETE /api/cases/:id ->204 cancels case jobs and removes uploaded copies, indexes, exports, conversations, events and selection checkpoints. Ownership is required. Filesystem deletion failure returns CASE_DELETE_FAILED and keeps records for retry; it does not claim successful cleanup.

Session boundary: assume one user of the current page. Follow-ups, product selection, retry and SSE reconnect keep the current `conversationId`; individual `jobId` values may change. The ownership cookie is not the conversation ID. Confirming **자료 삭제** (data clear) deletes the case and starts an empty interaction; the next upload/first question receives new case/conversation IDs with no inherited context. Dismissing the confirmation leaves the current session intact. Refresh retains the same case, conversation and submitted turns; it is not a reset boundary. Explicit new-conversation/document-replacement behavior remains document-scoped as specified below.

UI: 1:1 split, left chat/policy upload/drug candidate selection, right PDF.js with text layer and exact source quad overlays, click quote navigates page. Upload own PDF without fixtures. Render text with textContent only. No diagnoses/eligibility language. Distinguish source quotes, user statements, official product facts. Keep only the case ID in per-tab sessionStorage. On initialization, GET the case, document and current conversation under the ownership cookie and render saved requests/results. Reconnect queued/running jobs with their original job ID and SSE endpoint; never POST an investigation/resume or DELETE the case because of refresh. Completed/failed/cancelled turns and pending product selections remain visible. Checkpoint continuation and new questions still require explicit consent. Legacy browser IDs migrate after ownership is verified. Transient restore failures retain the pointer and block new inputs until explicit retry;404 clears only the pointer and opens an empty screen. Unsent drafts and unsubmitted selection edits are not restored. Unrelated storage and independently created tabs are preserved. Back/forward-cache restoration rechecks server state. A single 4,000-character composer sends query; legacy description remains supported by the API. The new-conversation action clears context, visible messages, highlights, input and confirmed/selected product state while preserving the PDF. Earlier completed answers are collapsed. Historical standalone jobs are never imported into a conversation. Delete control. Download annotations. UI uses SourceHit quote unchanged. Questions are handled through NIM input extraction and the NAT workflow. Do not automatically add a disease from drug information.

## Source context operation

`{op:'context',pdf,index,page,start,end,before:0..3,after:0..5,nextPage:boolean}` -> `{hits:SourceHit[],truncated:boolean}`. Coordinates must refer to a known tool-returned hit. Blocks are original neighbors, not inferred legal sections. Context may be on another page only through the explicit nextPage option. DLI loop reference: https://nvdli.github.io/NemoClawDLI/nemoclaw/01b-react.html#the-react-loop . Read finish_reason, execute validated tools, append tool observations, repeat. concreteInsure deliberately discards final free-form model text and emits its source contract instead.

## Sourced product-reference bridge

`await investigate_if_needed(names, products, nim, drugs, emit, consent)` returns `{status,references,specificTerms,contextTerms,products,requiresSelection,missingNames}` through the NAT-registered `drug_evidence_agent`. `status` is `skipped`, `needs_selection`, `ready`, or `unresolved`; it never represents insurance eligibility. With no medicine names and no selected products, return `skipped` before accessing MFDS or the specialist model. Otherwise require consent, providers and a bound NAT runner. Literal medicine names come from the input agent's bounded `drugNames` array and must be present in original user statements, not historical PDF quotes. MFDS API lookup supplies unselected candidate records; no product is automatically selected. Chosen case-owned IDs trigger a fresh detail request. A reference carries official source metadata and original field/paragraph quotes, with hashes and a process-local integrity marker. There is no product catalog. Missing keys, bad responses and mismatched IDs fail closed. A pending selection result has `requiresDrugSelection:true`, `products`, `missingNames`, `drugNames`, `terms`, and empty evidence arrays; it is persisted for restoration but excluded from model history.

Result adds `references:ProductReference[]` (empty when unavailable). A reference has id,brand,aliases,scope:'product_reference',source:{publisher,url,landingUrl?,documentDate,checkedAt,type},facts:[{kind,label,quote,page,terms,priority:'specific'|'context'}]. Reference objects must match trusted application records exactly. User/LLM supplied reference objects are not accepted.

PDF search optionally accepts `pages:number[]` (1-based, max20). Omitted means all pages, [] means no pages. Specific ingredient evidence is searched first; source-backed indication terms are searched around resulting pages when available. Highlight offsets and quotes remain original PDF text-layer spans.

## Provider failure

NIM chat uses JSON object mode with thinking disabled for supported Nemotron models. JSON must parse without repair; source grounding remains independently enforced. The web adapter requires cloud consent. Any provider/format failure terminates the job and emits a failed SSE event. Error codes never contain provider bodies or credentials. Cancellation and source-integrity failures terminate the job too.

`finish_retrieval({})` is a third native tool for explicit completion after source retrieval. It accepts no answer or other fields and must be the only action in its turn. Unsupported tools, repeated calls and malformed controls terminate the investigation; there is no automatic replacement result. Source-integrity and ungrounded-term errors still fail closed.

## Policy benefit identification

The latest user request permits identifying an explicitly documented policy benefit and a direct brand/explicit-term link or an indirect product-source ingredient link. This is different from deciding a person's actual coverage, claim likelihood or payout. Model final prose remains discarded.

`sections {op:'sections',pdf,index,anchors:SourceHit[]}` verifies up to12 prior source hits, recognizes numbered rider titles and article headings, and returns up to4 relevant riders' payment/definition/exclusion/claim source spans. It stops at the next rider and enforces page/character limits; unsupported layouts remain unresolved. Continuous blocks of one article on one page form one unchanged source span, with original glyph geometry. Pure whitespace/control-only context blocks are omitted; meaningful quotes are never trimmed.

`PolicyScope = {status:'identified'|'unresolved',scope:'policy_benefit_only',items:[{id,titleId,links:[{kind:'ingredient'|'direct_brand'|'explicit_term',referenceId,label,term,sourceIds}],clauses:[{kind,headingId,sourceIds}],checks:[{kind,sourceIds,status:'needs_confirmation'}],truncated}],truncated}`. All IDs must resolve to returned source objects. Product facts must retain verified MFDS field/paragraph provenance and pass the in-process integrity check. A payment heading alone or ingredient name in an exclusion is not sufficient. Negative wording is conservatively treated as ambiguous. Identification is a bounded rule-based evidence connection, not general legal interpretation. Personal conditions and unexpanded cross-references always require confirmation.

## Consent at submission

The web app opens a modal containing only the NVIDIA transfer consent statement and consent/cancel controls on each search submission and product-selection continuation, including description-only and keyboard submissions. The checkbox starts unchecked every time and is not stored. Only an explicit checkbox selection and confirmation submit cloudConsent:true. Cancel, Escape or unchecked submission send no investigation request and create no new result. Existing strict server guards reject missing/false consent before creating a job or invoking NIM.


## Conversation context

GET /api/cases/:id/conversation -> `{id:null|UUID,turns:[{jobId,query,description,confirmedTerms,state,error,result,resume?:{jobId,products,selectedIds}}]}` for the newest conversation of the current document only. POST the same route starts a new empty conversation and returns201 with that shape; it makes no model call. A search with conversationId requires that ID to match the current case/document conversation and requires fresh cloudConsent:true. All client-supplied history/source fields are rejected. Requests without conversationId remain standalone for API compatibility.

Waiting-selection turns and failed/cancelled continuations expose `resume` with the original pending job ID and its candidates. Successful continuations replace the pending result in the same turn, without duplicating the user message. The browser offers **선택한 제품으로 계속** only for the latest turn and does not overwrite unsent composer text.

A case may have one active search at a time. Active jobs block new conversations; stale tabs, other documents and other cases cannot supply a previous conversation ID. Limits: 50 submitted turns per conversation and 100 conversations per case, plus existing job/case limits. Deletion removes turns/conversations alongside jobs and files. SQLite adds tables without importing old standalone jobs.

`conversation.model_context` selects the newest four successful turns, at most 24,000 serialized characters for the turn objects. Each carries exact query/description/confirmed terms, previously verified search terms, and up to two prior source excerpts capped at1,200 characters each with an explicit truncation flag. Failed, cancelled, queued and running jobs never provide context. Limits are context selection, not a promise that the model recalls the entire chat.

The same bounded history is supplied to input extraction and ReAct as untrusted data. Search candidates must be literal substrings of a current input field or a history field separately; fields are never concatenated for grounding. A quote may supply a search phrase but cannot establish a diagnosis, role or actual eligibility. Current corrections take precedence; ambiguous references request more specific input. Historical excerpts never bypass fresh PDF retrieval or output source verification. Model final prose is discarded, as in standalone searches. Product references may be resolved from selected history-grounded terms.

Every web message has a fresh consent checkbox mentioning NVIDIA and current/previous conversation content. Refresh deletes the current case and starts empty, including unsent inputs and source highlights. New conversation and PDF replacement only disconnect prior context while preserving the active case. The explicit delete control also removes the full case. Console diagnostics contain no message or quotation text.

## Medicine agent tool contracts

| NAT tool | Input | Observation / enforcement |
|---|---|---|
| `medicine__lookup_products` | `{name_id: int}` | Only names grounded by input extraction; official candidates; never automatic selection |
| `medicine__inspect_ingredients` | `{product_id: int}` | Only user-selected, case-owned products; fresh detail; structured source facts and `labelAvailable` |
| `medicine__inspect_label` | `{product_id: int}` | Requires detail observation; original source facts with field/paragraph/hash/URL |
| `medicine__finish_evidence` | `{}` | All missing names looked up OR every selected product and available label inspected; assemble source-bound result |

Each tool accepts exactly its schema (strict integer indexes, no extra fields). One tool per model turn, no repeated tool/ID calls, maximum 12 turns. The native graph handles tool-result observations; parsing and ingredient relation validation remain code. SDK inference retains 300 seconds per attempt and one retry for transient failures, with NAT's 1200-second overall deadline and cancellable SSE progress. Provider and validation failures never create local substitute evidence. Runtime does not import test fixtures.
