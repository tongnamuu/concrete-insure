import { z } from 'zod';
export class AppError extends Error { constructor(code,status=400){super(code);this.status=status;} }
export function ensure(ok,code,status=400){if(!ok)throw new AppError(code,status);}
export const termSchema=z.string().min(1).max(120).refine(x=>x.trim().length>0);
export const querySchema=z.object({query:z.string().max(2000).default(''),description:z.string().max(4000).default(''),confirmedTerms:z.array(termSchema).max(20).default([]),drugIds:z.array(z.string().regex(/^\d{5,20}$/)).max(5).default([]),cloudConsent:z.boolean().default(false),translation:z.boolean().default(false)}).strict().refine(v=>v.query.trim().length>0||v.description.trim().length>0,{message:'Question or description is required'});
export const actionSchema=z.discriminatedUnion('action',[
 z.object({action:z.literal('search'),ids:z.array(z.number().int().nonnegative()).min(1).max(10)}).strict(),
 z.object({action:z.literal('finish')}).strict()
]);
// Filter conversational scaffolding, not medical facts. Explicit confirmed facts bypass this filter.
const conversationalWords=new Set(['약관','보험약관','보험금','보험','청구','지급','보장','대상','해당','사안','경우','내용','관련','관한','대해','대해서','여기','거기','이것','그것','이거','그거','지금','이번','다시','좀','더','또','혹시','분명','실제','실제로','저','제가','저는','나는','내','나','우리','조카','아이','것','건','수','때','처방','확인','검색','검토','질문','설명','알려','보여','찾아','있음','없음']);
const conversationalPhrase=/^(?:(?:다시)?(?:확인|검색|검토|설명|알려|보여|찾아)(?:해|해줘|해주세요|해주세|해주실래요|해줄래|해줄래요|해봐|해봐줘|해봐주세요|주세요|줘|주세|줄래|줄래요|봐|봐줘)?|(?:처방)?받(?:았|았습니다|았어요|았는데|았다고|은|은데|아서|아|고|았다|았어)|(?:있|없|맞|아니|되|안되|했|그랬|몰랐)(?:어|어요|습니다|는데|다고|나요|나|니|는|을텐데|을|음|다|죠|잖아|잖아요)?|(?:해당|관련)(?:하는|된|되는|한다|합니다|한다고)?|(?:걸렸|앓았)(?:어|어요|습니다|는데|다고|다)?|(?:해|해주세요|해야|될|인지|인가요|입니다|이에요|예요|텐데|같아요|같은데|부탁해|부탁해요|부탁드립니다))$/u;
export function isConversationalTerm(term){return conversationalWords.has(term)||conversationalPhrase.test(term);}
export function literalTerms(query,confirmed=[]){
 // Extract unchanged substrings only. No medicine-to-disease/ingredient expansion.
 const common=['독감','인플루엔자'];
 const tokens=query.match(/[\p{L}\p{N}][\p{L}\p{N}._-]*/gu)||[];
 const extracted=tokens.map(token=>token.replace(/[._-]+$/u,'')).filter(token=>!isConversationalTerm(token)).map(token=>token.replace(/(?:걸렸습니다|걸렸어요|걸렸는데|걸렸다고|걸렸어|관련된|관련|찾아줘|알려줘|보여줘|입니다|인가요|이네요|이야|했어요|이에요|으로는|에서는|에게는|에는|에서|으로|에게|이랑|하고|까지|부터|처럼|보다|이라면|이라서|라고|은요|는요|을|를|은|는|이|가|에|도)$/u,''));
 const derived=[...common.filter(term=>query.includes(term)),...extracted].filter(term=>term.length>=2&&term.length<=120&&!isConversationalTerm(term)&&query.includes(term));
 return [...new Set([...confirmed,...derived])].filter(term=>term.trim().length>0&&term.length<=120).slice(0,25);
}
export function groundedTerms(raw,query,confirmed=[],description=''){
 const v=z.object({terms:z.array(termSchema).max(25)}).strict().parse(JSON.parse(raw));
 ensure(v.terms.every(t=>query.includes(t)||description.includes(t)||confirmed.includes(t)),'UNGROUNDED_TERM');return v.terms;
}
export const NOTICE='보장 항목 확인은 약관의 지급사유와 관련 표현을 찾은 결과입니다. 실제 보장은 가입 특약·진단·처방 내용과 지급 조건을 확인해야 합니다. 검색 결과 없음은 보장 제외를 뜻하지 않습니다.';
