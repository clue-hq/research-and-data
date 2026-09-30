## Overview

Guest Portals are Conduit’s stay-level guest experience surface: one branded link for arrival prep, access instructions, upgrades, payments, and in-portal questions. The product page frames it as “the full stay, upsells, and guest support in one link,” with no guest app to download. ([Source](https://www.conduit.ai/product/portals.md))

Portals sit beside [AI Agents](#knowledge/product-agents) and [Inbox](#knowledge/product-inbox). Messaging answers guests in channels; Portals is the page a guest opens before and during a stay. Capabilities below are only those Conduit attributes to Portals, the Guest package, or the Portals API—not generic inbox automation.

## Who it is for

Public pages position Portals for hotels and vacation rentals. Company FAQ copy also lists hotel teams, serviced-apartment operators, and short-term rental managers as Conduit’s audience; that is a company-level statement, not a Portals-only ICP. ([Source](https://www.conduit.ai/product/portals))

**Buyers** are commercial owners of guest experience and ancillary revenue: operators who want a branded guide, damage waivers without a SKU fee (Guest package language), in-stay extras, and fewer “where is the code?” threads. **Users** split three ways: guests who complete the link; ops or CX leads who own templates, offers, verification rules, and brand kit; and implementation or engineering staff who use Portals API/MCP tools when the add-on is enabled.

Do not invent urgency scores or “typical” portfolio sizes from this page. Fit is an account that already has reservation/listing context in Conduit and a reason to replace a PDF guide, third-party guidebook, or manual waiver/payment chase. See [ICP strategy](#knowledge/ideal-customers) for segment work elsewhere.

## Capabilities and limits

| Capability | What Conduit publishes | Stated limit or condition |
| --- | --- | --- |
| One stay link | Property details, dates, check-in steps, access instructions | No app required ([Source](https://www.conduit.ai/product/portals.md)) |
| Pre-arrival | Stay details, identity checks, questions, agreements/waivers, fees/deposits | Access after required steps are complete ([Source](https://www.conduit.ai/product/portals.md)) |
| Payments | Stripe: card, Apple Pay, Google Pay, or Link | Guest enters a method in-portal; not the original booking card ([Source](https://www.conduit.ai/product/portals.md)) |
| Upsells | Browse extras and pay at checkout | Offers show only after a template layout references them ([Source](https://docs.conduit.ai/api-reference/portals/overview.md)) |
| AI concierge | Property-aware answers from stay + property info | 24/7 / local recommendations claimed on the product page, not independently measured ([Source](https://www.conduit.ai/product/portals.md)) |
| Smart access | Instructions, door codes, or lock controls after pre-arrival steps | Compatible integrations only; lock behavior varies; confirmed in implementation ([Source](https://www.conduit.ai/product/portals.md)) |
| Branding | Layout, colors, theme, hero, guides, offers | Team can migrate an existing guide and build a sample before portfolio rollout ([Source](https://www.conduit.ai/product/portals.md)) |

API configuration is modular: verification rules (deposits, agreements, arrival details, questions), offers (examples: late checkout, mid-stay clean, airport pickup), templates, guides, brand kit, and read-only sessions (progress, submitted fields, orders, tickets, assets). You can use verification rules without a template. Portal API methods require the **Portals add-on**; otherwise they return `403 Forbidden`. Reads need `Access Portals`; writes need `Manage Portals`. ([Source](https://docs.conduit.ai/api-reference/portals/overview.md))

Unknown from these sources: which PMS fields write back, conversion rates, and whether every Guest-bundle customer also has the API add-on entitlement.

## Workflows and use cases

**Before.** A guest books on an OTA. The team emails a PDF guidebook, a waiver link, a separate payment request, and later a door code. Identity checks live in another tool. After-hours questions bounce to [Inbox](#knowledge/product-inbox) or a phone tree. Upsells are ad hoc messages. Access is sent even if the waiver is unsigned.

**After (as published).** Conduit uses reservation, guest, listing, and booking-channel context so each portal is stay-specific. The guest opens one branded link, completes questions and identity checks, signs the rental agreement or damage waiver, pays required fees or deposits, buys upgrades, and only then receives access when requirements are complete. The in-portal concierge answers from stay details and property information. Email or SMS can still run alongside the portal. ([Source](https://www.conduit.ai/product/portals.md))

**Limits of that workflow.** Payment and verification rules can be tailored by booking channel, including excluding flows where an OTA’s policies require it. Guests do not reuse the booking card. Exact fields, write-back, smart-lock support, and payment rules vary by integration and are confirmed before launch. Lock compatibility is not a logo-level guarantee. ([Source](https://www.conduit.ai/product/portals.md))

Devices (separate add-on) can automatically generate a door code per reservation and publish it to the guest portal; that is a Devices capability that *lands in* Portals, not a Portals-only lock catalog. ([Source](https://docs.conduit.ai/devices/overview.md))

## Integrations and setup

Do not treat a PMS logo as proof the portal can collect deposits or issue codes. The published route is: connect PMS/OTA so reservation and listing context exist → connect Stripe for in-portal pay → confirm lock provider and property setup if access is in-portal → configure verification rules, offers, templates/guides, brand kit → optionally activate a template. Implementation can include moving content from a current guest guide and a sample portal before rollout. ([Source](https://www.conduit.ai/product/portals.md))

PMS connection itself is workspace-level (Settings → Connections → PMS, then Knowledge sync). Messaging vs non-messaging PMS rules affect inbox routing, not portal page composition; see [Integrations](#knowledge/integrations). Guest + Devices packaging adds portal-integrated smart devices and access codes; commercial access (cards, mobile keys, Instant Keys) is documented under Devices, not on the Portals FAQ. ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms))

Developers: MCP portal tools need the add-on plus the same Access/Manage Portals permissions; v3 API/MCP enablement is a support request, not a self-serve claim on the pricing page. ([Source](https://docs.conduit.ai/mcp/overview))

## Pricing and packaging

Public materials describe **two overlapping commercial shapes**. Preserve both; do not collapse them into one SKU.

| Shape | What is published | Units |
| --- | --- | --- |
| Guest bundle | Starting **$30 / unit / month**, **60 credits / unit / month**; everything in Messaging plus in-portal AI concierge, rich-media guidebooks, damage waivers with no SKU fee, one-click upsell payments ([Source](https://www.conduit.ai/pricing.md)) | Per unit / month; starting rates; scales beyond 50 listings ([Source](https://www.conduit.ai/pricing)) |
| Portals add-on | Paid add-on by **contracted listing count**, graduated volume pricing; bundles and **guest-transaction terms** can change the final rate; sales quotes monthly or annual ([Source](https://www.conduit.ai/product/portals.md)) | Listings; exact rate unpublished |
| Guest + Devices | Starting **$36 / unit / month**, **80 credits**; portal-integrated smart devices and access codes ([Source](https://www.conduit.ai/pricing.md)) | Per unit / month |
| Startup | **0–25 units**, **$899 / month**, **2,000 credits / month**, full feature set, no implementation fee ([Source](https://www.conduit.ai/pricing.md)) | Workspace month |

Messaging starts at **$18 / unit / month** and **40 credits** and does **not** list portals. Full Suite starts at **$48 / unit / month** and **100 credits**. Starting rates; talk to sales to map a package. ([Source](https://www.conduit.ai/pricing.md))

**Credits (workspace usage, not a Portals meter).** Included credits reset each monthly billing cycle. Conduit tracks four categories: workflow paid actions, Operator sidebar turns, internal agent activity, and Voice AI. **Inbox AI agent replies do not consume credits.** Regular voice is **1 credit per minute**; AI voice is **8 credits per minute**. Operator cost varies by model and tokens (roughly 7,000–71,000 billable tokens per credit depending on model). Internal agents have a dynamic cost. Workflow *runs* are free; credits apply when a successful run finishes a paid action. Low-credit path: notification, then upgrade or continue into **overage billed on the next invoice**. View usage under Settings → Billing. ([Source](https://docs.conduit.ai/setting-up-conduit/credits))

A bundle price is not a standalone Portals price. Guest-transaction fees are acknowledged but not quantified here.

The [workflow action guide](https://docs.conduit.ai/workflows/workflow-usage) separately lists Voice Agent Call at **6 credits/minute**, while the general guide lists AI voice at **8** and regular voice at **1**. Confirm which meter applies to the actual call path and whether any usage overlaps; these sources do not justify silently substituting or adding the rates.

## Differentiation

Attributed product claims, not third-party proof: stay-scoped branded link instead of a generic guidebook app; AI concierge that uses *this stay’s* details; Stripe checkout in the same page as waivers and extras; optional lock controls after verification; Conduit-led content migration and a sample portal. Guest package copy highlights “Damage waivers, no SKU fee” and “Upsells with One-click Payment.” ([Source](https://www.conduit.ai/pricing.md))

Competitive pages list Duve, Enso Connect, Canary, and others as “Conduit vs.” destinations; those pages are not evidence that Portals matches a named rival feature-for-feature. For broader positioning see [Alternatives](#knowledge/alternatives).

## Customer evidence

The broader [customer evidence library](#knowledge/customer-evidence), which includes Haven, Cascadia, Lauderdale, Cosmica and Bali Luxury Stays, report inbox/agent automation, staffing, and messaging upsells. **None of those stories isolate Guest Portals**—no portal conversion, waiver completion, or in-portal GMV figures. Do not reuse 90% automation, $500k asset value, or Dubai “up to 5%” upsell as Portals outcomes. ([Source](https://www.conduit.ai/customers/haven-2026))

Until a Portals-scoped case exists, proof for this product is the documented guest path, packaging, and API—not portfolio ROI. Track named portal customers as an open investigation: [Customer evidence](#knowledge/customer-evidence).

## Sales discovery

Ask only what decides Guest vs Messaging vs add-on and whether implementation can land:

1. What is the current guest guide (PDF, app, PMS message, third-party portal), and who owns content?
2. Which pre-arrival steps are mandatory before access: ID, waiver, deposit, house rules?
3. Stripe (or equivalent) already in use? Any OTA channels that must **exclude** in-portal pay?
4. Lock/access vendor and whether codes must appear only after verification?
5. PMS/channel: which reservation fields must appear, and is write-back required?
6. Ancillary catalog: SKU-fee pain on waivers, one-click extras, channel-specific offers?
7. Buyer of guest experience vs ops user who will maintain templates and offers?
8. Listing count for contracted Portals add-on vs Guest per-unit bundle, plus expected credit use (voice/Operator/workflows—not inbox replies)?

**Next practical step:** book a stack review that confirms PMS fields, Stripe, lock compatibility, and a sample portal—then quote either Guest ($30/unit starting) or the listing-count add-on, stating which contradiction applies to this account. Do not promise a rate Conduit has not priced. Map credits and overage using [Pricing & packaging](#knowledge/pricing) and the credit guide, not Portals page rhetoric.