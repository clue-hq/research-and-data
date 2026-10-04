# 2026-10-03 — WVI-4: how anonymous visitor identification really works

Founder brief: build person-level identification of ANONYMOUS visitors in-house (no resold vendor UI);
deterministic snippet + tracked-link/UTM layer already accepted. Rejected: any visitor-facing step
(e.g. "Continue with LinkedIn" button).

Five parallel research briefs written to docs/specs/_research/wvi-4/01-05; synthesis in
docs/specs/WVI-4-how-anonymous-identification-really-works.md.

Key facts: Ploy rents person-level from RB2B (trust.ploy.ai subprocessors: GetEmails / rb2b.com).
RB2B/Vector/Warmly/Customers.ai/Apollo scripts call LiveIntent (own distributor ids), the
a.usbrowserspeed.com "FXF" sync, TowerData/AtData; Leadpipe + AudienceLab serve an identical Delivr
script that injects Sovrn. Mechanism = third-party-cookie lookup of a hashed (usually personal) email,
then hash -> B2B profile. IP->email audited 16% correct (Truthset/CIMM Nov 2025).

Recommendation: build A (first-party layer) + B (own IP->company DB) + C (import HubSpot/Marketo/Mailchimp
bindings) now; D (direct upstream identity-network contracts feeding Clue's own resolver, with
committee + employer cross-checks) gated on rulings W18-W20; defer co-op (E) and publisher deals (F).
Open: founder rulings W18-W20; web search budget ran out late in agents 01/02/04/05 (noted in files).
