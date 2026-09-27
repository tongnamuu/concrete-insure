import {readFileSync} from 'node:fs';
import {ensure} from '../core.js';
const catalog=JSON.parse(readFileSync(new URL('../../data/drug-references.json',import.meta.url),'utf8'));
const hosts=new Set(['www.roche.co.kr','assets.roche.com']);
for(const item of catalog){
 const url=new URL(item.source.url);
 ensure(url.protocol==='https:'&&hosts.has(url.hostname)&&item.scope==='product_reference','INVALID_REFERENCE_SOURCE');
 for(const fact of item.facts)ensure(fact.terms.every(t=>fact.quote.includes(t)),'UNGROUNDED_REFERENCE_TERM');
}
// Curated, dated product references are not a claim of live MFDS approval or patient diagnosis.
// A prodrug/active-metabolite relation must have an explicit source; never strip drug-name suffixes.
export function resolveDrugReferences({query='',description='',confirmedTerms=[],products=[]}={}){
 const values=[query,description,...confirmedTerms,...products.map(p=>p.name)];
 const references=catalog.filter(item=>item.aliases.some(alias=>{
  const escaped=alias.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const re=new RegExp(`(?:^|[^\\p{L}\\p{N}])${escaped}(?=$|[^\\p{L}\\p{N}]|를|을|은|는|이|가|도|와|과|정|캡슐|현탁|처방)`,'iu');
  return values.some(text=>re.test(text));
 }));
 const specificTerms=[...new Set(references.flatMap(r=>r.facts.filter(f=>f.priority==='specific').flatMap(f=>f.terms)))];
 const contextTerms=[...new Set(references.flatMap(r=>r.facts.filter(f=>f.priority==='context').flatMap(f=>f.terms)))];
 return {references:structuredClone(references),specificTerms,contextTerms};
}
export function verifyDrugReferences(references){
 ensure(Array.isArray(references)&&references.length<=catalog.length,'INVALID_DRUG_REFERENCES');
 for(const ref of references)ensure(catalog.some(item=>JSON.stringify(item)===JSON.stringify(ref)),'UNVERIFIED_DRUG_REFERENCE');
 return references;
}
