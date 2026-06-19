# 2026-06-19 — Decision: reuse_scope classification foundation → defer to M6 (ENG-165)

## TL;DR decision
The cross-tenant `reuse_scope` classification hardening is a **real but not-yet-active risk**. We
chose **Option A: file it, build it as the FIRST step of M6** (the first claim-writer), and move on
to M4 now. Tracked as **ENG-165** (M6 milestone, High; blocks ENG-133 + ENG-138). We deliberately
did **not** build it early in M3 — that would be speculative plumbing nothing reads yet.

## The risk (plain)
M2.5 makes cross-tenant reuse a property of the claim row: `reuse_scope ∈
{public_footprint, tenant_private}` + `tenant_id` (present iff private). Tenant read = public(any) ∪
this tenant's private; never another tenant's private. `identity.classify_reuse_scope(field_key,
extraction_method, source_tier)` stamps it before `insert_claim`. Two fail-open weaknesses:
1. `reuse_scope` **defaults to `public_footprint`** — an unstamped claim is world-readable.
2. The private rule is a **namespace-prefix deny-list** in `ReusePolicy` (`tenant_private_prefixes =
   ("contact.", "account.resonance.", "account.scoring.")`, `tenant_private_methods = ("crm_import",)`),
   decoupled from the field registry. Anything not listed → public. So **every `<pack>.*` field
   defaults public**, and the policy names `account.scoring.` private but **no field actually
   registers that key** — the agreement is unenforced.

Leak classes (when writers ship): client-tuned fit/intent **scores**, **value-narrative** reasoning,
**personal/contact/facet/resonance** data — any could land in the shared base other clients read.
Silent (no test fails) until a privacy/competitive incident.

## Why deferring is safe (zero added risk)
Nothing in M0–M3 writes claims. M3 authors `field_definition`/config; the compiler is pure; M3.4's
`score()` is pure over `current_value` (M6 runs it and writes). Exposure begins exactly at the first
`insert_claim` callers: **M6** (ENG-133 discovery-provenance, ENG-138 Pass A scores), then M8/M11/M12.
The enforcing **write guard lives in M6 anyway**, and at M6 we'll have the real write path in front
of us instead of guessing. So the cheapest correct moment to build the foundation is M6's first step.

## The work (captured in ENG-165) — W1..W6
- **W1** declare `reuse_scope` on `FieldDef`/`field_definition` (extend like M3.2's `signal_class`);
  packs + core pack set it per field; classifier reads declared scope first, prefix heuristic = fallback.
- **W2** one shared `(FieldClass, pass_kind, signal_class) → ReuseScope` mapping in `core` (M2 + M3
  both import it; neither imports the other). `<pack>.*` has no safe default → must be declared.
- **W3** surface scope on the compiled `FieldPlan` (+ `public_fields`/`tenant_private_fields`).
- **W4** register `account.scoring.fit`/`.intent` (or chosen keys) as `tenant_private`; M6 writes
  scores under exactly those keys with `tenant_id = client_id`.
- **W5** fail-closed: pack/field authoring + the M6 write helper require an explicit resolved scope
  (no silent public default).
- **W6** harmonize `client_id` (M3) ↔ `tenant_id` (M2) at the write boundary.

## Cross-refs
- ENG-165 (the tracked issue). Cross-cutting finding #1 in `2026-06-19-m2-m3-integration.md`.
- CLAUDE.md / AGENTS.md → "Backlog / known caveats" → reuse-scope bullet.
- Code: `identity/reuse.py` (`classify_reuse_scope`, `stamp_reuse`), `identity/policy.py` (`ReusePolicy`).
