# 2026-10-17 — WVI-5 visitor intelligence architecture and build plan

Branch `feature/visitor-intelligence` cut from origin/research-streaming @ 61f9d1bf9 (alembic head ddf063300a0b);
WVI-1..4 + research briefs cherry-picked over. Plan: docs/specs/WVI-5-visitor-intelligence-architecture-and-build-plan.md.

Founder model (2026-10-16): all landing pages live in Clue (Clue address by default, customer custom domain once
connected); one Clue snippet, auto-injected on Clue pages, pasted via GTM/<head> on the customer's own site;
deterministic ID = snippet + personal tracked link/QR + UTMs; scope = target accounts' committees; Slack + in-app alerts.

Verified seams (three read-only code maps): design-API /w/ routes are gone, page_origin is the only serving path;
CSP connect-src 'none' + form-action 'none' pinned byte-exact and baked into revisions -> beacons as same-origin
image GETs (no CSP change); GET/HEAD only at edge and origin; page HTML is stored bytes (serve-time injection is
trivial); worker forwards all headers but stamps no trusted client IP; registrable_domain() gives the parent
domain (custom hostnames only; system hostnames must use host-only cookies); BindingSet.links/url_qr QR chain
exists but nothing fills links.*.url; no Slack/OAuth/integration/encrypted-token code exists; no chart library;
account_activity_event kind CHECK needs 'visit'; committee source = arv2/display/gather.py committee_members;
targets = project_account. Rulings R1-R7 pending (Aryan). Rough size 3-4 weeks for one engineer.
