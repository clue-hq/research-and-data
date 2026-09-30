## Overview

Conduit Workflows provides visual automations for proactive messages, routing and triage. Hospitality examples follow the stay journey, but triggers can also involve a new contact, a tag or an AI tool call; an existing booking is not a universal prerequisite. Agents supply the live reply behavior. Conduit describes it as automating that journey from check-in through follow-ups and routine tasks, with builders assembling confirmations, check-in instructions, follow-ups, and upgrades around the booking, the property, and the guest’s response. [Source](https://www.conduit.ai/product/workflows)

In platform architecture, workflows are the “arms and legs”: proactive outreach, routing into systems or teammates, and triage that escalates then can auto-close. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work) Conversational answering still sits with [AI Agents](#knowledge/product-agents) and the [Inbox](#knowledge/product-inbox). Workflows schedule, branch, wait, notify, and inject an agent when a defined event fires.

A concrete before/after: a support team copy-pastes door codes and check-in notes whenever a reservation appears. After a PMS-tied workflow, a reservation or stay-date trigger sends the confirmation and check-in sequence on connected email, WhatsApp, or OTA channels, branches on channel or a custom signal, waits until a send window, and only then injects an agent or pings Slack if the guest replies with a problem. Limits are real: the sequence only sends on connected channels, stay-date logic needs PMS/booking data, paid actions consume credits, and inbox routing is evaluated before workflow triggers. [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing)

## Who it is for

Conduit positions the company for hotel teams, serviced-apartment operators, and short-term rental managers. [Source](https://www.conduit.ai/pricing) Workflows is aimed at operators who already have a repeating guest calendar (confirm, instruct, upsell, follow up) and want those sequences designed once instead of typed per stay.

Buyer-role hypotheses include founders, revenue/guest-services leads and operations owners, informed by named stories rather than a required title map who care whether journey automation is included in a package and whether credits will cover outbound volume. Users are guest-services managers and the people Haven calls conversational engineers—staff who build and iterate workflows rather than answering every check-in question. [Source](https://www.conduit.ai/customers/haven-2026) Day-to-day agents still work exceptions in the inbox; they are consumers of routing and triage, not the primary authors.

## Capabilities and limits

Published Workflows capabilities on the product page:

| Capability | What Conduit states | Depends on | Not the same as |
| --- | --- | --- | --- |
| Visual builder | Hospitality triggers and actions without writing each sequence from scratch | Workspace access to workflows | Custom code in the [developer platform](#knowledge/product-developers) |
| Connected send | Email, WhatsApp, and OTA channels already connected | Channel setup | Unconnected OTAs |
| Conditional steps | Branch by booking channel, loyalty status, or custom signals; webhooks or MCP for supported tools | Those signals existing in the workspace | Guaranteed write-back to every PMS |
| Scheduled guest messages | Confirmations, check-in instructions, checkout reminders from PMS events and booking dates | Connected PMS / booking dates | Housekeeping dispatch (Operations is listed as coming soon; it is separate from the Operator assistant) |
| Post-stay campaigns | Stay dates, properties, guest responses; return offers | Identity of past guests | A measured win-back rate |
| Rule-based upgrades | Early check-in, gap nights, private chefs, room upgrades from booking details and rules you set | Rules and booking fields you configure | [Guest Portals](#knowledge/product-portals) checkout UI |

[Source](https://www.conduit.ai/product/workflows)

Docs add the building blocks: triggers such as a new contact, a conversation tag, or an AI tool call; actions (templated reply, reassign, notify, wait, inject AI); conditions/paths; and variables such as `{{contact.first_name}}`. Action groups are Message, AI, Workspace, and Controls. [Source](https://docs.conduit.ai/workflows/getting-started)

Limits to keep explicit: workflow **runs** are free; credits apply only when a successful run finishes a priced action. Triggers, conditions, waits, contact updates, and labels cost nothing. Failed or cancelled runs use 0 credits even if earlier steps finished. [Source](https://docs.conduit.ai/workflows/workflow-usage) Routing rules run **before** workflow triggers, so triggers should target the routed inbox, not Unmapped. [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing) REST and MCP workflow APIs are documented as v3-plan features, enabled via support—not as a default on every commercial package. [Source](https://docs.conduit.ai/api-reference/introduction)

## Workflows and use cases

Docs classify three types you can build from scratch or from a template:

| Type | Role | Doc examples | Hospitality reading (interpretation) |
| --- | --- | --- | --- |
| Proactive | Scheduled or triggered outbound | Survey 24 hours after a ticket resolves; renewal reminder | Confirmations, check-in/out reminders, return offers |
| Routing | Alert team or guest when conditions match | SMS when an order ships; Slack on negative survey | Slack/email when an agent books something or a tag fires |
| Triage | Ask humans when the AI lacks an answer, then reply | Billing/engineering/inventory ping then guest update | Escalate a lockout or billing exception, then close |

[Source](https://docs.conduit.ai/workflows/types-of-workflows)

Product-page hospitality sequences to scope in a demo: booking confirmation → check-in instructions on stay dates → checkout reminder → post-stay return offer; and if/then upgrade offers (early check-in, gap nights, add-ons) using booking details. [Source](https://www.conduit.ai/product/workflows) FAQ wording is the bound of what Conduit claims workflows automate: guest messages, follow-up campaigns, and add-ons such as early check-in, gap nights, and room upgrades, with the operator choosing trigger, conditions, and actions. [Source](https://www.conduit.ai/product/workflows)

Haven’s reported dog-at-property example is a routing/ops adjacent flow: when a guest brings a dog to a defined set of properties, notify the cleaning company and push the information back—built in about an hour by the guest-services manager. That is a customer-built workflow, not a packaged template catalog. [Source](https://www.conduit.ai/customers/haven-2026)

## Integrations and setup

Setup is not “pick a vendor logo.” Practical route:

1. Confirm that the workspace industry setting exposes the selected PMS; follow that provider’s setup instructions; connect PMS under Settings > Connections > PMS so listings and reservations sync and contacts can be created from bookings. Messaging vs non-messaging PMS paths differ: some PMS connections deliver guest messages; others supply property/reservation data only, with OTA messaging connected separately. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)
2. Connect the send channels the builder will use (email, WhatsApp, OTAs such as Airbnb). [Source](https://www.conduit.ai/product/workflows)
3. Set inbox routing so new contacts land in the inbox your workflow trigger targets. [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing)
4. Build in the visual editor (triggers, conditions, waits, sends, AI injection) or install workflow templates from the Marketplace. [Source](https://docs.conduit.ai/)
5. Optional: webhooks or MCP for supported tools; programmatic list/create/update of workflows and execution logs on the v3 API/MCP. [Source](https://docs.conduit.ai/mcp/overview)

The public integrations directory is a catalog of 43 apps (PMS, messaging, CRM, task managers). A logo is not proof that a named action exists as a first-class workflow step. [Source](https://www.conduit.ai/integrations) HomeHop’s SuiteOP workflow comment is a customer stack, not a listed Conduit integration. [Source](https://www.conduit.ai/customers/homehop)

## Pricing and packaging

There is **no published standalone Workflows price**. On the pricing page, workflows appear inside Messaging (“Operator, workflows, escalation”), which starts at **$18 / unit / month** with **40 credits / unit / month**. Starting rates are shown; pricing scales beyond 50 listings. Guest starts at $30/unit/month and adds portals, waivers and upsells. Guest + Devices starts at $36 and adds device management workflows. Full Suite starts at $48 and lists agentic operations workflows, tasks/workforce, scheduling/dispatch and inventory. Confirm exact availability because navigation still labels Operations as coming soon. None is a Workflows-only fee. A 0–25 unit Startup package is listed at **$899 / month** with 2,000 credits / month and no implementation fee. Talk-to-sales language applies as portfolio size grows. [Source](https://www.conduit.ai/pricing)

Credit units that matter for this product (successful finished steps only):

| Action | Credits |
| --- | --- |
| Slack or Teams message | 1 |
| HTTP webhook | 0 |
| HubSpot / Salesforce / Airtable record step | 1 |
| Run AI Prompt / Web Search | 2 / 5 |
| Email send (non-AI / AI-generated) | 1 / 4 |
| SMS or WhatsApp (non-AI / AI-generated) | 2 / 5 |
| Other-channel outbound message (non-AI / AI-generated) | 0 / 3 |
| Voice Agent Call (workflow action) | 6 per minute |

[Source](https://docs.conduit.ai/workflows/workflow-usage)

Inbound messages use no credits. The general credit guide separately lists regular voice at 1/minute and AI voice at 8/minute, versus the workflow action table’s 6/minute; confirm the applicable meter for the actual call path. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits) How far 40 credits per unit goes for a typical stay sequence is not published; model it from the table, not from package rhetoric. See [Pricing & packaging](#knowledge/pricing).

## Differentiation

Attributed to Conduit, not independently verified: a hospitality visual builder with booking/property/guest-response context, PMS-event scheduling, and branches on booking channel or loyalty—not a generic ticket macro tool. [Source](https://www.conduit.ai/product/workflows) Platform docs further separate workflows from agents (execution vs conversation) and from dashboards. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

Customer-attributed, not a Conduit SLA: Haven’s CEO on staff being given operational problems and building the workflow themselves. [Source](https://www.conduit.ai/customers/haven-2026) Do not convert that into “all customers become engineers in an hour.”

Competitive pages on conduit.ai list other vendors; those lists are not Workflows feature matrices. Keep comparisons in [Alternatives & differentiation](#knowledge/alternatives).

## Customer evidence

Use only stories that mention workflows. Do not assign Haven’s 90% automation, staffing cuts, or other accounts’ message-automation rates to this SKU unless the narrative isolates Workflows.

**Haven Vacation Rentals** (STR, ~270 properties, Conduit since February 2024; company-reported 2026 update): they had listings in Conduit at about 40% automation **with no workflows** and little knowledge-base work. The later operating model includes team members building workflows and training AI; Jack Zoppa: “Give them these problems. They just went and built the workflow and figured it out.” The dog-notification workflow was built in about an hour. Haven was rebuilding Slack triage workflows and expanding use of Conduit’s workflow engine. Portfolio automation and headcount figures in that article describe the broader Conduit program, not a Workflows-only KPI. [Source](https://www.conduit.ai/customers/haven-2026)

**HomeHop** (customer quote): Dan Mitchen said using AI in workflows with SuiteOP “is going to be an absolute game changer”—a forward-looking expectation, not a measured workflow result. Treat as their integration pattern, not a Conduit product metric. [Source](https://www.conduit.ai/customers/homehop)

## Sales discovery

Ask what is still typed by hand on a clock (confirmation, access instructions, checkout, win-back). Which PMS is source of truth, and does it pass messages or only reservations? Which send paths must the sequence use (email, WhatsApp, Airbnb/other OTA)? Who will own the builder after go-live—guest services, a single “Jonathan,” or a vendor? Which branches are policy (channel, pet, loyalty, gap night) versus hope? Where should a no-answer path go (Slack, reassign, inject agent)? Estimate monthly sends × credit table against the package’s credits per unit.

**Next practical step:** in a demo, rebuild one live stay sequence with their PMS event and one real channel—not a slide of 43 logos—then map Messaging-and-up packaging and credit burn. Book that working session rather than pitching Operations (still “coming soon”) or transferring an Agents case study into Workflows.
