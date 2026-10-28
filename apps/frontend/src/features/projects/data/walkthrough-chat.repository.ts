import type { ChatRepositories } from './chat-repositories';
import { FIXTURE_THREAD_ID, fixtureMessages } from './chat.fixture';
import { ChatMessageListResponseSchema } from '../model/chat-message';
/** An explicit scripted scenario; it never pretends to execute an agent turn. */
export function withWalkthroughChat(base:ChatRepositories):ChatRepositories {
 return {...base,messages:{async list(input){
  if(input.threadId!==FIXTURE_THREAD_ID)return base.messages.list(input);
  return ChatMessageListResponseSchema.parse({data:fixtureMessages.map((m,i)=>({...m,refs:[],body:input.includeBodies===false?null:i===0?'Use the completed account research to prepare direct mail for the field conversations campaign. Start with Snowflake and show me Morgan and Taylor together.':'The sample research and buying committee are ready. Morgan’s outreach uses a practical workshop gift and a short follow-up brief. Taylor’s outreach focuses on the handoff to the account owner.\n\nEach recipient has three gift options, a handwritten note and a personal landing page. Review the complete set and itemized cost before approving the send. Taylor’s sample shipment also shows the later tracking steps.\n\nOpen Snowflake from the target-account table or the linked materials below. The same review works across all 500 accounts.\n\n*Illustrative walkthrough: no research jobs, orders or publishing run from this chat.*'})),meta:{}});
 }},gates:{async list(input){return input.threadId===FIXTURE_THREAD_ID?{available:true,gates:[],reason:null}:base.gates.list(input);}},turns:{...base.turns,async list(input){const result=await base.turns.list(input);return input.threadId===FIXTURE_THREAD_ID?{...result,turns:[],threadRunning:false}:result;},async submit(input){if(input.threadId===FIXTURE_THREAD_ID)throw new Error('This walkthrough chat is illustrative. Review and edit the prepared outreach in Gallery; live agent execution is not connected.');return base.turns.submit(input);}}};
}
