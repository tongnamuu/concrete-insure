import { ensure, NOTICE } from '../core.js';
import {verifyDrugReferences} from './drug-references.js';
/** Accepts only source objects emitted by trusted retrieval, never model prose. */
export function assembleEvidence({hits,mappings,references=[],terms,mode,truncated,coverage={status:'unresolved',scope:'policy_benefit_only',items:[],truncated:false}}) {
 for(const h of hits) {
  ensure(h.offsetEncoding==='unicode-code-points'&&typeof h.quote==='string'&&typeof h.matchedText==='string'&&h.sourceStart<=h.start&&h.end<=h.sourceEnd,'INVALID_SOURCE_SPAN');
  ensure(Array.from(h.quote).slice(h.start-h.sourceStart,h.end-h.sourceStart).join('')===h.matchedText,'INVALID_SOURCE_SPAN');
  ensure(h.segments.every(s=>s.start>=h.start&&s.end<=h.end&&(s.quad===null||(s.quad.length===8&&s.quad.every(Number.isFinite)))),'INVALID_SOURCE_GEOMETRY');
 }
 const visibleHits=hits.filter(h=>/[^\s\p{C}]/u.test(h.quote));
 const sourceIds=new Set(visibleHits.map(h=>h.id));
 for(const item of coverage.items){ensure(sourceIds.has(item.titleId)&&item.clauses.every(c=>sourceIds.has(c.headingId)&&c.sourceIds.every(id=>sourceIds.has(id)))&&item.links.every(l=>l.sourceIds.every(id=>sourceIds.has(id)))&&item.checks.every(c=>c.sourceIds.every(id=>sourceIds.has(id))),'INVALID_COVERAGE_SOURCE');}
 return {coverage,quotes:visibleHits,mappings,references:verifyDrugReferences(references),terms,notice:NOTICE,mode,truncated};
}
