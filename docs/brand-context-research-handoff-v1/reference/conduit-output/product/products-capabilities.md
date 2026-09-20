## Product system

Conduit’s current website catalog is a four-product hospitality stack, not a long list of SKUs. The global product nav and footer name **Conduit Agents**, **Conduit Inbox**, **Conduit Portals**, and **Conduit Workflows**. A fifth nav item, **Operations**, is labeled coming soon for AI-coordinated housekeeping, maintenance, and inspections. [Source](https://www.conduit.ai/product/agents)

Those four names are the primary products. Other surfaces should not be treated as extra catalog products unless a source says they are sold that way:

- **Operator** is a workspace assistant for inspecting and editing agent configuration, and it also appears as a line inside the Messaging package, not as its own product page. [Source](https://docs.conduit.ai/) [Source](https://www.conduit.ai/pricing)
- **REST API and MCP** are a developer platform for workspace data and tools. Docs state both are available only on the **v3 plan** and may need support enablement. [Source](https://www.conduit.ai/developers) [Source](https://docs.conduit.ai/api-reference/introduction)
- **Integrations** are connections (the public directory lists 43 entries, including some marked coming soon). A logo is not proof of a specific write-back or messaging action. [Source](https://www.conduit.ai/integrations)
- **Affiliate Program** appears in the site footer; the integrations page also carries reseller-style copy. Neither source defines a standalone product. [Source](https://www.conduit.ai/product/agents)

Docs describe a different internal model: Inbox as the conversation surface; Build surfaces (Agents, Knowledge, Skills, Tools, Operator, Sandbox) as the brain; Workflows as automations; Dashboards as metrics. That is how the system is assembled, not a second product list. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

Plan packaging is a third layer. Public rates are **Messaging** ($18 / unit / mo starting, 40 credits), **Guest** ($30, 60 credits), **Guest + Devices** ($36, 80 credits), **Full Suite** ($48, 100 credits), plus a **Startup** bundle for 0–25 units at $899 / mo with 2,000 credits. Starting rates are shown and pricing scales beyond 50 listings. A bundle price is not a standalone Agents or Portals price. [Source](https://www.conduit.ai/pricing)

## Product and capability map

Buyer problems below are the problems each product page claims to address, not an inferred ICP.

| Product | Buyer problem (site language) | Workflow the page describes | Dependency | Linked guide |
| --- | --- | --- | --- | --- |
| Agents | Answer guest messages and calls, retrieve context, and take action; escalate when needed | Handle voice, chat, email, WhatsApp, and connected OTA threads; update bookings, collect payments, create tasks; review and backtest replies | Property information, reservation data, and supported connected tools | [AI Agents](#knowledge/product-agents) |
| Inbox | Messages, calls, and team handoffs in one workspace | Organize by property or team; take over with conversation history; keep stay/booking context beside the thread | Connected channels; PMS/OTA context for booking details | [Inbox](#knowledge/product-inbox) |
| Portals | One branded stay link for guidebook, upsells, payments, and AI concierge | Pre-arrival details and checks; extras with payment; in-portal questions using stay and property info | Stay/reservation context; Guest packaging on the public price page; optional smart-lock/device connections | [Guest Portals](#knowledge/product-portals) |
| Workflows | Automate the guest journey from check-in to follow-ups and routine tasks | Visual builder: PMS-dated messages, post-stay campaigns, conditional upgrades; webhooks or MCP to supported tools | Connected email/WhatsApp/OTA channels and booking signals | [Workflows](#knowledge/product-workflows) |

Agents are described as answering with property information and reservation data, acting through connected tools (for example creating a task or updating a booking), and passing requests to the team. [Source](https://www.conduit.ai/product/agents)

Inbox is the operating surface: SMS, WhatsApp, email, calls, social, and connected OTA threads in one workspace, with handoffs that keep history. [Source](https://www.conduit.ai/product/inbox)

Portals give guests one branded link (no app) to review stay details, complete pre-arrival and identity checks, sign agreements or waivers, pay fees or deposits, buy upgrades, access the property when requirements are complete, and ask the AI concierge. [Source](https://www.conduit.ai/product/portals)

Workflows send guest messages, run follow-up campaigns, and offer add-ons such as early check-in, gap nights, and room upgrades; the operator chooses trigger, conditions, and actions. Docs also classify workflows as proactive, routing, and triage automations. [Source](https://www.conduit.ai/product/workflows) [Source](https://docs.conduit.ai/workflows/types-of-workflows)

Industry and use-case URLs (Airbnb automation, after-hours receptionist, room upgrades, and similar) are marketing entry pages, not extra products. Comparison URLs (Canary, Zendesk, and others) are positioning pages, not capabilities. [Source](https://www.conduit.ai/product/agents)

## How the products work together

The intended loop is: connect channels and PMS data → teach agents with knowledge, skills, tools, and rules → run conversations in Inbox → use Workflows for scheduled or conditional journeys → use Portals as the guest-facing stay surface → inspect configuration with Operator and measure in dashboards. Docs frame this as a Connect / Teach / Test / Deploy path from copilot toward autopilot. [Source](https://docs.conduit.ai/) [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

Inbox routing assigns new contacts to an inbox before workflow triggers fire, so automations should target the routed inbox, not Unmapped. [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing)

PMS connections feed listing and reservation context. Docs say Conduit integrates with over 15 PMS systems, classify some as messaging PMS connections and others as reservation-data-only, and warn that mixing incompatible types can duplicate conversations. Opera Cloud, for example, is described as syncing property, reservation, and profile data without routing guest messaging through that integration. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms) [Source](https://www.conduit.ai/integrations/opera)

Developer access sits beside the four products: typed REST endpoints for workspaces, contacts, conversations, tickets, calls, knowledge, agents, skills, workflows, and devices; MCP exposes overlapping tools to clients such as ChatGPT, Claude, Cursor, and VS Code. Device tools in MCP require the Devices add-on. [Source](https://www.conduit.ai/developers) [Source](https://docs.conduit.ai/mcp/overview)

## Availability and boundaries

**Generally marketed as available:** Agents, Inbox, Portals, Workflows; Messaging-package features listed as unified inbox, voice AI (inbound and outbound), PMS and OTA integrations, Operator, workflows, escalation, analytics. [Source](https://www.conduit.ai/pricing)

**Packaged, not separately priced on the public page:** Portals sit in **Guest** and above (“Everything in Messaging” plus in-portal AI concierge, guidebooks, damage waivers, upsells). Smart-home/device capabilities sit in **Guest + Devices**. Tasks, workforce, agentic operations workflows, scheduling/dispatch, and inventory sit in **Full Suite**. [Source](https://www.conduit.ai/pricing)

**Gated or enablement-required in docs:** API and MCP on the v3 plan, contact support to enable; MCP default 120 requests per minute per workspace, shared with REST. [Source](https://docs.conduit.ai/api-reference/introduction) [Source](https://docs.conduit.ai/mcp/overview)

**Availability conflicts:** Operations is marked coming soon in navigation while Full Suite lists operational features. The integration directory labels Booking.com and VRBO coming soon, but industry pages and release notes describe OTA messaging paths. Confirm direct versus PMS-mediated connections and the exact enabled actions; do not promise or deny the complete workflow from one directory badge. [Source](https://www.conduit.ai/product/agents) [Source](https://www.conduit.ai/integrations)

**Contradiction to preserve:** changelog entries already describe Operations tasks, schedules, workforce call reporting, and portal/device controls (for example 3.13–3.15 in September 2026), while the marketing nav still says Operations is coming soon. Treat nav copy as the catalog status and changelog as evidence that some operations surfaces already exist in-product. [Source](https://www.conduit.ai/changelog)

**Do not infer:** that every listed integration supports the same agent actions; that HostAI-labeled Email/WhatsApp blurbs redefine the product name; that “most teams go live within a week” is a verified implementation SLA (docs claim, not customer-proofed here). [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

Commercial mapping, credit burn, and contract packaging belong in [Pricing & packaging](#knowledge/pricing). Connection depth belongs in [Integrations & implementation readiness](#knowledge/integrations).

PMS visibility also depends on workspace industry configuration. The setup documentation uses STR/LTR in general instructions and STR/Hotel in a provider-specific passage. Confirm the selected PMS and workspace setting; this is implementation readiness, not a negative ICP rule. [PMS setup](https://docs.conduit.ai/setting-up-conduit/connect-pms)

## Choosing the entry point

Lead with the **named product** that matches the job, then confirm **package** coverage:

- Omnichannel guest comms and human takeover → Inbox, usually with Agents; Messaging is the public starting package. [Source](https://www.conduit.ai/product/inbox)
- 24/7 answers plus actions in connected tools → Agents (voice and messaging). VoiceAI numbers, schedules, and warm transfer are documented separately. [Source](https://www.conduit.ai/product/agents) [Source](https://docs.conduit.ai/setting-up-conduit/connect-voiceai-ai-number)
- Pre-arrival, waivers, deposits, upgrades, guidebook → Portals; public pricing places this at Guest and above. [Source](https://www.conduit.ai/product/portals)
- Confirmations, check-in, win-back, rule-based upsells → Workflows; they also appear inside Messaging packaging. [Source](https://www.conduit.ai/product/workflows) [Source](https://www.conduit.ai/pricing)
- Custom systems, MCP clients, or code tools → [Developer platform & custom workflows](#knowledge/product-developers), after confirming v3/API entitlement.
- Internal configuration help → [Operator & internal AI availability](#knowledge/product-operator), not a fifth website product.

Startup is a published $899/month path for 0–25 units. Messaging, Guest and Guest + Devices show per-unit starting rates with Get Started; Full Suite has Talk to Sales. The site says pricing scales beyond 50 listings without publishing the curve. Confirm package eligibility rather than making 25 or 50 a universal sales-process gate. [Source](https://www.conduit.ai/pricing)
