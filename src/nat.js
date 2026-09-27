import {spawn} from 'node:child_process';import {existsSync} from 'node:fs';import {fileURLToPath} from 'node:url';
import {runInvestigation} from './agent.js';import {withProviderFallback} from './provider-fallback.js';import {AppError,ensure} from './core.js';
const python=fileURLToPath(new URL('../integrations/nat/.venv/bin/python',import.meta.url));
const script=fileURLToPath(new URL('../integrations/nat/run_local.py',import.meta.url));
export function runnerMode(){const mode=process.env.AGENT_RUNNER||'auto';ensure(['auto','nat','node'].includes(mode),'INVALID_AGENT_RUNNER');if(mode==='nat')ensure(existsSync(python),'NAT_RUNTIME_MISSING',503);return mode==='node'?'node':existsSync(python)?'nat':'node';}
async function runConfigured(input){
 if(runnerMode()==='node')return runInvestigation(input);
 const {document,request,products,signal,onEvent=()=>{}}=input;
 return new Promise((resolve,reject)=>{
  const child=spawn(python,[script],{stdio:['pipe','pipe','pipe'],detached:process.platform!=='win32'});let output='',errBuffer='',failureCode=null,done=false;
  const kill=()=>{try{if(process.platform==='win32')child.kill('SIGKILL');else process.kill(-child.pid,'SIGKILL');}catch{}};
  const fail=e=>{if(done)return;done=true;clearTimeout(timer);kill();reject(e);};
  const timer=setTimeout(()=>fail(new AppError('AGENT_TIMEOUT',504)),600000);
  const abort=()=>fail(new AppError('CANCELLED',409));signal?.addEventListener('abort',abort,{once:true});
  child.on('error',()=>fail(new AppError('NAT_RUNTIME_MISSING',503)));child.stdin.on('error',()=>{});
  child.stdout.on('data',b=>{output+=b;if(output.length>12e6)fail(new AppError('NAT_OUTPUT_LIMIT',502));});
  child.stderr.on('data',b=>{errBuffer+=b;if(errBuffer.length>65536)errBuffer=errBuffer.slice(-8192);const lines=errBuffer.split('\n');errBuffer=lines.pop();for(const line of lines){try{const v=JSON.parse(line);if(typeof v.error==='string'&&/^[A-Z_]{3,80}$/.test(v.error))failureCode=v.error;if(['stage_started','stage_completed'].includes(v.event))onEvent(v.event,v.data);}catch{}}});
  child.on('close',code=>{signal?.removeEventListener('abort',abort);if(done)return;done=true;clearTimeout(timer);if(code!==0){reject(new AppError(failureCode||'NAT_WORKFLOW_FAILED',502));return;}try{const value=JSON.parse(output);ensure(Array.isArray(value.quotes)&&Array.isArray(value.terms)&&['local','nim-react'].includes(value.mode),'NAT_INVALID_RESULT',502);resolve(value);}catch{reject(new AppError('NAT_INVALID_RESULT',502));}});
  child.stdin.end(JSON.stringify({document,request,products}));if(signal?.aborted)abort();
 });
}

export function configuredInvestigation(input){return withProviderFallback(input,runConfigured);}
