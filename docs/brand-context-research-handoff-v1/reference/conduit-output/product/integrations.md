Conduit’s site lists 43 integrations across CRM, channel managers, collaboration, messaging, PMS, and task managers ([Source](https://www.conduit.ai/integrations)). Docs treat connections as workspace work: channels first, then PMS and other sources that feed Knowledge and tools for [AI Agents](#knowledge/product-agents) ([Source](https://docs.conduit.ai/)). A logo is not proof that every account needs, or receives, every connector or write action.

## Integration map

Qualify four evidence types separately: marketplace cards, official setup docs, product claims about agent actions, and [developer](#knowledge/product-developers) API/MCP surfaces.

**PMS and related systems**

| System | Public list | Messaging via this connector (docs) | Other claim |
| --- | --- | --- | --- |
| Guesty, Beds24/Bed24, Hostaway, Hostfully, Hostify, Lodgify, OwnerRez, Resly, Smily | Marketplace + PMS docs | Messaging PMS: keep OTA messaging on the PMS or threads can duplicate | Guesty card: sync reservations and centralize Guesty messaging ([Source](https://www.conduit.ai/integrations/guesty)) |
| Hospitable, PassTheKeys | PMS docs only | Messaging PMS | Absent from the 43-card scrape ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)) |
| Apaleo, Cloudbeds, Escapia, HomHero/Homhero, Mews, Opera Cloud, RMS/RMS Cloud, Streamline, Track | Mix | Non-messaging: property/reservation data; message via auxiliary OTAs | Track’s card mentions Airbnb/Booking.com routing, but setup docs classify Track as non-messaging PMS sync. Confirm the actual separate OTA messaging path; neither the card nor a coming-soon directory label settles current availability ([Source](https://www.conduit.ai/integrations)) |
| CiiRUS, Kross Booking | PMS docs only | Non-messaging | Not on the marketplace scrape ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)) |
| StayNTouch | Marketplace only | Not in the docs table | Card claims two-way write-back ([Source](https://www.conduit.ai/integrations)) |
| Airbnb as PMS | Docs + Airbnb card | Separate Airbnb rules | Card: messages, support, reservation modifications ([Source](https://www.conduit.ai/integrations/airbnb)) |

Docs say Conduit integrates with over 15 PMS systems to populate listing information, create contacts from reservations, and show listings in Knowledge after sync ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)). Opera Cloud’s page matches the non-messaging class: property, room type, reservation, and profile sync; messaging stays on existing hotel channels ([Source](https://www.conduit.ai/integrations/opera)). Wheelhouse is listed as dynamic pricing, not a PMS path ([Source](https://www.conduit.ai/integrations)).

**Messaging channels**

| Channel | Evidence | Role |
| --- | --- | --- |
| Email, WhatsApp, phone/SMS, widget | Start guide + connect docs | [Inbox](#knowledge/product-inbox) unifies email, calls, WhatsApp, social, and connected OTA threads ([Source](https://www.conduit.ai/product/inbox)) |
| Airbnb | Marketplace (Messaging + Channel Manager) + connect docs | Two-way send/receive claimed on the Airbnb card ([Source](https://www.conduit.ai/integrations/airbnb)) |
| Twilio | Marketplace | Unified calls and SMS ([Source](https://www.conduit.ai/integrations)) |
| LINE, iMessage, VoiceAI numbers | Docs index / VoiceAI guide | Not on the 43-card list ([Source](https://docs.conduit.ai/llms.txt)) |
| Booking.com, VRBO | Marketplace | Both “Coming soon” ([Source](https://www.conduit.ai/integrations)) |
| Expedia | Marketplace + PMS docs | Card: push availability, rates, reservations. Docs: support-managed Expedia *messaging* for non-messaging PMS such as Cloudbeds; inventory can stay on the PMS ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)) |

[Workflows](#knowledge/product-workflows) send through connected email, WhatsApp, and OTA channels ([Source](https://www.conduit.ai/product/workflows)).

**Ops, knowledge, API**

Marketplace names Slack, Asana, ClickUp, Airtable, HubSpot, Salesforce, Google Drive/Docs/Sheets/Calendar, Notion, Firecrawl, Cal.com, Calendly, GitHub, and Apollo.io ([Source](https://www.conduit.ai/integrations)). Docs add Microsoft Teams notifications, a V3 Marketplace for apps/templates, and Devices (locks, thermostats, sensors, cameras) as an add-on for agents, workflows, [Operator](#knowledge/product-operator), or MCP ([Source](https://docs.conduit.ai/llms.txt)). [Guest Portals](#knowledge/product-portals) mention compatible smart locks without naming vendors ([Source](https://www.conduit.ai/product/portals)). REST (`https://api.conduit.ai/v1`) and MCP (`https://api.conduit.ai/v1/mcp`) are v3-plan surfaces enabled via support; default limit 120 requests/minute/workspace, shared across REST and MCP ([Source](https://docs.conduit.ai/mcp/overview)).

## Direct versus relayed connections

Docs classify PMS connectors by whether *this* integration delivers guest messages—not by every feature the vendor sells. Messaging PMS (Beds24, Guesty, Hospitable, Hostaway, Hostfully, Hostify, Lodgify, OwnerRez, PassTheKeys, Resly, Smily): keep OTA messaging on the PMS. Non-messaging (Apaleo, CiiRUS, Cloudbeds, Escapia, Homhero, Kross Booking, Mews, Opera Cloud, RMS, Streamline, Track): connect each OTA messaging channel directly ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)).

Workspace rules: multiple PMS accounts only when they share the same messaging setup; messaging and non-messaging PMS cannot share a workspace; Airbnb as primary PMS blocks another PMS; Airbnb can sit beside a PMS, with messages either remaining on the PMS or matching to reservations when the PMS is non-messaging ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)). Cloudbeds + Expedia is the worked example: Cloudbeds can keep inventory, rates, availability, and reservation sync while Conduit support connects Expedia messaging; do not leave messaging on both paths ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)).

Marketing can disagree. The Mews card says teams can centralize guest messaging from Mews properties, while the PMS guide lists Mews as non-messaging ([Source](https://www.conduit.ai/integrations/mews)). The Expedia marketplace line about pushing availability is not the support-managed messaging path in docs. Treat cards as listings until setup docs confirm the path.

## Data and action boundaries

Product copy says agents handle voice, chat, email, WhatsApp, and connected OTA messages, and can “check bookings, make reservation changes, and create tasks through supported integrations,” with live PMS, knowledge, payments, and tasks as clusters—not a per-vendor matrix ([Source](https://www.conduit.ai/product/agents)). Inbox copy places stay history, booking details, and availability from connected PMS/OTA accounts beside the thread and names Mews, Opera, Booking, and Airbnb as examples ([Source](https://www.conduit.ai/product/inbox)).

Tighter documentation:

- PMS connect: listing/Knowledge sync, contacts from reservations, scheduled Knowledge refresh (daily–monthly), and “Check for new listings.” Auth differs (Lodgify API key; Beds24 invite code plus per-property webhooks; Opera Cloud via OHIP) ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)).
- Opera’s public page documents property/reservation/profile sync and no messaging through that connector. Other write actions are unestablished, not proven impossible ([Source](https://www.conduit.ai/integrations/opera)). StayNTouch marketplace copy is the supplied source that states two-way write-back for that PMS ([Source](https://www.conduit.ai/integrations)).
- Workflows may use webhooks or MCP ([Source](https://www.conduit.ai/product/workflows)). Workflow credit docs price Slack, Teams, HubSpot, Salesforce, Airtable, webhooks, and channel sends—evidence those builder actions exist, not prices for this page ([Source](https://docs.conduit.ai/workflows/workflow-usage)).
- MCP: pin `workspace_id`; keep approvals on write tools (`send_`, `patch_`, `create_`, `update_`, `delete_`); pass idempotency keys; use least-privilege tokens. The ChatGPT/Codex plugin is five read-only tools, not the full catalog ([Source](https://docs.conduit.ai/mcp/overview)).
- Bring-your-own Twilio VoiceAI needs webhook `https://api.conduit.ai/twilio/messaging`, A2P 10DLC, and SMS enabled, or inbound SMS fails ([Source](https://docs.conduit.ai/setting-up-conduit/connect-voiceai-ai-number)).

Do not infer that every logo supports reservation edits, payments, tasks, or lock control.

## Implementation checklist

Public start-guide order ([Source](https://docs.conduit.ai/)):

1. Create the workspace (PMS UI may require Short Term Rental, Long Term Rental, or Hotel settings) ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)).
2. Invite members; decide who can manage agent settings.
3. Connect channels that apply; then PMS/data sources.
4. Import listings; enable PMS Knowledge auto-sync; use Sync history and Check for new listings.
5. Configure V3 agents, Knowledge, Skills, and Tools (connection tools, custom code, MCP, per-agent overrides).
6. Set inbox routing so new channel contacts do not sit in Unmapped; routing runs before workflow triggers ([Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing)).
7. Sandbox-test with listing and reservation context; expand writes via Connect → Teach → Test → Deploy.
8. Confirm support-enabled REST/MCP access; the documentation’s “v3 plan” wording is not mapped to public package names. Do not equate a V3 interface or Full Suite with automatic API access. Confirm Devices or Portals entitlements before those tool groups.

Ownership issues the sources actually raise: duplicate OTA threads if messaging is dual-routed; mixed PMS types blocked in one workspace; Expedia messaging provisioned with Conduit support rather than workspace credentials; MCP send misfires if clients allow-list write tools; Twilio SMS dropped without A2P; Lodgify API access may be gated on Lodgify’s plan ([Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)). Sources do not document SLAs, RACI, or security-review checklists.

## Unknowns and discovery questions

There is no published matrix of per-PMS writes (modify reservation, take payment, create a task). StayNTouch, Hospitable, PassTheKeys, CiiRUS, Kross Booking, LINE, and iMessage appear on different lists. Booking.com and VRBO were “Coming soon” on the scraped catalog. The Portals FAQ “How does Portals work with my PMS and booking channels?” is unanswered in the supplied HTML. Marketplace Email/WhatsApp blurbs still say HostAI. Confirm live connector status, message path, and allowed writes against the operator’s actual PMS and OTAs.