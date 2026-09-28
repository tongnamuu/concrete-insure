import * as pdfjs from '/vendor/pdfjs/build/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/build/pdf.worker.mjs';
const $ = id => document.getElementById(id);
const state = {ready:false,conversationId:null,busy:false,caseId:null,config:{},pdf:null,page:1,zoom:1,hits:[],selected:new Set(),job:null,resultJob:null,stream:null,renderTask:null,renderVersion:0,renderChain:Promise.resolve(),document:null};
const errors = {SERVER_RESTARTED:'서버가 다시 시작되어 진행 중이던 요청을 완료하지 못했습니다. 내용을 확인한 뒤 다시 보내 주세요.',SELECTION_EXPIRED:'이전 선택 대기를 이어갈 수 없습니다. 현재 약관과 대화에서 새 질문을 보내 주세요.',SELECTION_STATE_INVALID:'저장된 질문 분석 결과를 복원하지 못했습니다. 새 질문으로 진행해 주세요.',SELECTION_ALREADY_RESUMED:'이미 선택한 제품으로 진행 중이거나 완료된 요청입니다.',DRUG_SELECTION_REQUIRED:'이 질문에서 찾은 제품 후보를 선택해 주세요.',DRUG_SELECTION_INCOMPLETE:'질문에 나온 약품마다 처방받은 제품을 선택해 주세요. 후보가 없으면 정확한 약품명으로 새 질문을 보내 주세요.',AGENT_TIMEOUT:'전체 검색 제한 시간(20분)에 도달했습니다. 다시 시도해 주세요.',MFDS_KEY_REQUIRED:'의약품 조회에는 식약처 API 키가 필요합니다. README의 발급·설정 방법을 확인해 주세요.',MFDS_AUTH_FAILED:'식약처 API 인증 또는 활용 승인을 확인해 주세요.',MFDS_TIMEOUT:'식약처 자료 조회 시간이 초과되었습니다. 다시 시도해 주세요.',MFDS_REQUEST_FAILED:'식약처 자료를 가져오지 못했습니다. 다시 시도해 주세요.',MFDS_RATE_LIMIT:'식약처 API 호출 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.',MFDS_PRODUCT_MISMATCH:'정확한 제품 상세정보를 확인하지 못했습니다. 제품을 다시 선택해 주세요.',CONVERSATION_CHANGED:'다른 탭에서 대화나 약관이 바뀌었습니다. 현재 대화를 확인하고 다시 보내 주세요.',CONVERSATION_TURN_LIMIT:'이 대화의 메시지 한도에 도달했습니다. 새 대화를 시작해 주세요.',CONVERSATION_LIMIT:'대화 한도에 도달했습니다. 자료를 삭제한 뒤 다시 시작해 주세요.',NIM_INCOMPLETE_RESPONSE:'응답이 완성되지 않아 검색을 중단했습니다. 다시 시도해 주세요.',NIM_TIMEOUT:'검색 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.',NIM_SERVICE_UNAVAILABLE:'검색 서비스가 일시적으로 응답하지 않습니다.',NIM_MODEL_UNAVAILABLE:'설정된 검색 모델을 사용할 수 없습니다. 모델 설정과 접근 권한을 확인해 주세요.',NIM_AUTH_FAILED:'검색 서비스의 인증 설정과 접근 권한을 확인해 주세요.',NIM_RATE_LIMIT:'검색 서비스의 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.',NO_EXPLICIT_TERMS:'검색할 구체적인 정보를 찾지 못했습니다. 사고 상황·장소·차량, 진단명·약품명 또는 찾고 싶은 약관 표현을 적어 주세요.',PDF_PAGE_LIMIT:'약관은 최대 1,000페이지까지 올릴 수 있습니다.',PDF_TEXT_LIMIT:'약관은 최대 200만 자까지 처리할 수 있습니다.',PDF_SIZE_LIMIT:'약관은 최대 20 MB까지 올릴 수 있습니다.',ENCRYPTED_PDF:'암호로 잠긴 PDF입니다. 암호를 해제한 사본을 올려 주세요.',PDF_RUNTIME_MISSING:'PDF 처리 프로그램이 아직 설치되지 않았습니다. 실행 가이드의 PDF 설치 단계를 확인해 주세요.',PROVIDER_UNAVAILABLE:'외부 서비스에 연결하지 못했습니다. 연결 설정을 확인하고 다시 시도해 주세요.',PROVIDER_REQUEST_FAILED:'외부 서비스 요청이 실패했습니다. API 설정과 이용 한도를 확인해 주세요.',DOCUMENT_REQUIRED:'먼저 보험약관 PDF를 올려 주세요.',NIM_CONSENT_REQUIRED:'NVIDIA 자료 전송에 동의해야 검색을 진행할 수 있습니다.',TEXT_LAYER_REQUIRED:'이 약관에는 검색 가능한 문자 정보가 없습니다. 텍스트가 있는 약관 PDF를 올려 주세요.',CASE_BUSY:'이 자료에서 진행 중인 작업이 있습니다. 완료 후 다시 시도해 주세요.',NVIDIA_KEY_REQUIRED:'검색 서비스의 인증 설정이 필요합니다.',NAT_RUNTIME_MISSING:'검색 기능을 실행하는 데 필요한 프로그램 설치를 확인해 주세요.',NIM_NOT_CONFIGURED:'검색 모델 연결 설정이 필요합니다.',MFDS_NOT_CONFIGURED:'공식 의약품 조회 서비스가 아직 설정되지 않았습니다.',PDF_TIMEOUT:'문서 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.',CASE_NOT_FOUND:'이 자료는 만료되었거나 삭제되었습니다. 다시 업로드해 주세요.',NO_DOCUMENT:'먼저 보험약관 PDF를 올려 주세요.',PDF_TOO_MANY_PAGES:'약관은 최대 1,000페이지까지 올릴 수 있습니다.',PDF_TOO_MUCH_TEXT:'약관의 텍스트가 처리 한도를 넘었습니다.',FILE_TOO_LARGE:'파일이 너무 큽니다. 약관은 20 MB까지 올릴 수 있습니다.',ABORTED:'작업이 취소되었습니다.'};
function fail(e){$('error').textContent=errors[e.code]||e.message||'요청을 완료하지 못했습니다. 다시 시도해 주세요.';$('error').classList.remove('hidden');}
function clearError(){$('error').classList.add('hidden');}
function requestCloudConsent(){
 const dialog=$('consentDialog'),form=$('consentForm'),checkbox=$('cloudConsent'),confirm=$('confirmConsent'),cancel=$('cancelConsent');
 if(dialog.open)return Promise.resolve(false);
 checkbox.checked=false;confirm.disabled=true;
 return new Promise(resolve=>{
  let settled=false;
  const finish=accepted=>{if(settled)return;settled=true;form.removeEventListener('submit',submit);checkbox.removeEventListener('change',change);cancel.removeEventListener('click',decline);dialog.removeEventListener('cancel',escape);dialog.removeEventListener('close',decline);dialog.close();checkbox.checked=false;confirm.disabled=true;resolve(accepted);};
  const submit=e=>{e.preventDefault();if(checkbox.checked)finish(true);};
  const change=()=>{confirm.disabled=!checkbox.checked;};
  const decline=()=>finish(false);
  const escape=e=>{e.preventDefault();finish(false);};
  form.addEventListener('submit',submit);checkbox.addEventListener('change',change);cancel.addEventListener('click',decline);dialog.addEventListener('cancel',escape);dialog.addEventListener('close',decline);
  dialog.showModal();
 });
}

