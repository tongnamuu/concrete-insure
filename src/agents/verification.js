import { ensure, NOTICE } from '../core.js';
import {verifyDrugReferences} from './drug-references.js';
/** Accepts only source objects emitted by trusted retrieval, never model prose. */
export function assembleEvidence({hits,mappings,references=[],terms,mode,truncated}) {
 for(const h of hits) {
  ensure(h.offsetEncoding==='unicode-code-points'&&typeof h.quote==='string'&&typeof h.matchedText==='string'&&h.sourceStart<=h.start&&h.end<=h.sourceEnd,'INVALID_SOURCE_SPAN');
  ensure(Array.from(h.quote).slice(h.start-h.sourceStart,h.end-h.sourceStart).join('')===h.matchedText,'INVALID_SOURCE_SPAN');
  ensure(h.segments.every(s=>s.start>=h.start&&s.end<=h.end&&(s.quad===null||(s.quad.length===8&&s.quad.every(Number.isFinite)))),'INVALID_SOURCE_GEOMETRY');
 }
 return {quotes:hits,mappings,references:verifyDrugReferences(references),terms,notice:NOTICE,mode,truncated};
}
