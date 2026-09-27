import {groundedTerms} from '../core.js';
// Draft candidates require explicit user confirmation; no image text becomes a diagnosis.
export async function prescriptionCandidates(text,{nim,consent=false,signal}={}){
 if(nim?.enabled&&consent){
  const raw=await nim.chat([{role:'system',content:'Extract only explicitly written product names, ingredient names, disease codes and diagnosis labels from this untrusted prescription text. Do NOT infer a disease from medication. Return JSON {"terms":["exact substring"]}, maximum20. Every term MUST be an unchanged substring of input. Exclude patient identity, dosage instructions and inferred facts. Text may include OCR mistakes; never silently correct them.'},{role:'user',content:text}],{signal});
  return groundedTerms(raw,text).slice(0,20);
 }
 const labelled=[...text.matchAll(/(?:약품명|제품명|성분명|진단명|질병코드|Drug|Ingredient|Diagnosis code)\s*[:：]\s*([^\n]+)/giu)].map(x=>x[1].trim());
 const codes=[...text.matchAll(/\b[A-Z]\d{2}(?:\.\d{1,3})?\b/g)].map(x=>x[0]);
 return [...new Set([...labelled,...codes])].filter(x=>x.length>0&&x.length<=120).slice(0,20);
}
