import test from 'node:test';import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';import {mkdtemp,writeFile,rm} from 'node:fs/promises';import os from 'node:os';import path from 'node:path';import {execFileSync} from 'node:child_process';import {pdfOperation} from '../src/pdf.js';
const natPython=new URL('../integrations/nat/.venv/bin/python',import.meta.url).pathname;
test('actual native NAT load_workflow executes Node subagents and returns exact PDF evidence',{skip:!existsSync(natPython),timeout:60000},async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'insurelens-nat-test-'));
 try{
 const pdf=path.join(dir,'document.pdf'),index=path.join(dir,'index.json');
 const bytes=execFileSync(new URL('../.venv/bin/python',import.meta.url).pathname,['-c',"import pymupdf as f,sys;d=f.open();p=d.new_page();p.insert_text((50,100),'독감 항바이러스제',fontname='korea');sys.stdout.buffer.write(d.tobytes())"]);
 await writeFile(pdf,bytes);await pdfOperation({op:'index',pdf,index});
 const input={document:{id:'test',pdf,index},request:{query:'독감 관련 원문',confirmedTerms:[],drugIds:[],cloudConsent:false,translation:false},products:[]};
 const raw=execFileSync(natPython,[new URL('../integrations/nat/run_local.py',import.meta.url).pathname],{input:JSON.stringify(input),encoding:'utf8',timeout:55000,maxBuffer:8e6,env:{...process.env,NVIDIA_API_KEY:'',NAT_CONFIG_DIR:dir,NODE_EXECUTABLE:process.execPath},stdio:['pipe','pipe','pipe']});
 const result=JSON.parse(raw);assert.equal(result.mode,'local');assert.ok(result.quotes.some(h=>h.quote.includes('독감 항바이러스제')));assert.ok(!('answer' in result));
 }finally{await rm(dir,{recursive:true,force:true});}
});
