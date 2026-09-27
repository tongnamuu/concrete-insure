import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { AppError } from './core.js';
const worker=fileURLToPath(new URL('../python/pdf_worker.py',import.meta.url));
export function pdfOperation(payload,{timeout=120000,python=process.env.PDF_PYTHON||fileURLToPath(new URL('../.venv/bin/python',import.meta.url)),signal}={}){
 return new Promise((resolve,reject)=>{
  const child=spawn(python,[worker],{stdio:['pipe','pipe','pipe']});let parts=[],size=0,done=false;
  function fail(e){if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);child.kill('SIGKILL');reject(e);}
  const timer=setTimeout(()=>fail(new AppError('PDF_TIMEOUT',504)),timeout);
  const abort=()=>fail(new AppError('CANCELLED',409));signal?.addEventListener('abort',abort,{once:true});
  child.on('error',()=>fail(new AppError('PDF_RUNTIME_MISSING',503)));child.stdin.on('error',()=>{});
  child.stdout.on('data',b=>{size+=b.length;if(size>40*1024*1024)fail(new AppError('PDF_OUTPUT_LIMIT',413));else parts.push(b);});
  child.stderr.on('data',()=>{});
  child.on('close',()=>{signal?.removeEventListener('abort',abort);if(done)return;done=true;clearTimeout(timer);try{const r=JSON.parse(Buffer.concat(parts));if(r.error)reject(new AppError(r.error,422));else resolve(r.value);}catch{reject(new AppError('PDF_WORKER_FAILED',500));}});
  child.stdin.end(JSON.stringify(payload));if(signal?.aborted)abort();
 });
}
