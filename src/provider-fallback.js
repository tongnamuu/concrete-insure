import {runInvestigation} from './agent.js';
const recoverable=new Set(['NIM_TIMEOUT','NIM_UNAVAILABLE','NIM_SERVICE_UNAVAILABLE','NIM_MODEL_UNAVAILABLE','NIM_AUTH_FAILED','NIM_RATE_LIMIT','NIM_INVALID_JSON','NIM_INCOMPLETE_RESPONSE','NIM_INVALID_RESPONSE','NIM_INVALID_TOOL_CALL','NIM_STOP_WITHOUT_SEARCH','REPEATED_TOOL_CALL','AGENT_STEP_LIMIT','UNSUPPORTED_TOOL','INVALID_TOOL_ARGUMENTS']);
// This runs after the API's explicit cloud-consent guard. It never adds external calls.
// Provider outages must not masquerade as either no evidence or successful model reasoning.
export async function withProviderFallback(input,primary,local=runInvestigation){
 try{return await primary(input);}catch(error){
  if(!recoverable.has(error.message)||input.signal?.aborted)throw error;
  input.onEvent?.('stage_started',{stage:'local_recovery',message:'NVIDIA 응답을 받지 못해 로컬에서 검증된 근거를 찾습니다.'});
  const result=await local({...input,request:{...input.request,cloudConsent:false,translation:false},nim:{enabled:false}});
  return {...result,mode:'local',warnings:[error.message]};
 }
}
