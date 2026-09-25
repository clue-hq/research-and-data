# 2026-09-24 — Website visitor identification (WVI): vendor study + feature proposal (no code)

Founder ask: study how RB2B / Ploy / Userled de-anonymize website visitors, how to find the person
on LinkedIn, how to attribute the visit (and other things) and hand it to a CRM later, and the
cheapest way to build it as a Clue feature. Deliverable: **`docs/specs/WVI-website-visitor-identification.md`**
(research + integration design + build order + open rulings W1–W9). Awaiting founder ratification.

## What the study established
- Every vendor is the same three-layer stack: deterministic first-party (tracked links, 1:1 pages),
  company-level reverse IP, person-level rented identity graph (consumer publisher network → hashed
  email → then a *second* B2B lookup that yields the LinkedIn URL). US-only for person-level; EU is
  company-level everywhere. Nobody "finds people on LinkedIn"; LinkedIn is a column keyed by email.
- Userled buys no person graph: tracked links (`ul_e={{email}}` plaintext in the URL) ranked above
  IP reveal (Clearbit/6sense). Ploy resells an unnamed graph with standard consent language. RB2B
  runs its own graph + Demandbase + a Pro+ B2B waterfall.
- Independent accuracy evidence is vendor-adjacent and 2–3× below vendor claims; must measure on
  our own site before selling.
- Legal 2026: CPRA B2B exemption gone; SB 690 (passed 28 Aug 2026, awaiting governor) removes the
  private pen-register CIPA claim from 1 Jan 2027 but leaves §631/632; EU person-level needs consent
  + ePrivacy. Doc D machinery (jurisdiction, use_class, lawful_basis, use gate, DSAR) fits; the repo
  has zero cookie/consent code.
- Prices: reverse IP $0.29–0.67/1k (ipregistry), ipapi.is DB $89/mo, Snitcher API custom; person
  reveal $0.10–0.30/ID (RB2B, Leadpipe; Leadpipe Platforms = API + 3-month POC, payload has
  `linkedin_url`); AI Ark `POST /v1/people/reverse-lookup` by email = 0.5 credit → LinkedIn URL;
  Apollo `people/match` accepts `hashed_email`.

## Repo facts verified (Explore agent, HEAD 9ae1b211b)
- No tracking/pixel/UTM/visitor/reverse-IP/consent code anywhere.
- Design API publishes per-account pages at `/w/{ws}/p/abm-<slug>` (deterministic doc id); engine
  `BindingSet.audience{account_id, contact_id}` + `InstanceLink` + `UrlQr` slot exist unwired.
  Published-page CSP is `connect-src 'none'` and the sanitizer strips scripts → collect server-side.
- Inbound webhook pattern = `ExaWebhookIngestor` (HMAC, enqueue-only). No inbound rate limiter.
- Contact strong keys `linkedin_url`/`verified_email` (workspace-scoped); no email-hash key; no
  email→person resolver. `FleetTaskKind` closed enum (ALTER TYPE precedents). `run_event` subject
  kinds closed. Activity tab kinds closed (3 values) over `research_subject_activity`; ARV2 D1 adds
  `account_activity_event`. CRM connector is read-only duck-type, unwired.

## Proposal shape (spec §4–§7)
Identification ladder: rung 0 Clue links (opaque signed `?cl=` token, never PII) → rung 1 reverse
IP (server-side on Clue pages, `clue.js` on client sites) → rung 2 identity-graph reveal gated to
US + consent + target account/intent page + monthly cap, then AI Ark reverse lookup → contact
bind. One migration (`visitor_link`, `web_visit_event`, `visitor_resolution`, fleet kind
`visitor_resolve`, activity kind `visit`, fields `account/contact.web_engagement`), three source
manifests behind the `Resolver` protocol, claims via `insert_claim`, CRM via the handoff-style
outbox. V0 needs no vendor. Per 10k visits: reverse IP $3–7, gated person-level $21–63 vs RB2B
$149–199 ungated.

## Not done / follow-ups
- No code, no migration, no `.env.example` change. Founder rulings W1–W9 open.
- Provider choice for rung 2 unproven; run the known-visitor test on cluehq.ai first (V2 gate).
- `pricing-strategy/` stays uncommitted by founder instruction; this note + the spec are committed.
