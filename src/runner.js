// Private local stdio entry point used only by the registered NAT workflow.
import { runInvestigation } from './agent.js';
import { Nvidia } from './providers.js';
let data='';for await(const chunk of process.stdin){data+=chunk; if(data.length>1000000)throw Error('RUNNER_INPUT_LIMIT');}
const input=JSON.parse(data);
try{const result=await runInvestigation({...input,nim:new Nvidia(),onEvent:(event,value)=>process.stderr.write(JSON.stringify({event,data:value})+'\n')});process.stdout.write(JSON.stringify(result));}
catch(error){process.stderr.write(JSON.stringify({error:error.message})+'\n');process.exitCode=1;}
