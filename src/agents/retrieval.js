import { pdfOperation } from '../pdf.js';
import { ensure } from '../core.js';
/** Grounded term IDs -> application-owned PDF source spans. */
export async function retrievePolicy({document,terms,ids,pages,signal},operation=pdfOperation) {
 ensure(Array.isArray(ids)&&ids.length>0&&ids.length<=25&&ids.every(i=>Number.isInteger(i)&&i>=0&&i<terms.length),'UNGROUNDED_TERM');
 return operation({op:'search',pdf:document.pdf,index:document.index,...(pages===undefined?{}:{pages}),terms:[...new Set(ids)].map(i=>terms[i])},{signal});
}