async function api(url,{method='GET',body,headers={},signal}={}){const r=await fetch(url,{method,signal,body:body instanceof FormData?body:body===undefined?undefined:JSON.stringify(body),headers:{...(method!=='GET'?{'X-Local-Request':'1'}:{}),...(body!==undefined&&!(body instanceof FormData)?{'Content-Type':'application/json'}:{}),...headers}});if(!r.ok){let d={};try{d=await r.json();}catch{}const code=typeof d.error==='string'?d.error:d.error?.code||d.code;throw Object.assign(new Error(errors[code]||'요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'),{code,status:r.status});}return r.status===204?null:r.json();}
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function officialLink(url){try{const u=new URL(url);if(u.protocol==='https:'&&(u.hostname==='nedrug.mfds.go.kr'||u.hostname.endsWith('.mfds.go.kr')||u.hostname==='mfds.go.kr')){const a=el('a','','공식 자료 확인 ↗');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}}catch{}return el('span','','공식 출처 주소 확인 필요');}
async function ensureCase(){if(!state.caseId){const c=await api('/api/cases',{method:'POST'});state.caseId=c.id;sessionStorage.setItem('concrete-insure-case',c.id);}return state.caseId;}
const welcome = $('messages').firstElementChild.cloneNode(true);
function busy(jobId,message){state.busy=true;state.job=jobId;document.querySelectorAll('.assistant-message button').forEach(button=>button.disabled=true);$('progress').classList.remove('hidden');$('progressText').textContent=message;for(const id of ['send','query','policyFile','clearResults'])$(id).disabled=true;}
function idle(){state.busy=false;state.job=null;document.querySelectorAll('.assistant-message button').forEach(button=>button.disabled=button.dataset.locked==='true');$('progress').classList.add('hidden');for(const id of ['send','query','policyFile'])$(id).disabled=false;$('clearResults').disabled=!state.document;state.stream?.close();state.stream=null;}
function renderConversation(conversation){
 state.conversationId=conversation.id;state.hits=[];state.resultJob=null;$('download').disabled=true;$('messages').replaceChildren();
 const turns=conversation.turns||[];
 if(!turns.length)$('messages').append(welcome.cloneNode(true));
 for(const [index,turn] of turns.entries()){
  const message=el('div','user-message',[turn.description,turn.query].filter(Boolean).join('\n'));message.dataset.jobId=turn.jobId;$('messages').append(message);
  if((turn.state==='completed'&&turn.result?.requiresDrugSelection)||(['failed','cancelled'].includes(turn.state)&&turn.resume)){
   const reply=el('div','assistant-message drug-selection');
   const pending=turn.resume||{jobId:turn.jobId,products:turn.result.products,selectedIds:[]};
   reply.append(el('p','',pending.products.length?'식약처에서 제품 후보를 찾았습니다. 처방받은 함량·제형을 선택하면 성분 조사부터 이어서 진행합니다.':'식약처에서 일치하는 제품을 확인하지 못했습니다. 정확한 약품명으로 새 질문을 보내 주세요.'));
   if(['failed','cancelled'].includes(turn.state))reply.append(el('p','',turn.state==='cancelled'?'이어서 진행하던 조사를 취소했습니다. 선택을 확인하고 다시 이어갈 수 있습니다.':(errors[turn.error]||'이어서 진행하던 조사를 완료하지 못했습니다. 다시 이어갈 수 있습니다.')));
   if(turn.result?.truncated)reply.append(el('p','','제품 후보 중 일부만 표시했습니다. 원하는 제품이 없으면 정확한 제품명·함량으로 새 질문을 보내 주세요.'));
   if(turn.result?.missingNames?.length)reply.append(el('p','',`확인하지 못한 제품명: ${turn.result.missingNames.join(', ')}`));
   const selected=new Set(pending.selectedIds),choices=el('div','selection-products');
   const choose=el('button','secondary','선택한 제품으로 계속');choose.type='button';
   const update=()=>{choose.dataset.locked=String(!selected.size||index!==turns.length-1);choose.disabled=state.busy||choose.dataset.locked==='true';};
   renderProducts(pending.products,choices,selected,update);update();
   if(index!==turns.length-1)reply.append(el('p','result-note','이후 질문이 있어 이전 선택 대기는 이어갈 수 없습니다.'));
   choose.addEventListener('click',()=>resumeSelection(pending.jobId,[...selected]));reply.append(choices,choose);$('messages').append(reply);
  }else if(turn.state==='completed'&&Array.isArray(turn.result?.quotes)){
   renderResult(turn.result,turn.jobId);
   const result=$('messages').lastElementChild;
   if(index<turns.length-1){const earlier=el('details','earlier-turn');earlier.append(el('summary','','이 답변의 근거 보기'));result.replaceWith(earlier);earlier.append(result);}
  }else if(['failed','cancelled'].includes(turn.state)){
   const reply=el('div','assistant-message');reply.append(el('p','',turn.state==='cancelled'?'요청을 취소했습니다. 이 메시지는 다음 검색의 맥락에 포함하지 않습니다.':(errors[turn.error]||'요청을 완료하지 못했습니다. 다시 시도해 주세요.')));
   const retry=el('button','secondary','다시 입력하기');retry.type='button';retry.disabled=state.busy;retry.addEventListener('click',()=>{if(!state.busy){$('query').value=[turn.description,turn.query].filter(Boolean).join('\n').slice(0,4000);$('query').focus();}});reply.append(retry);$('messages').append(reply);
  }
 }
 $('clearResults').disabled=state.busy||!state.document;renderPage();
}
async function refreshConversation(){const conversation=await api(`/api/cases/${state.caseId}/conversation`);renderConversation(conversation);return conversation;}
async function acceptResult(result,jobId){if(result?.document){await refreshCase();}else if(Array.isArray(result?.quotes)){renderResult(result,jobId);}else{await refreshCase();}}
function followJob(jobId,message='작업을 접수했습니다.'){busy(jobId,message);state.stream?.close();const stream=new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);state.stream=stream;let finishing=false;async function finish(){if(finishing)return;finishing=true;stream.close();try{const job=await api(`/api/jobs/${encodeURIComponent(jobId)}`);if(job.kind==='investigation')await refreshConversation();if(job.state==='failed'){const code=typeof job.error==='string'?job.error:job.error?.code;throw Object.assign(new Error('자료 처리 중 오류가 발생했습니다.'),{code});}if(job.state!=='cancelled'&&job.kind!=='investigation')await acceptResult(job.result,jobId);}catch(e){fail(e);}finally{idle();}}
for(const event of ['queued','stage_started','stage_progress','stage_completed','completed','failed','cancelled'])stream.addEventListener(event,async e=>{let data={};try{data=JSON.parse(e.data);}catch{}if(['completed','failed','cancelled'].includes(event)){await finish();}else{$('progressText').textContent=data.message||'자료를 확인하고 있습니다.';}});stream.onerror=()=>{if(!finishing)$('progressText').textContent='진행 상태에 다시 연결하고 있습니다. 작업은 계속됩니다.';};
// The job may finish before its event stream is connected.
api(`/api/jobs/${encodeURIComponent(jobId)}`).then(j=>{if(['completed','failed','cancelled'].includes(j.state))finish();}).catch(e=>{stream.close();idle();fail(e);});}
async function refreshCase(c=null){c??=await api(`/api/cases/${encodeURIComponent(state.caseId)}`);state.document=c.document;const name=c.document?.name||'약관 원문';$('documentName').textContent=name;$('documentName').title=name;$('policyLabel').textContent=c.document?`${name} · ${c.document.pages}쪽`:'PDF 업로드 · 최대 20 MB';if(c.document&&state.pdfDocumentId!==c.document.id){await openPdf();state.pdfDocumentId=c.document.id;}if(c.products?.length)renderProducts(c.products);await refreshConversation();return c;}
async function openPdf(){state.hits=[];state.resultJob=null;$('download').disabled=true;if(state.pdfDocumentId){$('messages').replaceChildren();}$('clearResults').disabled=true;state.renderTask?.cancel();if(state.pdf)await state.pdf.loadingTask.destroy();state.pdf=null;state.pdf=await pdfjs.getDocument({url:`/api/cases/${encodeURIComponent(state.caseId)}/pdf`,cMapUrl:'/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/vendor/pdfjs/standard_fonts/',wasmUrl:'/vendor/pdfjs/wasm/'}).promise;state.page=1;state.hits=[];state.resultJob=null;$('download').disabled=true;$('pdfEmpty').classList.add('hidden');$('pdfPage').classList.remove('hidden');$('pageNumber').max=state.pdf.numPages;$('pageCount').textContent=`/ ${state.pdf.numPages}`;await renderPage();}
function renderPage(){const version=++state.renderVersion;state.renderTask?.cancel();state.renderChain=state.renderChain.catch(()=>{}).then(async()=>{if(!state.pdf||version!==state.renderVersion)return;const page=await state.pdf.getPage(state.page);if(version!==state.renderVersion)return;const natural=page.getViewport({scale:1});const width=Math.max(240,$('pdfScroll').clientWidth-48);const viewport=page.getViewport({scale:width/natural.width*state.zoom});state.viewport=viewport;const ratio=window.devicePixelRatio||1;const canvas=$('pdfCanvas');canvas.width=Math.ceil(viewport.width*ratio);canvas.height=Math.ceil(viewport.height*ratio);canvas.style.width=`${viewport.width}px`;canvas.style.height=`${viewport.height}px`;$('pdfPage').style.width=`${viewport.width}px`;$('pdfPage').style.height=`${viewport.height}px`;$('pdfPage').style.setProperty('--scale-factor',viewport.scale);$('pdfPage').style.setProperty('--user-unit',page.userUnit||1);$('textLayer').replaceChildren();$('highlights').replaceChildren();$('pageNumber').value=state.page;$('zoomValue').textContent=`${Math.round(state.zoom*100)}%`;state.renderTask=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:ratio===1?null:[ratio,0,0,ratio,0,0]});try{await state.renderTask.promise;}catch(e){if(e.name==='RenderingCancelledException')return;throw e;}if(version!==state.renderVersion)return;const text=await page.getTextContent();const layer=new pdfjs.TextLayer({textContentSource:text,container:$('textLayer'),viewport});await layer.render();if(version===state.renderVersion)drawHighlights(viewport);});return state.renderChain.catch(e=>{if(e.name!=='RenderingCancelledException')fail(e);});}
function drawHighlights(viewport){const seen=new Set();const svg=$('highlights');svg.replaceChildren();svg.setAttribute('width',viewport.width);svg.setAttribute('height',viewport.height);svg.setAttribute('viewBox',`0 0 ${viewport.width} ${viewport.height}`);for(const hit of state.hits.filter(h=>h.page===state.page)){for(const segment of hit.segments||[]){const q=segment.quad;if(!q||q.length!==8)continue;const key=`${segment.index}:${segment.start}:${segment.end}`;if(seen.has(key))continue;seen.add(key);const points=[];for(let i=0;i<8;i+=2)points.push(viewport.convertToViewportPoint(q[i],q[i+1]).join(','));const polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');polygon.setAttribute('points',points.join(' '));polygon.setAttribute('fill','#ffdc45');polygon.setAttribute('fill-opacity','.48');svg.append(polygon);}}}
function referenceLink(source){if(source.type==='mfds_label')return officialLink(source.url);const u=new URL(source.url);if(u.protocol!=='https:'||!['assets.roche.com','www.roche.co.kr'].includes(u.hostname))return el('span','','출처 확인 필요');const a=el('a','','제조사 공식 자료 ↗');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}
function renderReference(ref){const card=el('section','fact reference-card');card.append(el('strong','',`${ref.brand} · ${ref.source.type==='mfds_label'?'식약처 허가정보':'이전 제조사 자료'}의 연결 근거`));if(ref.source.type==='mfds_label')card.append(el('small','reference-date',`허가 상태 ${ref.source.status||'확인 필요'} · 최초 허가일 ${ref.source.permitDate||'확인 필요'}${ref.source.cancelDate?` · 취소일 ${ref.source.cancelDate}`:''}`));for(const fact of ref.facts){card.append(el('div','reference-label',`${fact.label}${fact.page?` · ${fact.page}쪽`:''}`),el('blockquote','',fact.quote));}card.append(referenceLink(ref.source),el('small','reference-date',`자료 기준 ${ref.source.documentDate||'문서 날짜 미표시'} · 확인 ${ref.source.checkedAt}`),el('p','result-note',ref.source.type==='mfds_label'?'조회 시점의 식약처 허가정보입니다. 처방일 당시 허가사항과 실제 지급 조건은 별도 확인이 필요합니다.':'이전 검색에서 저장한 제조사 자료입니다. 새 검색은 식약처 API를 사용합니다.'));return card;}
const visibleQuote=h=>typeof h?.quote==='string'&&/[^\s\p{C}]/u.test(h.quote);
const quoteKey=h=>`${h.documentHash}:${h.page}:${h.sourceStart}:${h.sourceEnd}`;
const uniqueQuotesOf=quotes=>[...new Map(quotes.filter(visibleQuote).map(h=>[quoteKey(h),h])).values()];
function quoteCard(hit,result,jobId){
 const card=el('article','quote-card'),meta=el('div','quote-meta');meta.append(el('span','',`약관 원문 · ${hit.page}쪽`));const jump=el('button','','원문 보기 ↗');jump.type='button';
 jump.addEventListener('click',async()=>{state.hits=result.quotes.filter(visibleQuote);state.resultJob=jobId;$('download').disabled=!state.hits.length;state.page=hit.page;await renderPage();const first=hit.segments?.find(s=>s.quad)?.quad;if(first&&state.viewport){const [,y]=state.viewport.convertToViewportPoint(first[0],first[1]);$('pdfScroll').scrollTop=Math.max(0,y-100);}if(innerWidth<681)$('pdfScroll').scrollIntoView({behavior:'smooth'});});
 meta.append(jump);card.append(meta,el('blockquote','',hit.quote));return card;
}
function renderCoverage(result,jobId,byId){
 const panel=el('section','coverage-panel');panel.append(el('h2','','보장 범위 확인'));
 const coverage=result.coverage,used=new Set();
 if(!coverage?.items?.length){panel.append(el('p','','보장 항목과 연결되는 근거를 아직 확인하지 못했습니다.'),el('p','result-note','아래 검색 원문만으로 보장 제외를 뜻하지 않습니다. 지급사유와 해당 특약을 함께 확인해야 합니다.'));return {panel,used};}
 panel.append(el('p','coverage-status','약관에 관련 보장 항목이 명시되어 있습니다.'));
 const kinds={payment:'지급사유 · 보장 조건 원문',definition:'정의 · 성분 · 허가 기준 원문',exclusion:'지급 제외사항 원문',claim:'청구서류 원문'};
 const checks={enrollment:'해당 특약의 실제 가입 여부와 가입금액',period:'진단·처방일과 보험기간·보장개시일',diagnosis:'약관에서 요구하는 진단 기준',treatment:'치료 목적과 처방·치료 사실',limit:'보장 횟수·한도와 이전 지급 내역',approval_date:'약관이 정한 시점의 식약처 허가사항',exclusion:'면책·지급 제외사유',cross_reference:'별표·보통약관 등 참조 조항의 추가 조건'};
 for(const item of coverage.items){
  const title=byId.get(item.titleId);if(!title)continue;
  const section=el('article','coverage-item');section.append(el('div','coverage-caption','약관에 기재된 보장 항목'),quoteCard(title,result,jobId));used.add(quoteKey(title));
  for(const link of item.links){const box=el('div','coverage-link');box.append(el('strong','',link.kind==='ingredient'?'성분 근거를 통한 간접 연결':link.kind==='direct_brand'?'상표명 직접 기재':'입력한 항목과 원문 일치'),el('p','',link.kind==='ingredient'?`${link.label} → ${link.term} → 위 보장 항목`:link.label));if(link.kind==='ingredient')box.append(el('p','result-note','제품 성분 근거와 약관의 성분 항목을 연결했습니다. 실제 처방 목적과 지급 조건은 별도 확인이 필요합니다.'));section.append(box);}
  section.append(el('p','coverage-caution','실제 보장은 가입한 특약과 진단·처방 내용, 아래 지급 조건을 확인해야 합니다.'));
  for(const clause of item.clauses){const hits=uniqueQuotesOf(clause.sourceIds.map(id=>byId.get(id)).filter(Boolean));if(!hits.length)continue;const details=el('details','clause-group');details.open=clause.kind==='payment';details.dataset.kind=clause.kind;details.append(el('summary','',kinds[clause.kind]||'관련 원문'));for(const hit of hits){details.append(quoteCard(hit,result,jobId));used.add(quoteKey(hit));}section.append(details);}
  const pending=el('details','coverage-checks');pending.append(el('summary','','실제 보장 확인에 필요한 사항'));const list=el('ul');for(const check of item.checks){const text=checks[check.kind];if(text)list.append(el('li','',`${text} — 확인 필요`));}pending.append(list,el('p','result-note','업로드한 약관과 성분 자료만으로는 위 사실을 확인할 수 없습니다. 참조 조항의 전체 검토도 필요합니다.'));section.append(pending);
  if(item.truncated)section.append(el('p','result-note','특약 원문 일부만 가져왔습니다. 원문 보기로 이어지는 조항을 확인해 주세요.'));
  panel.append(section);
 }
 return {panel,used};
}
function renderResult(result,jobId){
 $('clearResults').disabled=false;state.hits=result.quotes.filter(visibleQuote);state.resultJob=jobId;$('download').disabled=!state.hits.length;
 const uniqueQuotes=uniqueQuotesOf(state.hits),byId=new Map(state.hits.map(h=>[h.id,h]));const wrap=el('section','investigation-result');
 wrap.append(el('div','result-label',`✦ 약관 원문 ${uniqueQuotes.length}건`));
 const {panel,used}=renderCoverage(result,jobId,byId);wrap.append(panel);
 for(const ref of result.references||[])wrap.append(renderReference(ref));
 for(const p of result.mappings||[]){const fact=el('div','fact');fact.append(el('strong','',p.name),el('div','',`공식 성분 정보: ${Array.isArray(p.ingredients)?p.ingredients.join(', '):p.ingredients}`),officialLink(p.url));wrap.append(fact);}
 const remaining=uniqueQuotes.filter(h=>!used.has(quoteKey(h)));
 if(remaining.length){const details=el('details','clause-group other-sources');details.open=!used.size;details.append(el('summary','',`그 밖의 검색 원문 ${remaining.length}건`));for(const hit of remaining)details.append(quoteCard(hit,result,jobId));wrap.append(details);}
 if(!uniqueQuotes.length)wrap.append(el('p','','연결되는 약관 원문을 찾지 못했습니다. 이 결과만으로 보장 제외를 뜻하지 않습니다.'));
 if(result.truncated)wrap.append(el('p','result-note','일부 결과만 표시했습니다. 원문에서 추가 조항을 확인할 수 있습니다.'));
 wrap.append(el('p','result-note',result.notice||'표시된 원문은 실제 보험금 지급 여부를 확정하지 않습니다.'));$('messages').querySelector('.welcome')?.remove();$('messages').append(wrap);renderPage();
}
function renderProducts(products,box=$('drugResults'),selected=state.selected,onChange=()=>{}){box.replaceChildren();for(const p of products){const card=el('div','product');const label=el('label');const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(p.id);check.addEventListener('change',()=>{if(check.checked){if(selected.size>=5){check.checked=false;return fail(new Error('제품은 최대 5개까지 선택할 수 있습니다.'));}selected.add(p.id);}else selected.delete(p.id);onChange();});label.append(check,document.createTextNode(p.name));card.append(label,el('small','',`${p.manufacturer||'제조사 미표시'} · ${p.id}`),el('small','',`성분: ${Array.isArray(p.ingredients)?p.ingredients.join(', '):p.ingredients||'확인되지 않음'}`),officialLink(p.url));box.append(card);}if(!products.length)box.append(el('p','','일치하는 공식 제품을 찾지 못했습니다. 제품명을 확인해 주세요.'));}
$('policyFile').addEventListener('change',async e=>{const file=e.target.files[0];if(!state.ready||!file){e.target.value='';return;}clearError();try{await ensureCase();const data=new FormData();data.append('file',file);busy(null,'약관을 업로드하고 있습니다.');const {jobId}=await api(`/api/cases/${state.caseId}/documents`,{method:'POST',body:data});followJob(jobId);}catch(e){idle();fail(e);}finally{$('policyFile').value='';}});
$('drugForm').addEventListener('submit',async e=>{e.preventDefault();if(!state.ready)return;clearError();const name=$('drugName').value.trim();if(!name)return;const button=e.target.querySelector('button');button.disabled=true;try{await ensureCase();const data=await api(`/api/cases/${state.caseId}/drugs`,{method:'POST',body:{name}});renderProducts(data.products);}catch(e){fail(e);}finally{button.disabled=false;}});
async function resumeSelection(sourceJobId,drugIds){
 clearError();if(state.busy||!drugIds.length)return;
 if(!await requestCloudConsent())return;
 try{
  busy(null,'선택한 제품의 성분 조사부터 이어서 진행합니다.');
  const {jobId}=await api(`/api/jobs/${encodeURIComponent(sourceJobId)}/resume`,{method:'POST',body:{drugIds,cloudConsent:true}});
  followJob(jobId);await refreshConversation();$('progress').scrollIntoView({block:'nearest'});
 }catch(e){idle();if(['SELECTION_EXPIRED','SELECTION_ALREADY_RESUMED'].includes(e.code))await refreshCase();fail(e);}
}
$('queryForm').addEventListener('submit',async e=>{
 e.preventDefault();clearError();if(state.busy)return;
 const query=$('query').value;if(!query.trim())return fail(new Error('상황 설명 또는 질문을 입력해 주세요.'));
 if(!state.document)return fail(Object.assign(new Error(),{code:'NO_DOCUMENT'}));
 if(!state.config.nimEnabled)return fail(Object.assign(new Error(),{code:'NVIDIA_KEY_REQUIRED'}));
 if(!await requestCloudConsent())return;
 try{
  busy(null,'조사를 준비하고 있습니다.');
  if(!state.conversationId){const conversation=await api(`/api/cases/${state.caseId}/conversation`,{method:'POST'});state.conversationId=conversation.id;}
  const body={query,conversationId:state.conversationId,drugIds:[...state.selected],cloudConsent:true};
  const {jobId}=await api(`/api/cases/${state.caseId}/investigations`,{method:'POST',body});
  $('query').value='';followJob(jobId);await refreshConversation();$('progress').scrollIntoView({block:'nearest'});
 }catch(e){idle();if(e.code==='CONVERSATION_CHANGED')await refreshCase();fail(e);}
});
$('clearResults').addEventListener('click',async()=>{
 if(state.busy||!state.document)return;clearError();
 try{busy(null,'새 대화를 준비하고 있습니다.');const conversation=await api(`/api/cases/${state.caseId}/conversation`,{method:'POST'});
  state.selected.clear();$('drugResults').querySelectorAll('input[type=checkbox]').forEach(input=>input.checked=false);
  $('query').value='';renderConversation(conversation);$('highlights').replaceChildren();
 }catch(e){fail(e);}finally{idle();$('query').focus();}
});
$('query').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){$('queryForm').requestSubmit();}});
$('cancelJob').addEventListener('click',async()=>{if(!state.job)return;try{await api(`/api/jobs/${state.job}/cancel`,{method:'POST'});$('progressText').textContent='취소하고 있습니다.';}catch(e){fail(e);}});
$('clearCase').addEventListener('click',async()=>{if(!state.caseId)return;if(!confirm('올린 자료와 조사 결과를 모두 삭제할까요?'))return;try{await api(`/api/cases/${state.caseId}`,{method:'DELETE'});clearBrowserData();state.stream?.close();location.reload();}catch(e){fail(e);}});
$('download').addEventListener('click',async()=>{if(!state.resultJob)return;const b=$('download');b.disabled=true;clearError();try{const r=await fetch(`/api/jobs/${state.resultJob}/annotated.pdf`);if(!r.ok){const data=await r.json();throw Object.assign(new Error('PDF 저장에 실패했습니다.'),{code:data.code||data.error?.code||data.error});}const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=`concreteInsure-${state.document?.name||'약관.pdf'}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(e){fail(e);}finally{b.disabled=!state.resultJob||!state.hits.length;}});
$('prevPage').addEventListener('click',()=>{if(state.pdf&&state.page>1){state.page--;renderPage();$('pdfScroll').scrollTop=0;}});$('nextPage').addEventListener('click',()=>{if(state.pdf&&state.page<state.pdf.numPages){state.page++;renderPage();$('pdfScroll').scrollTop=0;}});$('pageNumber').addEventListener('change',()=>{if(state.pdf){state.page=Math.max(1,Math.min(state.pdf.numPages,Number($('pageNumber').value)||1));renderPage();$('pdfScroll').scrollTop=0;}});$('zoomIn').addEventListener('click',()=>{state.zoom=Math.min(3,state.zoom+.2);renderPage();});$('zoomOut').addEventListener('click',()=>{state.zoom=Math.max(.5,state.zoom-.2);renderPage();});let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>renderPage(),150);});
function clearBrowserData(){
 for(const storage of [sessionStorage,localStorage]){
  for(const key of Object.keys(storage))if(['concrete-insure-','insure-lens-'].some(prefix=>key.startsWith(prefix)))storage.removeItem(key);
 }
}
function savedCaseId(){
 // A per-tab pointer preserves the current case; older versions used another key/storage.
 for(const storage of [sessionStorage,localStorage]){
  for(const key of ['concrete-insure-case','insure-lens-case']){
   const id=storage.getItem(key);
   if(id&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id))return id;
   if(id)storage.removeItem(key);
  }
 }
 return null;
}
function forgetCasePointer(id){
 for(const storage of [sessionStorage,localStorage]){
  for(const key of ['concrete-insure-case','insure-lens-case'])if(storage.getItem(key)===id)storage.removeItem(key);
 }
}
async function restoreCase(){
 const id=savedCaseId();if(!id)return null;
 let current;
 try{current=await api(`/api/cases/${id}`,{signal:AbortSignal.timeout(15000)});}
 catch(error){if(error.status!==404)throw error;forgetCasePointer(id);return null;}
 // Migrate only after the server has verified ownership. Never submit or delete on reload.
 state.caseId=id;sessionStorage.setItem('concrete-insure-case',id);
 sessionStorage.removeItem('insure-lens-case');
 for(const key of ['concrete-insure-case','insure-lens-case'])if(localStorage.getItem(key)===id)localStorage.removeItem(key);
 await refreshCase(current);
 return current.jobs.find(job=>['queued','running'].includes(job.state));
}
async function start(){
 if(state.starting)return;
 state.starting=true;state.ready=false;clearError();$('retryRestore').classList.add('hidden');
 busy(null,'이전 대화와 요청을 불러오고 있습니다.');
 for(const id of ['clearCase','drugName'])$(id).disabled=true;
 $('drugForm').querySelector('button').disabled=true;
 for(const id of ['query','drugName','policyFile'])$(id).value='';
 $('pageNumber').value='1';
 document.querySelectorAll('details').forEach(section=>section.open=false);
 $('cloudConsent').checked=false;$('confirmConsent').disabled=true;
 try{
  state.config=await api('/api/config',{signal:AbortSignal.timeout(15000)});
  const activeJob=await restoreCase();
  state.ready=true;idle();
  for(const id of ['clearCase','drugName'])$(id).disabled=false;
  $('drugForm').querySelector('button').disabled=false;
  $('availability').textContent=state.config.nimEnabled?'검색 준비 완료':'연결 설정 필요';
  if(activeJob)followJob(activeJob.id,'진행 중인 요청에 다시 연결하고 있습니다.');
 }catch(error){
  $('progress').classList.add('hidden');$('availability').textContent='대화 복원 확인 필요';
  fail(new Error('이전 대화와 요청을 불러오지 못했습니다. 자료는 삭제하지 않았습니다. 서버 연결을 확인한 뒤 다시 시도해 주세요.'));
  $('retryRestore').classList.remove('hidden');
 }finally{state.starting=false;}
}
$('retryRestore').addEventListener('click',()=>location.reload());
// Recheck persisted state when returning from the back/forward cache.
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
start();
