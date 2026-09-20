## Overview

Conduit positions **Agents** as the product that answers guest messages and calls, retrieves property and reservation context, takes action in connected tools, and escalates to people when needed. The public product line treats Agents as distinct from [Inbox](#knowledge/product-inbox), [Guest Portals](#knowledge/product-portals), and [Workflows](#knowledge/product-workflows): Agents “answer guest messages and calls, and take action,” while Inbox is the handoff surface and Workflows automate journey and routine-task sequences. [Source](https://www.conduit.ai/product/agents)

The company-defined agent is not a draft-only chatbot. Conduit’s FAQ states that an AI agent “answers guest messages and calls using your property information and reservation data,” can create a task or update a booking through connected tools, and can pass requests to the team. [Source](https://www.conduit.ai/product/agents)

Docs describe the same product as configurable workers: external (guest-facing), internal, and voice agents with persona, tool access, skills, behavior, triggers, and publish state, plus Knowledge, Skills, Tools, sandbox testing, and Operator for inspecting configuration. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

## Who it is for

Conduit says the company is for hotel teams, serviced-apartment operators, and short-term rental managers, and that its AI agents answer messages and calls, handle routine requests, and coordinate work with the team. Industry pages on the same site group short-term rentals, independent hotels, and hotel groups. [Source](https://www.conduit.ai/pricing)

**Buyers** in published stories are operators and founders who need 24/7 coverage without linear headcount (portfolio growth, after-hours phones, acquisition integration). **Users** are guest-services staff who teach the agent, standardize answers, review gaps, and take escalations—Haven describes team members becoming “conversational engineers.” [Source](https://www.conduit.ai/customers/haven-2026)

This is a fit conversation when guest volume already hits phones, OTA inboxes, WhatsApp, and email, and when property policies and live reservation data exist (or can be documented). It is a weaker first product if the account only wants a shared inbox with no agent autonomy; start from [Inbox](#knowledge/product-inbox) instead.

## Capabilities and limits

| Capability | What Conduit publishes | Bound to watch |
| --- | --- | --- |
| Omnichannel answer | Voice, chat, email, WhatsApp, and connected OTA messages with conversation history | Only connected channels; Booking.com and VRBO listed as coming soon on the integrations directory | [Source](https://www.conduit.ai/product/agents) |
| Property-specific answers | Uses property information and policies | Quality tracks what is in Knowledge / PMS-synced listings | [Source](https://www.conduit.ai/product/agents) |
| Actions | Check bookings, change reservations, collect payments, create tasks via supported integrations | Not every PMS connection is two-way messaging or write-back | [Source](https://www.conduit.ai/product/agents) |
| Rules and escalation | Procedures the agent follows; requests the team should handle | Humans remain in the loop by design | [Source](https://www.conduit.ai/product/agents) |
| Improve loop | Find gaps, review proposed fixes, test before guests see them | Changes are not live until reviewed/tested | [Source](https://www.conduit.ai/product/agents) |
| Voice | Voice agents for calls; VoiceAI numbers can run 24/7 or on a schedule, with static/dynamic/warm-transfer escalation | Bring-your-own Twilio SMS needs webhook, A2P 10DLC, and SMS enabled | [Source](https://docs.conduit.ai/setting-up-conduit/connect-voiceai-ai-number) |

The complete product FAQ says resolution depends on the guest requests, knowledge base, integrations and escalation rules; track resolved conversations and human handoffs. It does not prescribe a universal automation percentage. Do not treat marketing “end to end” as a guaranteed resolution rate. Operations (“AI-coordinated housekeeping, maintenance and inspections”) is listed as coming soon and is not this product. [Source](https://www.conduit.ai/product/agents)

## Workflows and use cases

**Before.** A night or weekend guest texts for a door code, then calls about parking. Staff hunt Drive/PMS tabs, copy-paste the same policy, and miss the phone. Volume rises with each listing. Haven described ~25 support people at peak across shifts before the automation push. [Source](https://www.conduit.ai/customers/haven-2026)

**After (Agents).** The same thread lands with history. The agent retrieves listing policy and reservation context, answers the code/parking question, and—if the integration supports it—updates a booking, collects a payment, or opens a task. If the request is out of policy, it escalates. Operators inspect reasoning/sources in the conversation, teach the miss, and sandbox a fix before guests see it. HomeHop used voice AI for overnight coverage 1 AM–7 AM rather than staffing that window. [Source](https://www.conduit.ai/customers/homehop)

**Limits of that loop.** The Flex’s CEO said that if the information was not there, the AI would not reply—and that misunderstanding delayed turning it on. Haven’s jump from ~40% to 90% automation required knowledge standardization, Slack “AI Avengers” review, and months of teaching, not a switch-flip. Workflows that notify cleaners or inject follow-ups are a related but separate product; see [Workflows](#knowledge/product-workflows). [Source](https://www.conduit.ai/customers/the-flex)

Docs map a crawl: Level 0 copilot drafts, Level 1 the team teaches simple end-to-end conversations, Level 2 the agent takes actions. “Road to Autopilot” is Connect → Teach → Test → Deploy, not an implied day-one autopilot. [Source](https://docs.conduit.ai/overview/the-5-levels-of-ai-automation)

## Integrations and setup

Agents do not magically “have Guesty.” Setup is: workspace → connect channels → connect PMS/data → configure the V3 agent (knowledge, skills, tools, triggers) → sandbox → publish. [Source](https://docs.conduit.ai/)

**PMS route.** `Settings > Connections > PMS` → pick provider → authenticate → import listings; PMS-backed content appears under `Build > Knowledge`; auto-sync is scheduled from the Knowledge source menu. Conduit says it integrates with over 15 PMS systems to populate listing information. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)

Messaging path is the critical split: some PMS connections (e.g. Guesty, Hostaway, Lodgify, Beds24) send guest messages into Conduit; others (e.g. Opera Cloud, Mews, Cloudbeds, Apaleo) supply property/reservation data only—OTA messaging must be connected as auxiliary channels. Connecting the same OTA both through a messaging PMS and directly can duplicate conversations. If Airbnb is the primary PMS, another PMS cannot be added in that workspace. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)

Opera Cloud example: OHIP credentials sync property, reservation, and profile data so agents can ground answers; Conduit states Opera “does not route guest messaging through this integration.” [Source](https://www.conduit.ai/integrations/opera)

Airbnb is documented as two-way send/receive in Conduit plus reservation modifications—verify write actions per account, not from the logo wall. [Source](https://www.conduit.ai/integrations/airbnb)

Voice: `Settings > Channels > Phone` → claim or route a VoiceAI number → configure agent voice, greeting, and escalation. [Source](https://docs.conduit.ai/setting-up-conduit/connect-voiceai-ai-number)

Full catalog and implementation caveats live in [Integrations & implementation readiness](#knowledge/integrations).

## Pricing and packaging

There is **no published standalone Agents price**. Voice AI (inbound and outbound) is listed inside the **Messaging** package, starting at **$18 / unit / month** with **40 credits / unit / month**, alongside unified inbox, PMS/OTA integrations, Operator, workflows, and escalation. Starting rates are shown; pricing “scales beyond 50 listings.” Guest ($30/unit/month) adds the stay/portal layer; Guest + Devices ($36) adds devices; Full Suite ($48) lists workforce and operational features. Operations remains marked coming soon in navigation, so confirm the specific operational feature before promising availability. These are package rates, not a separate Agents license. A 0–25 unit Startup plan is **$899 / month** with **2,000 credits / month** and “no implementation fee.” [Source](https://www.conduit.ai/pricing)

The credit guide says inbox AI replies use no credits, regular voice costs 1 credit/minute and AI voice costs 8 credits/minute. The workflow action guide separately lists Voice Agent Call at 6 credits/minute. Confirm the applicable call path and how these meters relate before quoting; do not silently substitute or add the rates. Dollar overage pricing remains unestablished. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits) [Workflow usage](https://docs.conduit.ai/workflows/workflow-usage) Map the account on [Pricing & packaging](#knowledge/pricing).

## Differentiation

Attributed product claims, not guarantees:

- **Answer plus act**, not draft-only: property context, reservation data, and tool actions, with team escalation. Renjoy’s CTO, quoted on the pricing page: “We don’t want to just draft messages—we want real automation.” [Source](https://www.conduit.ai/pricing)
- **Inspectable worker model** (docs): reasoning and sources in-thread; users approve, edit, or teach inline; sandbox before deploy. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)
- **Hospitality channel + PMS split** rather than a generic helpdesk bot, including scheduled or 24/7 voice. The Flex’s CEO contrasted Conduit with Front, Zendesk, and Trengo as “flow bots” on AI—his opinion, not a bake-off. [Source](https://www.conduit.ai/customers/the-flex)

See [Alternatives & differentiation](#knowledge/alternatives) before using competitor names in outbound copy.

## Customer evidence

Company-published stories; not independently verified. Do not copy a portal, inbox, or whole-platform metric onto Agents unless the story is about AI answering/acting.

| Account | Agent-relevant report | Scope / date notes |
| --- | --- | --- |
| Haven Vacation Rentals | 90% automation across ~270 properties, from ~40%; support staffing need described as 25 people to two per shift; quality scores held ~4.8–4.9 | Using Conduit since February 2024; required teaching, workflows, and knowledge work—not Agents in isolation. Header “59%” Guest Favorite vs body “55%” | [Source](https://www.conduit.ai/customers/haven-2026) |
| Cascadia Getaways | 60% automation and 4.9 communication score across ~100 properties; AI on lockbox, parking, local recs; humans on empathy/escalation | Start date unresolved: header says December 2024; body describes a March deployment | [Source](https://www.conduit.ai/customers/cascadia-getaways) |
| HomeHop | 70% automation; voice AI 1 AM–7 AM; portfolio 40→108 listings without added guest-support hires (company claim) | Using since June 2025 in the story header; body also says “approximately two years”—leave unresolved | [Source](https://www.conduit.ai/customers/homehop) |
| Canbnb | ~1,500 messages/week, 60% handled by AI | Mix of inbox structure and AI; since March 2024 | [Source](https://www.conduit.ai/customers/canbnb) |
| The Flex | CEO describes 70% automation as “very realistic”; the hero also claims 90% | The hero and body differ, and 80–90% also appears as a future ambition. Do not use 90% as a verified outcome; using-since header says December 2023 | [Source](https://www.conduit.ai/customers/the-flex) |

Lauderdale Boutique Hotel reports faster replies and lower support cost after replacing a call center with “Conduit’s AI-powered support platform **and** 24/7 staffed support team”—do not cite $500k asset value as an Agents-only outcome. Wynwood House’s “cannot tell the difference between an AI agent and a human agent” is a CX quote on reply quality inside a unified-inbox rollout. More proof: [Customer evidence & usable proof](#knowledge/customer-evidence).

## Sales discovery

1. Which channels must the agent own on week one (Airbnb/Hostaway messaging vs Opera/Mews data-only plus direct OTA/voice)?
2. Which requests may the agent execute (booking change, payment, task) versus escalate—named policies, not “most FAQs”?
3. Who will teach Knowledge/Skills weekly, and what is today’s after-hours phone path?
4. What automation rate and quality floor would you accept in the first 60 days (Haven held scores while climbing; Cascadia locked 4.9)?
5. Unit count and whether Messaging ($18/unit starting) vs Startup ($899/month) is the commercial path—credits included vs unknown overage?

**Next step:** book a demo that uses one live listing, one PMS connection type (messaging vs data-only), and a VoiceAI schedule, then sandbox the top three intents before any autopilot discussion.