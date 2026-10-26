import { PROJECT_ID, WorkspaceSchema, type AccountPlan, type WorkspaceState } from "../model/workspace";

/** Six curated fictional accounts plus a deterministic scale fixture. No research is invented for additional rows. */
export function createWorkspaceFixture(count = 1000): WorkspaceState {
  const accounts: AccountPlan[] = [
    { id: "account-northstar-systems", revision: 1, name: "Northstar Systems", initials: "NS", industry: "Enterprise software", ownerId: "alex", senderId: "alex", territory: "West", assignmentReason: "West territory · existing account owner", approach: "Gift-led", researchStatus: "ready", fit: 94, insight: "A new field-marketing program needs a closer connection to sales.", evidence: "The team is planning regional customer workshops and wants the findings to inform its named-account campaigns.", source: "Account research brief · fictional example", observedAt: "Oct 20", rationale: "A useful workshop notebook and a focused account brief make a relevant opening for Avery. Follow up with a practical way to turn workshop notes into outreach.", mailerId: "mailer-avery", contactId: "contact-avery", contact: "Avery Stone", role: "VP of Marketing", committee: [{ name: "Avery Stone", role: "Champion · Marketing", status: "Ready for outreach" }, { name: "Sam Rivera", role: "Economic buyer · Revenue", status: "Research available" }, { name: "Not identified", role: "Technical evaluator", status: "Research needed" }], campaignIds: ["campaign-gifts"], audienceSize: 180 },
    { id: "account-harbor-labs", revision: 1, name: "Harbor Labs", initials: "HL", industry: "Data infrastructure", ownerId: "jamie", senderId: "jamie", territory: "East", assignmentReason: "East territory · existing account owner", approach: "Gift-led", researchStatus: "ready", fit: 91, insight: "Customer observations are scattered across three regional teams.", evidence: "The growth team is consolidating customer learnings ahead of its next planning cycle.", source: "Account research brief · fictional example", observedAt: "Oct 21", rationale: "The note opens a conversation about carrying customer context into every campaign. The package is being inspected at Clue.", mailerId: "mailer-casey", contactId: "contact-casey", contact: "Casey Chen", role: "Marketing Lead", committee: [{ name: "Casey Chen", role: "Champion · Marketing", status: "Gift in preparation" }, { name: "Jordan Lee", role: "Sponsor · Growth", status: "Research available" }], campaignIds: ["campaign-gifts"], audienceSize: 120 },
    { id: "account-fieldwork", revision: 1, name: "Fieldwork", initials: "F", industry: "Customer experience", ownerId: "alex", senderId: "alex", territory: "West", assignmentReason: "West territory · existing account owner", approach: "Gift-led", researchStatus: "ready", fit: 89, insight: "Small customer workshops are becoming a repeatable growth motion.", evidence: "Marketing and field teams are organizing an in-person planning workshop. A receiving address has not been confirmed.", source: "Account research brief · fictional example", observedAt: "Oct 20", rationale: "Prepare the gift and note while Alex confirms a receiving address. Hold purchase approval until the delivery details are complete.", mailerId: "mailer-priya", contactId: "contact-priya", contact: "Priya Shah", role: "Director of Marketing", committee: [{ name: "Priya Shah", role: "Champion · Marketing", status: "Address needed" }, { name: "Taylor Brooks", role: "Influencer · Partnerships", status: "Research available" }], campaignIds: ["campaign-gifts"], audienceSize: 85 },
    { id: "account-linden-technologies", revision: 1, name: "Linden Technologies", initials: "LT", industry: "Business intelligence", ownerId: "jamie", senderId: "jamie", territory: "East", assignmentReason: "Existing relationship · Jamie Park", approach: "Opportunity support", researchStatus: "ready", fit: 96, insight: "The team wants a concrete account example for its planning session.", evidence: "Riley replied asking for an example to share with the revenue team. ", source: "Sample recipient reply", observedAt: "Oct 25", rationale: "Jamie should respond with a relevant example and clarify who should join the discussion. ", mailerId: "mailer-riley", contactId: "contact-riley", contact: "Riley Parker", role: "Head of Marketing", committee: [{ name: "Riley Parker", role: "Champion · Marketing", status: "Replied" }, { name: "Morgan Ellis", role: "Sponsor · Growth", status: "Suggested participant" }], campaignIds: ["campaign-gifts"], audienceSize: 340 },
    { id: "account-meridian", revision: 1, name: "Meridian", initials: "M", industry: "Financial software", ownerId: "jamie", senderId: "jamie", territory: "East", assignmentReason: "East territory · named-account assignment", approach: "Content-led", researchStatus: "ready", fit: 92, insight: "A new enterprise segment calls for more specific customer proof.", evidence: "The team is testing enterprise messaging and has asked for examples that connect research to the buying committee.", source: "Account research brief · fictional example", observedAt: "Oct 22", rationale: "Lead with a short, useful account example. There is no relevant gifting reason yet, so this approach starts with an account brief.", mailerId: null, contactId: "contact-drew", contact: "Drew Hayes", role: "VP of Growth", committee: [{ name: "Drew Hayes", role: "Champion · Growth", status: "Research available" }, { name: "Not identified", role: "Economic buyer", status: "Research needed" }], campaignIds: [], audienceSize: 260 },
    { id: "account-atlas", revision: 1, name: "Atlas Cloud", initials: "AC", industry: "Cloud infrastructure", ownerId: "alex", senderId: "alex", territory: "West", assignmentReason: "West territory · named-account assignment", approach: "Content-led", researchStatus: "ready", fit: 90, insight: "The buying group needs a shared story across marketing and engineering.", evidence: "The account brief identifies a cross-functional evaluation involving demand generation and technical stakeholders.", source: "Account research brief · fictional example", observedAt: "Oct 23", rationale: "Use a relevant technical proof page and direct outreach. An account-focused ad can reinforce the business problem if its audience qualifies.", mailerId: null, contactId: "contact-devon", contact: "Devon Reed", role: "Director of Demand Generation", committee: [{ name: "Devon Reed", role: "Champion · Marketing", status: "Research available" }, { name: "Not identified", role: "Technical evaluator", status: "Research needed" }], campaignIds: ["campaign-awareness"], audienceSize: 2400 },
  ];

  const pageCopy: Record<string, { headline:string; body:string; sectionTitle:string; sectionBody:string }> = {
    "account-northstar-systems": {
      headline:"Put your field insights to work.",
      body:"Avery, the best part of a customer workshop often lives in someone’s notebook. Here’s a way to carry those observations into your next named-account campaign.",
      sectionTitle:"One workshop. A useful next conversation.",
      sectionBody:"Start with a question your customer raised. Connect it to a specific account, prepare a relevant example, and give the account owner the context to follow up. We can walk through one together.",
    },
    "account-harbor-labs": {
      headline:"Keep the customer context together.",
      body:"Casey, your regional teams hear different parts of the customer story. This is an invitation to bring those observations into one account brief for your next planning cycle.",
      sectionTitle:"Start with a single account.",
      sectionBody:"Bring a customer observation from each region. We’ll help turn the shared context into a brief your growth team can use to plan a more relevant conversation.",
    },
    "account-fieldwork": {
      headline:"Make the next workshop count.",
      body:"Priya, a notebook for the ideas that deserve a follow-up. Here’s a practical way to take one conversation from your next customer workshop into an account campaign.",
      sectionTitle:"From a good question to a useful follow-up.",
      sectionBody:"Choose one question from the workshop, identify the account and person it matters to, and prepare a specific example. We can build that first account brief together.",
    },
    "account-linden-technologies": {
      headline:"An account example for your next planning session.",
      body:"Riley, here’s a starting point to share with your revenue team: one account, the research behind it, and a concrete reason to begin a conversation.",
      sectionTitle:"Review the reasoning together.",
      sectionBody:"We can walk through the account finding, the people involved and the message it supports. Bring a target account to the discussion and we’ll use it as the working example.",
    },
    "account-meridian": {
      headline:"Give your enterprise story a specific account.",
      body:"Drew, a new segment needs more than a new headline. Let’s connect one of your customer examples to the people evaluating a solution at a target account.",
      sectionTitle:"A brief your buying team can use.",
      sectionBody:"We’ll start with a relevant customer outcome, map it to the account’s current priorities, and prepare an example that marketing and sales can review together.",
    },
    "account-atlas": {
      headline:"One account story. Room for every evaluator.",
      body:"Devon, marketing and engineering bring different questions to an evaluation. An account brief can give both teams a common starting point without losing the technical detail.",
      sectionTitle:"Connect the business case to the technical proof.",
      sectionBody:"Choose an account and a relevant technical example. We’ll show how the same evidence can support a business conversation and a deeper discussion with the engineering team.",
    },
  };
  const curated = [...accounts];
  const prefixes = ["Alder","Birch","Cedar","Elm","Fir","Grove","Hawthorn","Juniper","Maple","Oak","Pine","Willow","Acorn","Beacon","Cove","Delta","Evergreen","Flint","Granite","Horizon","Indigo","Jasper","Keystone","Larch","Meadow","Noble","Orchard","Prairie","Quartz","Ridge"];
  const suffixes = ["Analytics","Systems","Software","Cloud","Data","Networks","Partners","Digital","Labs","Technologies","Works","Group","Solutions","Research","Computing","Platforms","Services","Studio","Operations","Ventures","Industries","Insights","Collective","Tools","Logic","Intelligence","Products","Supply","Development","Exchange","Commerce","Infrastructure","Engineering","Applications"];
  for (let index = 6; index < Math.min(1000,Math.max(6,count)); index++) {
    const n = index - 6, prefix = prefixes[n % prefixes.length], suffix = suffixes[Math.floor(n / prefixes.length)];
    const ownerId = index % 2 ? "jamie" : "alex";
    accounts.push({
      id:`scale-account-${index + 1}`, revision:1, name:`${prefix} ${suffix}`, initials:prefix[0]+suffix[0], industry:["Software","Infrastructure","Business services"][index % 3],
      ownerId,senderId:ownerId,territory:index % 2 ? "East" : "West",assignmentReason:"Territory assignment",
      approach:"Content-led",fit:null,researchStatus:"pending",insight:"",evidence:"",source:"",observedAt:"",rationale:"",
      mailerId:null,contactId:`scale-contact-${index + 1}`,contact:"",role:"",committee:[],campaignIds:[],audienceSize:0,
    });
  }
  return WorkspaceSchema.parse({
    version:4,
    project:{ id:PROJECT_ID,name:"10x revenue campaign",goal:"Enterprise account outreach",ownerId:"maya",budget:"$50–100 per gift" },
    people:[
      { id:"maya",name:"Maya Chen",initials:"MC",role:"ABM lead",territory:"All territories",canOwn:false },
      { id:"alex",name:"Alex Rivera",initials:"AR",role:"Account executive",territory:"West",canOwn:true },
      { id:"jamie",name:"Jamie Park",initials:"JP",role:"Account executive",territory:"East",canOwn:true },
    ],accounts,
    campaigns:[
      { id:"campaign-gifts",name:"Direct mail",channel:"Direct Mail",ownerId:"maya",purpose:"Personalized gifts for selected accounts" },
      { id:"campaign-awareness",name:"Account advertising",channel:"LinkedIn",ownerId:"maya",purpose:"Account-specific creative" },
    ],
    artifacts:curated.flatMap((a) => [
      { id:`page-${a.id}`,accountId:a.id,kind:"page",title:`${a.name} · Account brief`,version:1,status:"review",...pageCopy[a.id],cta:`Talk with ${a.senderId === "alex" ? "Alex" : "Jamie"}`,mailerId:null },
      ...(a.mailerId ? [{ id:`note-${a.id}`,accountId:a.id,kind:"note",title:`${a.contact.split(" ")[0]} · Handwritten note`,version:1,status:"review",headline:"",body:"",cta:"Review note",mailerId:a.mailerId }] : []),
      ...(["account-northstar-systems","account-atlas"].includes(a.id) ? [{ id:`ad-${a.id}`,accountId:a.id,kind:"ad",title:`${a.name} · LinkedIn ad`,version:1,status:"draft",headline:pageCopy[a.id].headline,body:pageCopy[a.id].body,cta:"View account brief",mailerId:null }] : []),
    ]),
  });
}

/** Preserve earlier account assignments while retiring V2's email records. */
export function parseWorkspace(value:unknown):WorkspaceState {
  const parsed = WorkspaceSchema.safeParse(value);
  if (parsed.success) return parsed.data;
  if (!value || typeof value !== "object" || !("version" in value) || ![2,3].includes(Number(value.version))) return WorkspaceSchema.parse(value);
  const next = createWorkspaceFixture();
  const legacy = value as { accounts?: { id:string;ownerId:string;revision:number;assignmentReason:string }[] };
  for (const old of legacy.accounts ?? []) {
    const current = next.accounts.find((a) => a.id === old.id);
    if (current && next.people.some((p) => p.id === old.ownerId && p.canOwn)) {
      current.ownerId = old.ownerId; current.revision = old.revision; current.assignmentReason = old.assignmentReason;
    }
  }
  return WorkspaceSchema.parse(next);
}
