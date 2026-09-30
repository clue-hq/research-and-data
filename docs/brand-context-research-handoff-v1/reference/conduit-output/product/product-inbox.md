## Overview

Conduit Inbox is the workspace where messages and calls sit so a hospitality team can see a guest in one thread, assign work, and take over from AI when a person is needed. Product copy describes it as bringing messages and calls into one workspace while agents automate routine work end to end and humans step in with full history. [Source](https://www.conduit.ai/product/inbox)

Site navigation lists Inbox separately from [AI Agents](#knowledge/product-agents), [Guest Portals](#knowledge/product-portals), and [Workflows](#knowledge/product-workflows): “Messages, calls and team handoffs in one place.” Docs still treat the inbox as the daily operating surface—unified threads per contact, with conversations flowing through Todo, Follow-Up, and Done, plus inline visibility into how an AI reply was produced. [Source](https://www.conduit.ai/pricing) [Source](https://docs.conduit.ai/) [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

## Who it is for

Conduit’s own FAQ names hotel teams, serviced-apartment operators, and short-term rental managers as the audience. [Source](https://www.conduit.ai/pricing)

Buyers are usually the leader accountable for guest (and often owner) communication quality and staffing: guest-services, CX, or operations. Users are the people in the queue—shift agents, specialists, and managers who tag, note, assign, and take over. Canbnb split Guest, Owner, and Vendor inboxes so the right team owned the right thread. Bocobay moved guest and owner communication after running WhatsApp, a separate support inbox, and Hostaway in parallel. Those are examples of how teams use the workspace, not a requirement that every account needs three inboxes. [Source](https://www.conduit.ai/customers/canbnb) [Source](https://www.conduit.ai/customers/bocobay)

## Capabilities and limits

Capabilities below are those the Inbox product and inbox docs actually describe. Adjacent products (agents, workflows, portals) should not be sold as Inbox features.

| Area | What sources describe | Bound / unknown |
| Channels | SMS, WhatsApp, email, calls, social messages, and connected OTA threads in one workspace; docs also name voice, Airbnb, live-chat, Messenger, Instagram, widget, LINE, and Slack as routable channels | Booking.com and VRBO are listed as coming soon on the integrations directory |
| Team coordination | Tag teammates, internal notes, assign without switching tools; views by team or property; round-robin or custom assignment rules | Channel routing rules apply only to new, unmapped contacts |
| Handoffs | Agents pass requests with conversation history; humans can review the guest request and the agent’s replies before responding; inline approve, edit, or teach | The product FAQ “How much guest messaging can Conduit automate?” is unanswered in the supplied page text |
| Stay context | Stay history, booking details, and availability from connected PMS and OTA accounts next to the conversation | Opera Cloud syncs property/reservation/profile data but does not route guest messaging through that integration |
| Daily queue | Sort/filter and triage views; Todo / Follow-Up / Done | Contacts with no routing rule land in Unmapped and need a manual move |

[Source](https://www.conduit.ai/product/inbox) [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing) [Source](https://docs.conduit.ai/overview/how-conduit-agents-work) [Source](https://www.conduit.ai/integrations) [Source](https://www.conduit.ai/integrations/opera)

## Workflows and use cases

**Before/after (Wynwood House; customer story says using Conduit since October 2025).** Before Conduit, CX agents drafted in ChatGPT, messaged in Guesty, translated in separate tools, and scored sentiment in Google Sheets. Guests waited an average of 14–15 minutes for resolution, and shift handoffs meant rereading entire threads. After go-live, drafting, translation, sentiment, tagging, internal notes, follow-ups, and guest messaging were centralized in one inbox; agents used AI summaries and worked the solution. The same story reports resolution time down to 3 minutes from 15 while the company operated across seven countries. That is Conduit’s attributed outcome for consolidating communication—not an Inbox-only controlled experiment. [Source](https://www.conduit.ai/customers/wynwood-house)

**Channel collapse (Bocobay).** The co-founder described dual inboxes as painful (WhatsApp, a separate support inbox, Hostaway). Migration was sequenced: email, then WhatsApp, then phone, then live chat, so notes and tagging lived on one thread. [Source](https://www.conduit.ai/customers/bocobay)

Inbox routing runs before [Workflows](#knowledge/product-workflows) triggers, so automation must target the *routed* inbox, not Unmapped. Inbox does not replace PMS inventory, payments, or portal upsells in [Guest Portals](#knowledge/product-portals).

## Integrations and setup

Setup is a connection path, not a logo wall:

1. Create the workspace, invite members, set roles under Settings > Members. [Source](https://docs.conduit.ai/)
2. Connect channels you actually reply on (email, WhatsApp Business, business phone/SMS, widget, Airbnb, LINE, and others documented). [Source](https://docs.conduit.ai/)
3. Connect PMS at Settings > Connections > PMS so listings and reservations sync and contacts can be created from bookings. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms)
4. Add Inbox Routing rules (Settings > Inbox Routing) by channel—SMS/WhatsApp/voice number, email account, Facebook page, Instagram account, widget, Slack, helpdesk—or new contacts stay Unmapped. [Source](https://docs.conduit.ai/setting-up-conduit/inbox-routing)
5. Optional: Slack or Microsoft Teams for notifications rather than as the system of record.

PMS messaging class is a design constraint. Messaging PMS connections (including Beds24, Guesty, Hostaway, Hostfully, Hostify, Lodgify, OwnerRez, Resly, Smily) send guest messages into Conduit; keep OTA messaging through the PMS or the same conversation can arrive twice. Non-messaging PMS connections (including Apaleo, Cloudbeds, Escapia, Mews, Opera Cloud, RMS, Streamline, Track) supply property and reservation data only; OTA messaging needs a direct channel connection. Airbnb has its own primary-PMS vs additional-messaging rules. Guesty marketing copy says messaging from Guesty properties can centralize in one inbox; Opera Cloud marketing says existing hotel channels handle outbound contact. Those routes are not interchangeable. [Source](https://docs.conduit.ai/setting-up-conduit/connect-pms) [Source](https://www.conduit.ai/integrations/guesty) [Source](https://www.conduit.ai/integrations/opera)

## Pricing and packaging

No standalone Inbox price is published. Unified inbox is listed inside the Messaging package. Starting rates are shown; the page says pricing scales beyond 50 listings and that plans should be mapped with an expert. [Source](https://www.conduit.ai/pricing)

| Package | Starting rate (published) | Credits | Inbox-relevant inclusions listed |
| Messaging | $18 / unit / mo | 40 / unit / mo | Unified inbox, every channel; Voice AI inbound and outbound; PMS and OTA integrations; Operator, workflows, escalation; analytics |
| Guest | $30 / unit / mo | 60 / unit / mo | Everything in Messaging plus portals |
| Guest + Devices | $36 / unit / mo | 80 / unit / mo | Everything in Guest plus devices |
| Full Suite | $48 / unit / mo | 100 / unit / mo | Talk to Sales; operations items listed |
| Startup, 0–25 units | $899 / mo | 2,000 / mo | Full feature set, no implementation fee |

Whether Inbox can be bought without Voice AI or workflows is not stated. Bundle price is not an Inbox-only price. See [Pricing & packaging](#knowledge/pricing).

## Differentiation

Attributed, not guaranteed:

- Product page: stay/booking/availability beside the thread, plus calls and OTA threads with team handoffs. [Source](https://www.conduit.ai/product/inbox)
- Bocobay left Intercom; Nick Curtis is quoted that they needed guest, owner, and on-the-ground ops in one place, and that Conduit was “as good as anything we’ve used before, but finally tailored to hospitality.” [Source](https://www.conduit.ai/customers/bocobay)
- The Flex’s CEO said that on day one Conduit already looked ahead of Front, Zendesk, and Trengo, and that those tools still felt like “flow bots” on AI. That is one operator’s comparison, not a bake-off. [Source](https://www.conduit.ai/customers/the-flex)

Footer “Conduit vs.” names (Canary, Akia, Zendesk, Intercom, and others) are not win-rate evidence.

## Customer evidence

Use stories that describe the inbox workspace. Do not move Haven’s 90% automation or Lauderdale’s asset-value math onto this product.

- **Wynwood House** (since October 2025): unified inbox replaced a multi-tool CX stack; reported resolution 14–15 minutes → 3 minutes; AI handoff summaries. The 4.8 Airbnb rating in Colombia is in the same story, not isolated to Inbox. [Source](https://www.conduit.ai/customers/wynwood-house)
- **Bocobay** (since June 2024): explicit “one inbox, not two”; notes/tagging for handoffs; owner comms centralized. Hero “80% resolution rate” and “100s hours saved” are page metrics without a method that ties them solely to Inbox. [Source](https://www.conduit.ai/customers/bocobay)
- **Canbnb** (since March 2024): structured inbox and dedicated Guest/Owner/Vendor queues after a 630-unread-message morning; Hostaway + WhatsApp + email + SMS + widget. “~1,500 messages per week, 60% handled by AI” mixes agent automation with inbox operations. [Source](https://www.conduit.ai/customers/canbnb)
- **The Flex** (since December 2023): named a unified inbox with phone and messaging, tagging, and call summaries. 70% / 90% automation figures in that story describe guest-support automation, not Inbox packaging. [Source](https://www.conduit.ai/customers/the-flex)

More proof patterns: [Customer evidence & usable proof](#knowledge/customer-evidence).

## Sales discovery

1. How many inboxes do agents open today (PMS, WhatsApp, email, OTA, phone, Intercom/Zendesk), and which threads duplicate?
2. Is the PMS in the *messaging* class (messages through the PMS) or *non-messaging* class (direct OTA/channel connects required)?
3. Who takes over from AI—by property, shift, or guest vs owner vs vendor—and is assignment round-robin or named?
4. What must sit next to the thread (reservation, availability, stay history), and which PMS/OTA actually syncs it?
5. At shift change, do agents reread full threads, or do they need notes/summaries?
6. After hours, must calls land in the same workspace as SMS/WhatsApp?

**Next step:** run a demo on one live guest across SMS or OTA *with* PMS context, then sketch routing so new contacts never sit in Unmapped. Map listing count to Messaging ($18/unit/mo starting, 40 credits) versus Startup ($899/mo, 0–25 units). Pair with [Integrations & implementation readiness](#knowledge/integrations).