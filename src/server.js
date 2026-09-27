import express from 'express';
import multer from 'multer';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir,writeFile,rm,stat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { AppError,ensure,querySchema } from './core.js';
import { Store,Queue } from './store.js';
import { pdfOperation } from './pdf.js';
import { Nvidia,Drugs } from './providers.js';
import { prescriptionCandidates } from './agents/prescription.js';
import { runInvestigation } from './agent.js';
import { configuredInvestigation,runnerMode } from './nat.js';
const ROOT=fileURLToPath(new URL('../',import.meta.url));
const upload=multer({storage:multer.memoryStorage(),limits:{fileSize:20*1024*1024,files:1,fields:1,parts:3}}).single('file');
const uuid=z.string().uuid();
export function createApp({root=process.env.DATA_DIR||path.join(ROOT,'.local-data'),nim=new Nvidia(),drugs=new Drugs(),pdf=pdfOperation,investigate=runInvestigation}={}){
 root=path.resolve(root);const store=new Store(root),queue=new Queue(store);const app=express();app.disable('x-powered-by');
 app.use((req,res,next)=>{
  try{
   ensure(/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(req.headers.host||''),'HOST_FORBIDDEN',403);
   const origin=req.headers.origin;ensure(!origin||origin===`http://${req.headers.host}`,'ORIGIN_FORBIDDEN',403);
   if(!['GET','HEAD'].includes(req.method))ensure(req.get('X-Local-Request')==='1','LOCAL_REQUEST_REQUIRED',403);
   res.set({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"});
   let session=(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('insurelens_session='))?.slice('insurelens_session='.length);
   if(!session||!uuid.safeParse(session).success){session=randomUUID();res.setHeader('Set-Cookie',`insurelens_session=${session}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400`);}
   req.owner=session;next();
  }catch(e){next(e);}
 });
 app.use(express.json({limit:'64kb'}));
 const caseFor=req=>store.get(uuid.parse(req.params.id),req.owner);
 const dir=id=>path.join(root,id);
 const publicCase=c=>({id:c.id,document:c.document?Object.fromEntries(Object.entries(c.document).filter(([k])=>!['pdf','index'].includes(k))):null,jobs:store.jobs(c.id).filter(j=>j.kind!=='investigation'||j.documentId===c.document?.id),products:Object.values(c.products)});
 app.get('/api/config',(req,res)=>res.json({nimEnabled:nim.enabled,ocrEnabled:!!(nim.enabled&&nim.ocrUrl),mfdsEnabled:!!drugs.key,translationEnabled:!!(nim.enabled&&process.env.TRANSLATION_MODEL),mode:nim.enabled?'nim-react':'local',orchestrator:runnerMode()}));
 app.post('/api/cases',(req,res)=>res.status(201).json({id:store.create(req.owner).id}));
 app.get('/api/cases/:id',(req,res)=>res.json(publicCase(caseFor(req))));
 app.delete('/api/cases/:id',async(req,res)=>{const c=caseFor(req);await queue.cancelCase(c.id);store.remove(c.id);await rm(dir(c.id),{recursive:true,force:true});res.sendStatus(204);});
 app.post('/api/cases/:id/documents',upload,async(req,res)=>{
  const c=caseFor(req);ensure(req.file?.buffer.subarray(0,5).toString()==='%PDF-','INVALID_PDF');
  ensure(store.jobs(c.id).every(j=>!['queued','running'].includes(j.state)),'CASE_BUSY',429);
  const docId=randomUUID(),folder=dir(c.id);await mkdir(folder,{recursive:true,mode:0o700});
  const pdfPath=path.join(folder,`${docId}.pdf`),index=path.join(folder,`${docId}.json.gz`);
  const jobId=store.createJob(c.id,'document',docId);await writeFile(pdfPath,req.file.buffer,{mode:0o600});
  queue.add(jobId,async(signal,emit)=>{try{emit('stage_started',{stage:'document',message:'약관의 원문과 문자 위치를 읽고 있습니다.'});const meta=await pdf({op:'index',pdf:pdfPath,index},{signal});ensure(meta.textPages>0,'TEXT_LAYER_REQUIRED',422);const document={id:docId,name:req.file.originalname,pdf:pdfPath,index,...meta};store.get(c.id,req.owner);const old=store.get(c.id,req.owner).document;store.setDocument(c.id,document);if(old){await rm(old.pdf,{force:true});await rm(old.index,{force:true});}emit('stage_completed',{stage:'document'});return {document:publicCase(store.get(c.id,req.owner)).document};}catch(e){await rm(pdfPath,{force:true});await rm(index,{force:true});throw e;}});
  res.status(202).json({jobId});
 });
 app.get('/api/cases/:id/pdf',(req,res)=>{const c=caseFor(req);ensure(c.document,'DOCUMENT_REQUIRED',409);res.type('application/pdf').sendFile(c.document.pdf,{dotfiles:'allow'});});
 app.post('/api/cases/:id/ocr',upload,async(req,res)=>{
  const c=caseFor(req);ensure(req.file&&req.file.size<=8*1024*1024,'PRESCRIPTION_SIZE_LIMIT',413);
  const isPdf=req.file.buffer.subarray(0,5).toString()==='%PDF-',consent=req.get('X-Cloud-Consent')==='yes';
  if(!isPdf)ensure(consent&&nim.enabled&&nim.ocrUrl,'OCR_CONSENT_OR_CONFIG_REQUIRED',409);
  const folder=dir(c.id);await mkdir(folder,{recursive:true,mode:0o700});const input=path.join(folder,`${randomUUID()}.input`),index=input+'.json.gz';const buffer=req.file.buffer;
  const jobId=store.createJob(c.id,'ocr');
  queue.add(jobId,async(signal,emit)=>{emit('stage_started',{stage:'ocr',message:'진료·처방 자료의 글자를 읽고 있습니다.'});try{
   if(!isPdf){const value=await nim.ocr(buffer,signal);return {...value,candidates:await prescriptionCandidates(value.text,{nim,consent,signal})};}
   await writeFile(input,buffer,{mode:0o600});const meta=await pdf({op:'index',pdf:input,index},{signal});ensure(meta.pages<=8,'PRESCRIPTION_PAGE_LIMIT');
   if(meta.textPages===meta.pages){const {text}=await pdf({op:'text',pdf:input,index},{signal});return {text,candidates:await prescriptionCandidates(text,{nim,consent,signal}),requiresConfirmation:true,method:'pdf-text-layer'};}
   ensure(consent&&nim.enabled&&nim.ocrUrl,'OCR_CONSENT_OR_CONFIG_REQUIRED',409);const {images}=await pdf({op:'render',pdf:input},{signal});let results=[];for(const image of images)results.push(await nim.ocr(Buffer.from(image,'base64'),signal));const text=results.map(x=>x.text).join('\n');return {text,candidates:await prescriptionCandidates(text,{nim,consent,signal}),requiresConfirmation:true,method:'ocr'};
  }finally{await rm(input,{force:true});await rm(index,{force:true});}});res.status(202).json({jobId});
 });
 app.post('/api/cases/:id/drugs',async(req,res)=>{const c=caseFor(req),{name}=z.object({name:z.string().min(2).max(120)}).strict().parse(req.body);const result=await drugs.lookup(name);const products={...c.products};for(const p of result.products)products[p.id]=p;ensure(Object.keys(products).length<=300,'DRUG_RESULT_LIMIT',429);store.setProducts(c.id,products);res.json(result);});
 app.post('/api/cases/:id/investigations',(req,res)=>{
  const c=caseFor(req);ensure(c.document,'DOCUMENT_REQUIRED',409);const request=querySchema.parse(req.body);ensure(!nim.enabled||request.cloudConsent,'NIM_CONSENT_REQUIRED',409);
  const products=request.drugIds.map(id=>{ensure(c.products[id],'DRUG_SELECTION_REQUIRED');return c.products[id];});const jobId=store.createJob(c.id,'investigation',c.document.id);
  queue.add(jobId,(signal,onEvent)=>investigate({document:c.document,request,products,nim,onEvent,signal}));res.status(202).json({jobId});
 });
 app.get('/api/jobs/:id',(req,res)=>res.json(store.job(uuid.parse(req.params.id),req.owner)));
 app.post('/api/jobs/:id/cancel',(req,res)=>{const j=store.job(uuid.parse(req.params.id),req.owner);queue.cancel(j.id);res.json({ok:true});});
 app.get('/api/jobs/:id/events',(req,res)=>{
  const id=uuid.parse(req.params.id);store.job(id,req.owner);let after=Number(req.get('Last-Event-ID')||req.query.after||0);ensure(Number.isSafeInteger(after)&&after>=0,'INVALID_EVENT_ID');
  res.set({'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive','X-Accel-Buffering':'no'});res.flushHeaders();let timer,heart;
  const close=()=>{clearInterval(timer);clearInterval(heart);};
  const send=()=>{try{for(const e of store.events(id,after)){res.write(`id: ${e.id}\nevent: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`);after=e.id;}const j=store.job(id,req.owner);if(['completed','failed','cancelled'].includes(j.state)){close();res.end();}}catch{close();res.end();}};
  timer=setInterval(send,300);heart=setInterval(()=>res.write(': heartbeat\n\n'),15000);req.on('close',close);send();
 });
 let exports=0;
 app.get('/api/jobs/:id/annotated.pdf',async(req,res)=>{
  const j=store.job(uuid.parse(req.params.id),req.owner),c=store.get(j.caseId,req.owner);ensure(j.state==='completed'&&j.kind==='investigation','RESULT_REQUIRED',409);ensure(j.documentId===c.document?.id,'DOCUMENT_REPLACED',409);ensure(exports<2,'PDF_BUSY',429);exports++;
  try{const output=path.join(dir(c.id),`${j.id}.annotated.pdf`);let exists=true;try{await stat(output);}catch{exists=false;}
   if(!exists){const r=await pdf({op:'annotate',pdf:c.document.pdf,index:c.document.index,hits:j.result.quotes,output});res.set({'X-Highlight-Count':String(r.count),'X-Highlight-Skipped':String(r.skipped)});}
   res.set('Content-Disposition','attachment; filename="insurelens-highlighted.pdf"');res.type('application/pdf').sendFile(output,{dotfiles:'allow'});
  }finally{exports--;}
 });
 app.use('/vendor/pdfjs',express.static(path.join(ROOT,'node_modules/pdfjs-dist')));
 app.use(express.static(path.join(ROOT,'public')));
 app.use((err,req,res,next)=>{if(res.headersSent)return next(err);const isZod=err instanceof z.ZodError;res.status(isZod?400:err.status||400).json({error:isZod?'INVALID_REQUEST':err.code==='LIMIT_FILE_SIZE'?'FILE_TOO_LARGE':(/^[A-Z_]{3,80}$/.test(err.message)?err.message:'REQUEST_FAILED')});});
 return {app,store,queue};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const {app}=createApp({investigate:configuredInvestigation});const port=Number(process.env.PORT||8000);app.listen(port,'127.0.0.1',()=>console.log(`InsureLens http://127.0.0.1:${port}`));
}
