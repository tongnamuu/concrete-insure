import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const project=fileURLToPath(new URL('../',import.meta.url));
export const python=process.env.PDF_PYTHON||path.join(project,'.venv/bin/python');
export async function startPythonTestServer(dataDir,factory='tests.browser_server:create_test_app'){
 const child=spawn(python,['-m','uvicorn',factory,'--factory','--host','127.0.0.1','--port','0'],{cwd:project,env:{...process.env,DATA_DIR:dataDir,NVIDIA_API_KEY:'',NIM_API_KEY:'',MFDS_API_KEY:'',MFDS_SERVICE_KEY:''},stdio:['ignore','pipe','pipe']});
 let log='';let base;const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(`Python test server timeout: ${log}`)),30000);const inspect=b=>{log=(log+b.toString()).slice(-12000);const match=log.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);if(match&&!base){base=match[1];clearTimeout(timer);resolve(base);}};child.stdout.on('data',inspect);child.stderr.on('data',inspect);child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('exit',code=>{clearTimeout(timer);if(!base)reject(new Error(`Python test server exited ${code}: ${log}`));});});
 const close=async()=>{if(child.exitCode!==null||child.signalCode!==null)return;await new Promise(resolve=>{const timer=setTimeout(()=>child.kill('SIGKILL'),5000);child.once('exit',()=>{clearTimeout(timer);resolve();});child.kill('SIGTERM');});};
 try{await ready;return {base,close};}catch(e){await close();throw e;}
}
