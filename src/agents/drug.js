import { ensure } from '../core.js';
/** Server-selected MFDS records -> literal ingredient terms; never diagnoses. */
export function identifyDrugs(products=[]) {
 ensure(Array.isArray(products)&&products.length<=5,'INVALID_PRODUCTS');
 for(const p of products) ensure(/^\d{5,20}$/.test(p.id)&&typeof p.name==='string'&&typeof p.ingredients==='string'&&p.url?.startsWith('https://nedrug.mfds.go.kr/'),'UNVERIFIED_PRODUCT');
 const terms=products.flatMap(p=>p.ingredients.split(/[|;,\n]/u).map(x=>x.trim()).filter(x=>x.length>1&&x.length<=120));
 return {mappings:products,terms:[...new Set(terms)]};
}
