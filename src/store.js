import { DatabaseSync } from 'node:sqlite';
import { mkdirSync,chmodSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { ensure } from './core.js';
export class Store {
 constructor(root){this.root=root;mkdirSync(root,{recursive:true,mode:0o700});chmodSync(root,0o700);this.db=new DatabaseSync(path.join(root,'store.sqlite'));this.db.exec(`PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,owner TEXT NOT NULL,created INTEGER NOT NULL,document TEXT,products TEXT NOT NULL DEFAULT '{}');
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,result TEXT,error TEXT,created INTEGER NOT NULL,document_id TEXT);
 CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,event TEXT NOT NULL,data TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS event_job ON events(job_id,id);`);
 for(const j of this.db.prepare("SELECT id FROM jobs WHERE state IN ('running','queued')").all()){this.db.prepare("UPDATE jobs SET state='failed',error='SERVER_RESTARTED' WHERE id=?").run(j.id);this.event(j.id,'failed',{code:'SERVER_RESTARTED'});}
 }
 create(owner){ensure(this.db.prepare('SELECT count(*) AS n FROM cases').get().n<30,'CASE_LIMIT',429);const id=randomUUID();this.db.prepare('INSERT INTO cases(id,owner,created) VALUES(?,?,?)').run(id,owner,Date.now());return this.get(id,owner);}
 get(id,owner){const r=this.db.prepare('SELECT * FROM cases WHERE id=? AND owner=?').get(id,owner);ensure(r,'CASE_NOT_FOUND',404);return {...r,document:r.document?JSON.parse(r.document):null,products:JSON.parse(r.products)};}
 setDocument(id,doc){this.db.prepare('UPDATE cases SET document=? WHERE id=?').run(JSON.stringify(doc),id);}
 setProducts(id,products){this.db.prepare('UPDATE cases SET products=? WHERE id=?').run(JSON.stringify(products),id);}
 jobs(caseId){return this.db.prepare('SELECT id,state,kind,document_id AS documentId FROM jobs WHERE case_id=? ORDER BY created DESC').all(caseId);}
 job(id,owner){const r=this.db.prepare('SELECT jobs.* FROM jobs JOIN cases ON jobs.case_id=cases.id WHERE jobs.id=? AND cases.owner=?').get(id,owner);ensure(r,'JOB_NOT_FOUND',404);return {id:r.id,caseId:r.case_id,kind:r.kind,state:r.state,result:r.result?JSON.parse(r.result):null,error:r.error,documentId:r.document_id};}
 createJob(caseId,kind,documentId=null){ensure(this.db.prepare('SELECT count(*) AS n FROM jobs').get().n<500,'JOB_LIMIT',429);ensure(this.db.prepare("SELECT count(*) AS n FROM jobs WHERE case_id=? AND state IN ('queued','running')").get(caseId).n<3,'CASE_BUSY',429);const id=randomUUID();this.db.prepare('INSERT INTO jobs(id,case_id,kind,state,created,document_id) VALUES(?,?,?,?,?,?)').run(id,caseId,kind,'queued',Date.now(),documentId);this.event(id,'queued',{});return id;}
 state(id,state,result=null,error=null){this.db.prepare('UPDATE jobs SET state=?,result=?,error=? WHERE id=?').run(state,result===null?null:JSON.stringify(result),error,id);}
 event(id,event,data){this.db.prepare('INSERT INTO events(job_id,event,data) VALUES(?,?,?)').run(id,event,JSON.stringify(data));}
 events(id,after=0){return this.db.prepare('SELECT id,event,data FROM events WHERE job_id=? AND id>? ORDER BY id').all(id,after).map(x=>({...x,data:JSON.parse(x.data)}));}
 remove(id){this.db.prepare('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE case_id=?)').run(id);this.db.prepare('DELETE FROM jobs WHERE case_id=?').run(id);this.db.prepare('DELETE FROM cases WHERE id=?').run(id);}
 close(){this.db.close();}
}
export class Queue {
 constructor(store){this.store=store;this.tail=Promise.resolve();this.controls=new Map();}
 add(id,fn){const controller=new AbortController();let resolveDone;const done=new Promise(r=>resolveDone=r);this.controls.set(id,{controller,done});
 this.tail=this.tail.catch(()=>{}).then(async()=>{
 try {if(controller.signal.aborted)throw new Error('CANCELLED');this.store.state(id,'running');const result=await fn(controller.signal,(event,data)=>{if(!controller.signal.aborted)this.store.event(id,event,data);});if(controller.signal.aborted)throw new Error('CANCELLED');this.store.state(id,'completed',result);this.store.event(id,'completed',{resultUrl:`/api/jobs/${id}`});}
 catch(e){const cancelled=controller.signal.aborted;const code=cancelled?'CANCELLED':(/^[A-Z_]{3,80}$/.test(e.message)?e.message:'PROCESSING_FAILED');this.store.state(id,cancelled?'cancelled':'failed',null,code);this.store.event(id,cancelled?'cancelled':'failed',{code});}
 finally{this.controls.delete(id);resolveDone();}
 });return done;}
 cancel(id){this.controls.get(id)?.controller.abort();}
 async cancelCase(caseId){const jobs=this.store.jobs(caseId);for(const j of jobs)this.cancel(j.id);await Promise.all(jobs.map(j=>this.controls.get(j.id)?.done));}
}
