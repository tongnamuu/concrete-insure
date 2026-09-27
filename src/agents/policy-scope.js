import {pdfOperation} from '../pdf.js';
import {ensure} from '../core.js';
import {verifyDrugReferences} from './drug-references.js';
const normalize=text=>text.replace(/[\s\p{C}]/gu,'');
const ambiguous=text=>/(?:제외|인정하지|해당하지|지급하지|보장하지|보상하지)/u.test(normalize(text));
const permitted=new Set(['payment','definition','exclusion','claim']);
const unique=values=>[...new Set(values)];

/** Identifies policy benefits and literal/product-source links; never evaluates patient eligibility. */
export function describePolicyScope({sections=[],references=[],terms=[],truncated=false}){
 verifyDrugReferences(references);
 const items=[];
 for(const section of sections){
  const clauses=section.clauses.filter(c=>permitted.has(c.kind)&&c.hits.length);
  const payment=clauses.filter(c=>c.kind==='payment').flatMap(c=>c.hits);
  // A heading alone cannot establish a benefit; require actual affirmative payment wording.
  const body=payment.map(h=>h.quote).join('');
  if(!/(?:지급합니다|지급합니|보상합니다|보상합니)/u.test(normalize(body)))continue;
  const definition=clauses.filter(c=>c.kind==='definition').flatMap(c=>c.hits);
  const positive=[...payment,...definition].filter(h=>!ambiguous(h.quote));
  const links=[];
  for(const reference of references){
   const brandHits=positive.filter(h=>reference.aliases.some(alias=>h.quote.includes(alias)));
   if(brandHits.length){links.push({kind:'direct_brand',referenceId:reference.id,label:reference.brand,term:reference.brand,sourceIds:unique(brandHits.map(h=>h.id))});continue;}
   // Ingredient equality is evidence of a related policy entry, not clinical or contractual equivalence.
   const contextTerms=reference.facts.filter(f=>f.priority==='context').flatMap(f=>f.terms);
   if(!contextTerms.some(t=>section.title.quote.includes(t)||payment.some(h=>h.quote.includes(t))))continue;
   for(const fact of reference.facts.filter(f=>f.priority==='specific'))for(const term of fact.terms){
    const matched=definition.filter(h=>h.quote.includes(term)&&!ambiguous(h.quote));
    if(matched.length)links.push({kind:'ingredient',referenceId:reference.id,label:reference.brand,term,sourceIds:unique(matched.map(h=>h.id))});
   }
  }
  if(!links.length){
   // Explicit terms may identify a named benefit. Product indications are not patient assertions.
   const supplied=new Set(references.flatMap(r=>r.facts.flatMap(f=>f.terms)));
   for(const term of terms.filter(t=>!supplied.has(t))){
    const matched=payment.filter(h=>h.quote.includes(term)&&!ambiguous(h.quote));
    if(section.title.quote.includes(term)&&matched.length)links.push({kind:'explicit_term',referenceId:null,label:term,term,sourceIds:unique(matched.map(h=>h.id))});
   }
  }
  if(!links.length)continue;
  const sourceIds=kind=>unique(clauses.filter(c=>c.kind===kind).flatMap(c=>c.hits.map(h=>h.id)));
  const allText=clauses.flatMap(c=>c.hits).map(h=>h.quote).join('');
  const checks=[{kind:'enrollment',sourceIds:[section.title.id],status:'needs_confirmation'}];
  const add=(kind,pattern)=>{const ids=unique(clauses.flatMap(c=>c.hits).filter(h=>pattern.test(normalize(h.quote))).map(h=>h.id));if(ids.length)checks.push({kind,sourceIds:ids,status:'needs_confirmation'});};
  add('period',/보험기간|보장개시|면책기간/u);add('diagnosis',/진단/u);add('treatment',/처방|치료|수술|입원/u);add('limit',/연간|회한|횟수|한도|최초/u);add('approval_date',/허가|진단당시/u);
  checks.push({kind:'exclusion',sourceIds:sourceIds('exclusion'),status:'needs_confirmation'});
  if(/보통약관|별표|준용/u.test(allText))checks.push({kind:'cross_reference',sourceIds:unique(clauses.flatMap(c=>c.hits).filter(h=>/보통약관|별표|준용/u.test(h.quote)).map(h=>h.id)),status:'needs_confirmation'});
  items.push({id:section.id,titleId:section.title.id,links,clauses:clauses.map(c=>({kind:c.kind,headingId:c.heading.id,sourceIds:unique(c.hits.map(h=>h.id))})),checks,truncated:!!section.truncated});
 }
 return {status:items.length?'identified':'unresolved',scope:'policy_benefit_only',items,truncated:!!truncated};
}

export async function inspectPolicyScope({document,hits,terms,references,signal},operation=pdfOperation){
 const anchors=[];const seen=new Set();
 for(const h of hits){const key=`${h.page}:${h.sourceStart}:${h.sourceEnd}`;if(!seen.has(key)&&/[^\s\p{C}]/u.test(h.quote)){anchors.push(h);seen.add(key);}if(anchors.length===12)break;}
 if(!anchors.length)return {coverage:describePolicyScope({}),hits:[]};
 const result=await operation({op:'sections',pdf:document.pdf,index:document.index,anchors},{signal});
 ensure(Array.isArray(result.sections),'INVALID_POLICY_SECTIONS');
 const coverage=describePolicyScope({...result,references,terms});
 const included=new Set(coverage.items.map(s=>s.id));
 const sourceHits=result.sections.filter(s=>included.has(s.id)).flatMap(s=>[s.title,...s.clauses.flatMap(c=>c.hits)]);
 return {coverage,hits:sourceHits};
}
