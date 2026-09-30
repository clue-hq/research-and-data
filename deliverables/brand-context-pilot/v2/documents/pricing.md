Conduit’s public commercial story is package starting rates plus a credit pool, not a menu of separately priced Inbox, Agents, or Workflows SKUs. Figures below are what Conduit publishes on its pricing page and docs as of the captured pages—not a signed quote, not independently audited, and not a guarantee of what every customer pays.

## Published plans

The pricing page addresses “independent teams to enterprise,” shows starting rates, and says pricing scales beyond 50 listings. It also tells operators to talk to an AI expert to map a package. HTML and Markdown extracts agree on the dollar and credit numbers; nothing in the supplied pages is a conflicting toggle. [Source](https://www.conduit.ai/pricing)

| Package | Starting price | Included credits | Page CTA | What the package list adds |
| Messaging | $18 / unit / mo | 40 credits / unit / mo | Get Started | Unified inbox, Voice AI inbound and outbound, PMS and OTA integrations, Operator, workflows, escalation, analytics |
| Guest | $30 / unit / mo | 60 credits / unit / mo | Get Started | Everything in Messaging, plus in-portal AI concierge, rich-media guidebooks, damage waivers with no SKU fee, one-click payment upsells |
| Guest + Devices | $36 / unit / mo | 80 credits / unit / mo | Get Started | Everything in Guest, plus smart home, portal-integrated devices, guest/team access codes, device management workflows |
| Full Suite | $48 / unit / mo | 100 credits / unit / mo | Talk to Sales | Everything in Guest + Devices, plus tasks and workforce, agentic operations workflows, scheduling and dispatch, inventory management |
| Startup (0–25 units) | $899 / mo | 2,000 credits / mo | Get Started | Described as the full feature set with no implementation fee |

[Source](https://www.conduit.ai/pricing.md)

Do not treat $18–$48 as standalone licenses for [Inbox](#knowledge/product-inbox), [AI Agents](#knowledge/product-agents), or [Workflows](#knowledge/product-workflows). Those capabilities appear inside packages.

## Usage and billing units

Stacked packages are billed **per unit per month**; Startup is a **flat month**. The same pricing page talks about **listings** (rates scale beyond 50). The Portals FAQ prices an add-on by **contracted listing count**. These pages never equate unit, listing, and room—confirm the inventory object on the quote. [Source](https://www.conduit.ai/pricing)

A credit is Conduit’s usage unit. Included credits reset at the start of each monthly billing cycle. Usage is tracked in four categories: Workflows, Operator Sidebar, Internal Agents, and Voice AI. Replies sent by AI agents in the inbox do not consume credits. [Source](https://docs.conduit.ai/setting-up-conduit/credits)

| Activity | Published credit rule | Caveat on the same page |
| Regular voice minute | 1 credit per minute | Voice AI category |
| AI voice minute | 8 credits per minute | Same category; much heavier than regular voice |
| Operator sidebar | Variable per turn | ~7,000–71,000 billable tokens per 1 credit depending on model; prior context may be discounted |
| Internal agents | Dynamic | No single flat rate |
| Workflows | Paid actions on successful runs | Starting or running a workflow is free; most steps free; charges when a successful run sends a message, calls an integration, runs an AI prompt, searches the web, or makes an agent call |

[Source](https://docs.conduit.ai/setting-up-conduit/credits)

Voice AI can sit in the Messaging feature list and still draw credits when minutes run. Inbox AI replies do not. Illustration only: ten AI voice minutes would use 80 credits at 8 per minute—that is arithmetic on the published rate, not a customer invoice.

Settings > Billing shows cycle usage by category and workflow. When credits run low, Conduit says you can upgrade or continue into overage charged on the next invoice. Invoice PDFs are downloaded there; billing questions go to support@conduit.ai. [Source](https://docs.conduit.ai/setting-up-conduit/billing.md) No dollar overage rate is published.

## What is included

[Messaging](#knowledge/product-inbox) is the communications stack: every-channel inbox, inbound/outbound Voice AI, PMS/OTA integrations, [Operator](#knowledge/product-operator), workflows, escalation, analytics. [Guest](#knowledge/product-portals) adds stay-link merchandising on top of that stack (concierge, guidebooks, waivers without a SKU fee, one-click payment upsells). That is bundle copy, not a public à-la-carte Portals price. [Source](https://www.conduit.ai/pricing.md)

Guest + Devices adds locks, thermostats, sensors, portal-integrated devices, access codes, and device workflows. Full Suite adds workforce/operations bullets. Product navigation still labels Operations “Coming soon,” so do not treat those Full Suite lines as independently confirmed generally available modules. [Source](https://www.conduit.ai/pricing)

Startup is the full feature set for 0–25 units with no implementation fee. [Developer platform](#knowledge/product-developers) API and MCP access is for eligible authenticated workspaces; no developer line item appears on pricing.

The Portals FAQ (which fills gaps the HTML pricing FAQ does not answer) describes one branded stay link with no app: stay details, pre-arrival and identity checks, agreements or damage waivers, fees or deposits, upgrades, access when requirements are complete, and a stay-aware AI concierge. Portal card payments are described via a connected Stripe account (card, Apple Pay, Google Pay, or Link), not reuse of the original booking card. Smart-lock behavior varies by provider and is confirmed in implementation. [Source](https://www.conduit.ai/product/portals.md)

The [workflow action guide](https://docs.conduit.ai/workflows/workflow-usage) separately lists Voice Agent Call at **6 credits/minute**, while the general guide lists AI voice at **8** and regular voice at **1**. Confirm which meter applies to the actual call path and whether any usage overlaps; these sources do not justify silently substituting or adding the rates.

Operator in Messaging is the workspace assistant, not the Operations product. Operations is separately marked coming soon in navigation; confirm individual Full Suite operational features before promising them. [Operator guide](#knowledge/product-operator)

## Choosing a package

Match published bullets, not assumed ROI. Messaging if the job is omnichannel inbox, voice, Operator, and workflows without portal merchandising. Guest if waivers, guidebooks, in-portal concierge, and payments matter. Guest + Devices if locks/thermostats/sensors and access codes must live in the portal. Full Suite if the buyer also wants workforce/operations language—and they should talk to sales (the only package with that CTA). Startup if the account is in the 0–25 unit band and wants the full feature set with the published no-implementation-fee claim.

Do not assume Messaging can add Portals at a listed rate. The FAQ says add-on pricing exists; the package table does not print it. Capability detail lives in the [product catalog](#knowledge/products-capabilities), not in a hidden SKU price.

## Unpublished terms

Not in these sources: overage $ per credit; volume steps above 50 listings; whether a unit is a listing; taxes; contract length; seat fees; guest-transaction fee schedule; API/MCP surcharges; currencies other than $. The HTML pricing FAQ lists “Is Conduit free?” without an answer in the extract—do not invent one. Portals FAQ says sales can quote monthly or annual; the main table is monthly starting rates only.

Portals is bundled inside Guest and higher packages **and** described as a paid add-on priced by contracted listing count with graduated volume pricing; bundles and guest-transaction terms can change the final rate. Both statements are Conduit’s; they are not one public number. [Source](https://www.conduit.ai/product/portals.md)

## Questions before a quote

1. Inventory: unit vs listing vs room, 0–25 (Startup) vs above 50 listings.
2. Portals path: Guest bundle vs listing add-on, and whether Messaging-only is even eligible.
3. Devices and access codes (Guest + Devices).
4. Full Suite operations/workforce scope versus Operations “Coming soon.”
5. Credit mix: AI voice (8/min) vs regular voice (1/min), Operator tokens, internal agents, paid workflow actions—not inbox AI replies.
6. Low-credit path: upgrade vs overage on the next invoice (rate unpublished).
7. Implementation fee (Startup says none; others unpublished) and monthly vs annual.
8. Stripe / guest-transaction terms, PMS/OTA/lock stack (lock and payment rules vary), billing entity, and Settings > Billing access (support@conduit.ai for charge disputes).

Starting rates are a map for the conversation, not the contract.