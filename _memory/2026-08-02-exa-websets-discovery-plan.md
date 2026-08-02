# 2026-08-02 — Exa Websets durable discovery plan

Branch `platform/c8-exa-sumble-discovery`, created from `platform/c8-context-card`. Planning/docs
only; provider and backend implementation have not started.

Binding spec: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`.

Key rulings:

- discovery is a closed durable batch; `discovery -> scoring` requires an immutable batch seal;
- all provider operations, events, polling, pagination, reconciliation, identity dispositions,
  required-field attempts, receipts/artifacts, and costs must be terminal before sealing;
- reaching the requested row count, receiving an idle webhook, or completing a worker is progress,
  never discovery completion; only the transactional immutable seal permits Pass A;
- hard account identity requires canonical name + primary domain;
- LinkedIn company URL, industry, employee count/range, location, and revenue/revenue band require a
  terminal resolution per admitted account; honest missing/conflict is allowed, fabrication is not;
- company email/phone are optional discovery attempts;
- same exact request fingerprint within the observation window reuses the durable operation and
  snapshot with zero provider calls;
- Sumble committee discovery is allowed only after evidence-backed Pass A + human-approved eligible
  tier; no whole-list people search;
- Sumble signals, Priority Signals, and Intelligence Briefs are explicitly deferred; and
- slices D0–D6 are sequential, with live provider and production-composition gates required where
  the slice touches Exa. Unit/fixture tests alone cannot close a provider slice.

No code or provider spend occurred in this planning session.
