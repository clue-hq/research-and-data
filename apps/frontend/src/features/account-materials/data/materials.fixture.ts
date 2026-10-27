import { AccountSchema, type Account } from "@/features/accounts/model/account";
import { selectedGift, StateSchema, type DirectMailState } from "@/features/direct-mail/model/direct-mail";
import { WorkspaceSchema, type WorkspaceState } from "@/features/orchestration/model/workspace";

/** Additive V2 demo migration. Snowflake is an existing target account; all people/research below are fictional. */
export function withMaterialsWorkspace(state:WorkspaceState):WorkspaceState {
 if (state.accounts.some(a=>a.id==="snowflake")) return state;
 const next=structuredClone(state), template=next.accounts[0];
 next.accounts.unshift({...template,id:"snowflake",name:"Snowflake",initials:"S",revision:1,ownerId:"alex",senderId:"alex",contactId:"snowflake-morgan",contact:"Morgan Lee",role:"Field Marketing Lead",mailerId:"mailer-snowflake-morgan",industry:"Data infrastructure",
  insight:"Connect field events to account conversations",evidence:"Demo brief: a regional workshop program needs a consistent account follow-up.",source:"Illustrative research brief · fictional",rationale:"Morgan receives a practical workshop gift; Taylor receives an account-planning gift. Each has a separate note and landing page.",committee:[{name:"Morgan Lee",role:"Champion · Field marketing",status:"Gift ready for review"},{name:"Taylor Reed",role:"Evaluator · Revenue operations",status:"Delivery in progress"}]});
 const page=next.artifacts.find(a=>a.kind==="page")!;
 for (const [key,name,headline] of [["morgan","Morgan","Turn a workshop conversation into an account plan."],["taylor","Taylor","Give every account conversation a clear next step."]]) next.artifacts.push({...page,id:`page-snowflake-${key}`,accountId:"snowflake",mailerId:`mailer-snowflake-${key}`,title:`${name} · Workshop follow-up`,headline,body:`${name}, a small gift for your next planning session. Let's use one target account to explore how research, relevant content and sales follow-up can work together.`,sectionTitle:"Start with one account.",sectionBody:"Bring an account to a short working session. We’ll map the people, the evidence and a useful reason to reach out.",cta:"Book a working session with Alex"});
 next.artifacts.push({...page,id:"ad-snowflake",accountId:"snowflake",mailerId:null,kind:"ad",title:"Snowflake · Account campaign",headline:"Good account conversations start with context.",body:"Give marketing and sales a shared account brief. Turn one relevant insight into a conversation worth having.",cta:"Explore the account approach",status:"draft"});
 return WorkspaceSchema.parse(next);
}
export function withMaterialsMail(state:DirectMailState):DirectMailState {
 if (state.mailers.some(m=>m.id==="mailer-snowflake-morgan")) {
  // Repair only the exact unedited Taylor sample shipped during this preview.
  // User drafts/approvals and any changed sample text remain untouched.
  const oldNote="Taylor, a notebook for the ideas that deserve a follow-up. I thought it could be useful for your next account planning session. Would love to compare notes.";
  const sample=state.mailers.find(m=>m.id==="mailer-snowflake-taylor");
  if(sample?.note!==oldNote || sample.approval?.note!==oldNote)return state;
  const next=structuredClone(state),taylor=next.mailers.find(m=>m.id===sample.id)!;
  taylor.note=`Taylor, a ${taylor.approval!.gift.name.toLowerCase()} for your next planning session. A small thank-you for making space for a thoughtful account conversation. Would love to compare notes.`;
  taylor.approval!.note=taylor.note;
  return StateSchema.parse(next);
 }
 const next=structuredClone(state), review=next.mailers.find(m=>m.id==="mailer-avery")!;
 const tracking=next.mailers.find(m=>m.stage==="shipped" || m.stage==="delivered" || m.stage==="preparing") ?? next.mailers.find(m=>m.approval);
 for (const [key,name,role] of [["morgan","Morgan Lee","Field Marketing Lead"],["taylor","Taylor Reed","Revenue Operations Lead"]]) {
  const m=structuredClone(key==="taylor" && tracking ? tracking : review);
  m.id=`mailer-snowflake-${key}`;m.accountId="snowflake";m.contactId=`snowflake-${key}`;m.revision=1;
  m.recipient={name,role,company:"Snowflake",initials:name.split(" ").map(n=>n[0]).join("")};
  m.address={...m.address,name,company:"Snowflake"};m.addressConfirmed=true;
  m.insight={title:key==="morgan"?"Make the next workshop useful beyond the room":"Keep the account plan close to the conversation",detail:"Illustrative scenario for the walkthrough. These contacts and their research are fictional.",source:"Demo account brief",date:"Oct 26, 2026",excerpt:"The example team wants field-event conversations to inform a clear account follow-up."};
  m.note=`${name.split(" ")[0]}, a ${selectedGift(m)!.name.toLowerCase()} for your next planning session. A small thank-you for making space for a thoughtful account conversation. Would love to compare notes.`;
  m.signature="Alex Rivera\nClue";m.sourceLabel="Fictional recipient and research for this preview";
  m.assets=[];m.qr={destinationUrl:null,destinationStatus:"draft",printedUrl:null,verifiedAt:null};
  m.proposalRequest=null;m.exception=null;
  if (key==="morgan") {m.stage="needs_review";m.approval=null;m.priorApprovals=[];m.reviewedRevision=null;m.inbound=null;m.outbound=null;m.events=[];m.photos=[];}
  else if(m.approval) {m.approval={...m.approval,revision:1,note:m.note,signature:m.signature,address:m.address};}
  next.mailers.unshift(m);
 }
 return StateSchema.parse(next);
}
export function materialAccountRows(base:Account[],workspace:WorkspaceState):Account[] {
 const result=new Map(base.map(a=>[a.id,a]));
 for(const a of workspace.accounts) {
  const old=result.get(a.id), project={id:workspace.project.id,name:workspace.project.name};
  result.set(a.id,AccountSchema.parse(old ? {...old,...(a.id==="snowflake"?{industryLabels:[a.industry],owner:workspace.people.find(p=>p.id===a.ownerId),fitScore:null,overallFit:null,revenueBand:"—",employeeBand:"—",researchStatusLabel:"Demo research"}:{}),projects:[...old.projects.filter(p=>p.id!==project.id),project]} : {
   id:a.id,name:a.name,logoPath:null,websiteUrl:null,researchStatus:a.researchStatus==="ready"?"completed":"not_started",researchStatusLabel:a.researchStatus==="ready"?"Demo research":"Not started",fitScore:a.fit,overallFit:a.fit===null?null:"High",revenueBand:"—",employeeBand:"—",locationCount:0,locationsLabel:"—",industryLabels:[a.industry],owner:workspace.people.find(p=>p.id===a.ownerId),projects:[project],primaryProjectId:project.id,
  }));
 }
 return [...result.values()].sort((a,b)=>a.id==="snowflake"?-1:b.id==="snowflake"?1:0);
}
