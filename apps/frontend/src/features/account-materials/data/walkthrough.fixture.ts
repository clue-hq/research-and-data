import { createWorkspaceFixture } from "@/features/orchestration/data/workspace.fixture";
import type { AccountPlan, WorkspaceState } from "@/features/orchestration/model/workspace";
import { estimate, StateSchema, type DirectMailState, type Mailer, type Stage } from "@/features/direct-mail/model/direct-mail";
import type { OutreachPage } from "@/features/direct-mail/model/outreach-page";

import { WALKTHROUGH_CAMPAIGN, WALKTHROUGH_NAME } from "../model/outreach";
export { WALKTHROUGH_CAMPAIGN, WALKTHROUGH_NAME } from "../model/outreach";
const date="2026-10-27T16:00:00Z";
/** Synthetic scenario only. No external research, orders or publishing are performed. */
export function walkthroughAccounts():AccountPlan[] {
 const base=createWorkspaceFixture(505);
 const snowflake={...base.accounts[0],id:"snowflake",name:"Snowflake",initials:"S",industry:"Data infrastructure",ownerId:"alex",senderId:"alex",territory:"West"};
 return [snowflake,...base.accounts.filter(a=>a.id.startsWith("scale-account-")).slice(0,499)].map((a,index)=>({...a,
  researchStatus:"ready",campaignIds:[...a.campaignIds,WALKTHROUGH_CAMPAIGN],
  contactId:index===0?"snowflake-morgan":`${a.id}-marketing`,contact:index===0?"Morgan Lee":`Jordan ${index+1}`,role:"Field Marketing Lead",mailerId:`walkthrough-${a.id}-morgan`,
  insight:"Turn workshop conversations into useful account follow-up",evidence:"Illustrative brief: regional workshops generate customer questions, but the handoff to account owners is inconsistent.",source:"Sample research brief · fictional",observedAt:"Oct 27, 2026",
  rationale:"A field notebook supports the workshop; a personal account brief gives the recipient a useful reason to meet their account owner.",
  committee:[{name:index===0?"Morgan Lee":`Jordan ${index+1}`,role:"Champion · Field marketing",status:"Research complete · example"},{name:index===0?"Taylor Reed":`Casey ${index+1}`,role:"Evaluator · Revenue operations",status:"Research complete · example"}],
 }));
}
export function withWalkthroughWorkspace(state:WorkspaceState):WorkspaceState {
 if(state.campaigns.some(c=>c.id===WALKTHROUGH_CAMPAIGN))return state;
 const next=structuredClone(state),accounts=new Map(next.accounts.map(a=>[a.id,a]));
 for(const account of walkthroughAccounts())accounts.set(account.id,{...account,ownerId:accounts.get(account.id)?.ownerId??account.ownerId});
 next.accounts=[...accounts.values()];
 next.campaigns.push({id:WALKTHROUGH_CAMPAIGN,name:WALKTHROUGH_NAME,channel:"Direct Mail",ownerId:"maya",purpose:"Book account working sessions after regional workshops"});
 return next;
}
export function withWalkthroughMail(state:DirectMailState):DirectMailState {
 if(state.mailers.some(m=>m.campaignId===WALKTHROUGH_CAMPAIGN))return state;
 const next=structuredClone(state),template=state.mailers.find(m=>m.id==="mailer-avery")??state.mailers[0];
 const prepared:Mailer[]=[];const pages:OutreachPage[]=[];
 for(const [index,a] of walkthroughAccounts().entries())for(const [personIndex,key] of ["morgan","taylor"].entries()) {
  const m=structuredClone(template),name=a.committee[personIndex].name;
  m.id=`walkthrough-${a.id}-${key}`;m.accountId=a.id;m.contactId=index===0?`snowflake-${key}`:`${a.id}-${personIndex===0?"marketing":"operations"}`;
  m.campaignId=WALKTHROUGH_CAMPAIGN;m.campaign=WALKTHROUGH_NAME;m.pageId=`page-${m.id}`;m.revision=1;m.reviewedRevision=null;
  m.recipient={name,role:personIndex===0?"Field Marketing Lead":"Revenue Operations Lead",company:a.name,initials:name.split(" ").map(x=>x[0]).join("")};
  m.address={...m.address,name,company:a.name,line1:"100 Example Avenue",line2:"Suite 200"};m.addressConfirmed=true;
  m.signature=`${a.ownerId==="alex"?"Alex Rivera":"Jamie Park"}\nClue`;
  m.selectedGiftId=m.gifts[personIndex===0?0:1].id;
  m.note=personIndex===0?`Hi ${name.split(" ")[0]},\n\nA small thank-you for the conversations that continue after your next workshop. I'd love to compare one account's follow-up plan with you.\n\nThe card links to a short brief to start from.`:`Hi ${name.split(" ")[0]},\n\nA small thank-you for your perspective on the next planning session. I put together a short account brief on connecting workshop insights to the sales follow-up. I'd love your perspective.`;
  m.insight={title:personIndex===0?"The workshop is the start of the conversation":"Make the handoff useful to the account owner",detail:personIndex===0?"The sample research identifies a regional workshop program. A field notebook is useful in the room; a tailored follow-up brief carries the discussion into an account conversation.":"The sample buying committee places revenue operations alongside field marketing. The page focuses on ownership and the next action after an event.",source:"Illustrative account research brief",date:"Oct 27, 2026",excerpt:a.evidence};
  const stage:Stage=index===0?(personIndex===0?"needs_review":"shipped"):index%13===0?"attention":index%5===0?"delivered":index%5===1?"quality_check":index%5===2?"approved":"needs_review";
  m.stage=stage;m.budgetCents=12000;m.updatedAt=date;m.approval=null;m.priorApprovals=[];m.events=[];m.photos=[];m.inbound=null;m.outbound=null;m.assets=[];m.proposalRequest=null;m.exception=null;
  m.sourceLabel="Illustrative campaign · fictional people, research and delivery events";
  const approved=stage!=="needs_review"&&stage!=="attention",shipped=stage==="shipped"||stage==="delivered";
  const page:OutreachPage={id:m.pageId,projectId:m.projectId,accountId:a.id,contactId:m.contactId,mailerId:m.id,version:1,reviewedVersion:approved?1:null,title:`${name.split(" ")[0]} · Account working session`,headline:personIndex===0?"Good conversations deserve a useful follow-up.":"Give every account conversation a clear next step.",body:personIndex===0?`${name.split(" ")[0]}, your next workshop will surface questions worth following up on. Let's take one of those questions and turn it into a useful account conversation.`:`${name.split(" ")[0]}, a clear owner and a useful next action make the difference after a workshop. Let's review how one account's context can move from marketing to sales.`,cta:"Plan a 20-minute working session",publication:shipped?"published":"draft"};
  pages.push(page);
  m.deliveryEstimate=stage==="delivered"?"Delivered Oct 26":shipped?"Oct 29–30":"7–10 business days after approval";
  m.qr={destinationUrl:shipped?`https://pages.clue.example/${m.id}`:null,destinationStatus:shipped?"published":"draft",printedUrl:shipped?`https://go.clue.example/${m.id}`:null,verifiedAt:shipped?"2026-10-26T15:00:00Z":null};
  if(approved) {
   m.approval={revision:1,at:"2026-10-23T16:00:00Z",gift:structuredClone(m.gifts.find(g=>g.id===m.selectedGiftId)!),note:m.note,signature:m.signature,card:structuredClone(next.cards.find(c=>c.id===m.cardId)!),style:structuredClone(next.styles.find(s=>s.id===m.styleId)!),address:structuredClone(m.address),estimatedCents:estimate(m)!,budgetCents:m.budgetCents,page:structuredClone(page)};
   m.events.push({id:"approved",title:"Outreach approved",detail:"Gift, rendered note, page version and itemized cost approved.",at:"2026-10-23T16:00:00Z",kind:"standard"});
  }
  if(stage==="quality_check"||shipped) {
   m.inbound={carrier:"Merchant delivery",trackingNumber:`DEMO-IN-${index}-${personIndex}`,trackingUrl:null,expected:"Received Oct 26",status:"Received at Clue"};
   m.events.push({id:"received",title:"Received at Clue",detail:"Gift checked in; condition inspection completed.",at:"2026-10-26T13:00:00Z",kind:"standard"});
  }
  if(shipped) {
   m.outbound={carrier:"UPS · sample shipment",trackingNumber:`DEMO-OUT-${index}-${personIndex}`,trackingUrl:null,expected:stage==="delivered"?"Delivered Oct 26":"Oct 29–30",status:stage==="delivered"?"Delivered":"In transit"};
   m.photos=[{id:"package",url:"/direct-mail/package.svg",caption:"Prepared package · illustrative image",at:"2026-10-26T15:00:00Z"}];
   m.events.push({id:"quality",title:"Quality check passed",detail:"Gift inspected, card written, QR destination checked and package prepared.",at:"2026-10-26T15:00:00Z",kind:"standard"},{id:"shipped",title:stage==="delivered"?"Carrier delivery confirmed":"Handed to outbound carrier",detail:stage==="delivered"?"Delivery at the receiving address; personal receipt is unconfirmed.":"Next update will come from the outbound carrier.",at:"2026-10-26T18:00:00Z",kind:"standard"});
  }
  if(stage==="attention"){m.stage="needs_review";m.addressConfirmed=false;m.exception={title:"Receiving route needs confirmation",detail:"The agent needs a confirmed business receiving address before this send can proceed.",action:"address"};}
  prepared.push(m);
 }
 next.mailers=[...prepared,...next.mailers];next.pages=[...pages,...(next.pages??[])];
 return StateSchema.parse(next);
}
