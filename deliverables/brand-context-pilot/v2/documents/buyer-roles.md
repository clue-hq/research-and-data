Conduit’s site names the audience as hotel teams, serviced-apartment operators, and short-term rental managers, not a published buying committee. Named stories mostly put founders or CEOs on the commercial decision and guest-experience or communications leads on daily configuration. Titles below are observed in those pages or in industry copy; they are not a confirmed org chart. Pair this with [Customer evidence & usable proof](#knowledge/customer-evidence), [ICP · hotel operators](#knowledge/icp-hotels), and [ICP · vacation-rental operators](#knowledge/icp-rentals).

## Buying roles and title map

Committee labels are a working overlay. Only titles in the observed column appear in the supplied sources.

| Function | Observed titles | Remit / scope in sources | Product surface they actually used |
| --- | --- | --- | --- |
| Economic buyer | CEO (Haven, The Flex); Founder (Lauderdale, Cosmica, Bali Luxury Stays); Co-Founder (Bocobay, HomeHop) | Headcount, NOI or exit math, whether listing growth needs more support staff | Platform as a whole vs call center, VAs, or Intercom |
| Champion / process owner | Process and Communication Manager (Canbnb); Revenue & Guest Services (Cascadia); Global Head of Customer Experience (Wynwood); guest services manager (Haven) | Inbox design, knowledge, automation rate without dropping scores | [Inbox](#knowledge/product-inbox), [AI Agents](#knowledge/product-agents), [Workflows](#knowledge/product-workflows) |
| Operational user (can block) | Guest-services reps, VA teams, night shift, front-desk staff; remaining “conversational engineers” | Takeovers, teaching replies, owner/vendor threads | Handoffs, notes/tags, after-hours voice |
| Technical / build evaluator | The Flex: homegrown PMS, with communications AI bought separately; HomeHop: SuiteOP as an adjacent system; Easy BnB founder: abandoned in-house messaging AI (story on Bali Luxury Stays page) | Stack fit, knowledge quality, when writes are allowed | [Integrations & implementation readiness](#knowledge/integrations), [Developer platform & custom workflows](#knowledge/product-developers) |

Independent-hotel copy is a desk team covering calls after hours while people remain at the desk. Hotel-group copy is shared brand standards plus per-property policies. STR copy is per-listing knowledge and OTA inboxes. None of those pages maps to GM, cluster manager, or CISO as buyers. [Source](https://www.conduit.ai/industry/independent-hotels) [Source](https://www.conduit.ai/industry/hotel-groups) [Source](https://www.conduit.ai/industry/short-term-rentals)

A security evaluator is not named here. API/MCP is a workspace capability, not proof that engineering always sits on the committee. [Source](https://www.conduit.ai/developers)

### Roles to test during discovery

The following title hypotheses make the committee map actionable; they are suggested search roles, not confirmed Conduit buyers or required titles.

| Buying role | Titles to test | Decision and practical question |
| --- | --- | --- |
| Independent-hotel sponsor | Owner, general manager, operations director | Owns staffing and guest-service economics. Who can approve a change to night coverage and its budget? |
| Group-level sponsor | COO, VP/Director of Operations, guest-experience leader | Owns shared service standards and rollout. Is purchasing centralized, property-led, or franchise-controlled? |
| Operational champion | Front Office Manager, reservations lead, guest-services/CX manager | Owns queues, knowledge and escalation. Who can maintain policies and measure response quality after launch? |
| Technical evaluator | IT director, business-systems/PMS administrator, integration owner | Confirms reservation data, channel routing and permitted actions. Which connection path and write permissions are actually available? |
| Risk and commercial reviewers | Security/privacy reviewer, procurement or finance owner when required | Confirms guest-data handling, contract and usage economics. Who approves access, billing assumptions and vendor onboarding? |

Role seniority and property-versus-group remit are relevant professional demographics. Age, gender and personal income are not needed for these buying decisions. Validate the role map with the account instead of assuming that every company has every department.

## Priorities and desired results

| Observed role | Job in the stories | Result they cited | Proof they pointed at |
| --- | --- | --- | --- |
| Founder / CEO / owner | Stop linear hiring; raise NOI or EBITDA; absorb an acquisition | Automation %, support cost, listings per rep, modeled asset value | Lauderdale support $4,000→$600/mo and ≥$3,400/mo NOI; Haven’s support staffing need ~25 people → two per shift, alongside its no-AI-layoff pledge and staff retraining; HomeHop 40→108 listings without extra guest-support hires |
| CX / guest services lead | One inbox, faster resolution, multilingual quality, shift handoffs | Resolution time, communication score, AI/human indistinguishability | Wynwood 14–15 min → 3 min; Cascadia 4.9 communication score; Canbnb ~1,500 messages/week, 60% AI |
| Revenue + guest services | Free people for upsells and proactive calls | Upsell share, pre-arrival programs | Cosmica ~5% of Dubai revenue from upsells/cross-sells at peak; Cascadia concierge and pre-arrival calls |
| Ops / process manager | Virtual vs on-site coordination; brand-consistent replies | Queue control, fewer tool switches | Canbnb guest/owner/vendor inboxes; Bocobay leaving Intercom |

Agents are evaluated as answering with property information and reservation data, acting in connected tools, and escalating on procedures the operator sets—not as a guaranteed resolution rate. [Source](https://www.conduit.ai/product/agents)

## Buying attitudes and objections

**Trust.** Wynwood’s CX lead said guests cannot tell an AI agent from a human. Cascadia’s Ryan said guests think they are talking to someone local. Haven’s CEO had the agent say it needs a moment and will follow up in two or three minutes rather than guess. [Source](https://www.conduit.ai/customers/wynwood-house) [Source](https://www.conduit.ai/customers/cascadia-getaways) [Source](https://www.conduit.ai/customers/haven-2026)

**Control.** Site copy stresses rules you set and requests the team should handle. HomeHop wanted to approve messages or run autopilot after a failed vendor. The Flex’s CEO delayed turning AI on until he understood it would not answer without knowledge. [Source](https://www.conduit.ai/product/agents) [Source](https://www.conduit.ai/customers/homehop) [Source](https://www.conduit.ai/customers/the-flex)

**Change.** Haven’s CEO held three meetings, pledged no AI layoffs, and moved people into workflow building. Cascadia told the team AI would not take their jobs and expanded people into SEO, revenue, and concierge. Easy BnB, in the Bali Luxury Stays story, is the contrary case: eleven VAs replaced for an exit. Do not treat one staffing model as the category. [Source](https://www.conduit.ai/customers/haven-2026) [Source](https://www.conduit.ai/customers/cascadia-getaways) [Source](https://www.conduit.ai/customers/bali-luxury-stays)

**Fit skepticism.** Canbnb’s process manager was unconvinced AI would fit operations. HomeHop’s co-founder was leery after a chatbot that did not work. Bocobay’s objection was Intercom versus guest, owner, and ground operations in one place. [Source](https://www.conduit.ai/customers/canbnb) [Source](https://www.conduit.ai/customers/bocobay)

## Decision process

These pages describe implementations, not a standard RFP.

1. **The trigger is operational scale:** Canbnb’s 630-message backlog, Lauderdale’s call-center cost and ~57-minute replies, Bocobay’s dual inboxes, The Flex’s 17 SaaS tools, Haven/HomeHop growth without proportional support, Cascadia’s first PM acquisition.
2. **Economic buyer plus an operator** show up together (Jack and Jonathan; Jo-Anne and Dan; Dan Mitchen and Nate; Mayra as global CX). The Flex later said knowledge setup should have been founder-led.
3. **Proof is control, then measured automation.** Haven tied incentives to automation *and* scores. Bocobay moved email, then WhatsApp, then phone, then live chat. A security questionnaire is not documented.
4. **Comparisons named in stories:** Intercom, Jurny and other call services, a failed AI vendor, Google Voice, in-house messaging AI. That is not a complete shortlist.

Hotel-group buying (loyalty, cluster reporting, shared KB) appears on the industry page, not in a named hotel-group case in this pack. [Source](https://www.conduit.ai/industry/hotel-groups)

## Questions by role

**Founder / CEO / owner.** What support cost, refund, or night coverage stops scaling linearly? If this is an acquisition or exit, which operating metric belongs in the OM? Who owns knowledge-base truth after go-live?

**CX / process champion.** Which channels must share one workspace? What must never be automated, and who trains exceptions? How will you count resolved versus handed-off conversations without dropping communication scores?

**Operational users.** How do property views, routing, and notes work on shift handoff? What is handled at 2am (access codes, voice) versus what still pages a person?

**Technical evaluator (when present).** Messaging versus reservation-only PMS path, and duplicate-thread risk? Which writes (booking change, payment, task) are enabled for this stack? Is API/MCP in scope, or only the four marketed products in [Product catalog & capability map](#knowledge/products-capabilities)?

If a title is missing, ask. Do not invent ages, gender, income, or a fixed hotel-group committee. Related jobs live in [Buyer problems & desired results](#knowledge/customer-jobs).