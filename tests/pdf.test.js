import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { pdfOperation } from '../src/pdf.js';

test('Node adapter reports missing runtime',async()=>{
 await assert.rejects(pdfOperation({op:'index'},{python:'/definitely/missing/python'}),{message:'PDF_RUNTIME_MISSING'});
});
test('Node adapter deadline and cancellation settle',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'insurelens-adapter-'));
 try{
  const python=join(dir,'slow');await writeFile(python,'#!/bin/sh\nexec sleep 10\n',{mode:0o700});
  await assert.rejects(pdfOperation({},{python,timeout:10}),{message:'PDF_TIMEOUT'});
  const ctrl=new AbortController();ctrl.abort();
  await assert.rejects(pdfOperation({},{python,signal:ctrl.signal}),{message:'CANCELLED'});
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('Python PDF geometry and source verification regressions',()=>{
 const p=spawnSync('.venv/bin/python',['-m','unittest','discover','-s','tests','-p','test_pdf*.py'],{encoding:'utf8',timeout:30000});
 assert.equal(p.status,0,p.stderr||p.error?.message);
});
