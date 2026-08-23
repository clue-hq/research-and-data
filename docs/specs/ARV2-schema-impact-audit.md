# ARV2 — Schema-impact audit (the "are we modifying any schemas?" document)

**Status:** review document for the founders, 2026-08-23. Companion to
`ARV2-deep-agent-build-runbook.md` (the execution plan) and `ARV2-apollo-api-contract.md`
(the Apollo wire-schema deep dive).

**Ruling this document defends: ARV2 ships with ZERO database schema changes.** No new tables, no
ALTERs, no new Alembic migration, no enum changes, no CHECK/trigger edits. The Alembic head stays
`612428f3731f` (the current head of `platform/comprehensive-account-contact-research`). Everything
ARV2 adds is: **data rows** (field registry, source manifests, run/job/claim rows), **versioned
catalog files** (agent prompts/skills/profiles), and **new code modules**. The one place "schema"
is touched at all is application-level (a handful of new config flags and one frozen test fixture),
and each instance is documented in §6.

---

## 1. What "schema" means here — the five surfaces, and what ARV2 does to each

| # | Schema surface | Owner | ARV2 action |
|---|---|---|---|
| 1 | **Database schema** (tables, columns, CHECKs, triggers, enums, Alembic chain) | Alembic migrations | **Untouched.** Zero migrations. §2–§4 prove the writes fit the existing constraints. |
| 2 | **Field registry** (`field_definition` rows: key, value_schema, description, reuse_scope…) | `register_field` / pack loaders | **Rows added, schema unchanged.** Registering the ARV2 dossier pack is `INSERT`s through the existing loader — the registry was designed to be extended this way ("open by registration, not enumeration"). §5 lists the rows. |
| 3 | **Source manifests** (`sources/seeds.py` entries: source_key, tier, cost, auth_ref) | seed data in code | **Entries added** (`exa_search`, `exa_research`; the existing `apollo` entry's `yields` extended). Data-in-code, reviewed like data. One frozen test fixture moves (§6.3). |
| 4 | **Pydantic/typed contracts** (`clue_core` models: Claim, FieldDef, enums) | frozen `core` | **Untouched.** ARV2 constructs existing types with existing enum values only. No contract-delta. |
| 5 | **Frontend contracts** (Zod schemas, `/frontend/v1` payloads) | `apps/frontend` + FI specs | **Untouched.** New research fields ride the existing generic `fieldKey` rendering (`neutralFacts`, `projectSections[].insights`, `professionalFacts`). No new endpoint, no Zod change. |

---

## 2. The claim table: every constraint that can reject an ARV2 write, and how each is satisfied

This is the section that prevents the "mechanical failures coming again and again" experience from
returning as raw `IntegrityError`s. The `claim` table carries ~14 CHECKs/triggers. For each, the
left column is the constraint (with its migration of origin); the right column is the ARV2 write
rule that satisfies it **by construction**. The `write_claims` tool pre-checks every rule in Python
and returns a per-item, actionable refusal — a DB constraint firing at runtime is defined as an
ARV2 bug.

| Constraint (migration) | ARV2 write rule |
|---|---|
| `claim_source_tier_range` 1..4 (0002) | Tier comes from a fixed per-tool stamp (§3), never from the model. |
| `claim_confidence_range` 0..1 (0002) | Clamped in the tool. |
| **`claim_tier4_iff_synthesis`** — tier 4 ⟺ `extraction_method='llm_synthesis'`, biconditional (0002) | Anything the agent authors (extracts, summarizes, infers) is stamped `tier=4 + llm_synthesis`. Anything a deterministic adapter normalizes (Apollo, NPI) is `tier=1 + api`. There is no third case. |
| `claim_tier4_verified_requires_span` (0002, re-cut by 0ac041814c56) | Fires only on `VERIFIED`. ARV2 claims are **born `UNVERIFIED`** and nothing in the lane promotes them, so it can never fire. (We still write verbatim quotes into `evidence_span` for every quoted fact — as product value, not to satisfy a gate.) |
| `_URL_REQUIRED_METHODS` model validator — `api`/`scrape`/`llm_synthesis` require `source_url` (`clue_core/claim.py:54`) | `write_claims` requires `source_url` on every item; refusal names the missing field. |
| **`claim_contact_field_requires_governance`** — `contact.facet.*` requires `identity_binding` AND `use_class` (0004) | The tool's schema makes both **required parameters for facet fields** (§3 stamping matrix); a facet item without them is refused in-tool with the exact fix. |
| `claim_discovery_requires_provenance` / `claim_field_claim_no_discovery` (0004) | ARV2 deep-research claims are plain FIELD flavor; discovery claims are written only by the (existing) discovery path. The tool hardcodes `claim_flavor=FIELD`. |
| **`claim_reuse_scope_workspace`** — `public_footprint` ⟺ `workspace_id IS NULL` (0008/b61cd4887129) | ARV2 stamps **every** claim `reuse_scope=tenant_private` + the job's `workspace_id`. (A claim more private than its field is always allowed; post-B3 there is no cross-tenant reuse to preserve.) |
| `claim_product_requires_private_scope` / product FK (1b71451d48cd) | `product_id` stamped from the run's pinned product (already on `ProjectRunRow`); private scope holds per the row above. |
| `claim_external_research_lineage_shape` — the three `source_*_ref`s are all-or-none, and any ref ⇒ `artifact_key` (2e6920101a1b) + `claim_external_research_lineage_validate` trigger (fa28c91abc3c) | ARV2 writes either **no refs** (agent-authored claims citing a URL) or the **full triple + artifact** (claims materialized straight off a persisted provider snapshot). The tool exposes exactly those two shapes; a partial triple is unconstructable. |
| **`claim_exa_deep_lineage_required`** — `source_key='exa_deep'` ⇒ full triple + artifact (f9281fac77e1) | **ARV2 does not reuse the `exa_deep` source key.** New keys `exa_search` / `exa_research` (§3) — this provider-specific CHECK is scoped to the literal string and therefore never applies. This is the main "schema mix-up by source_key" trap and the reason for new keys. |
| **`claim_sumble_professional_shape`** + DB-join lineage trigger (26eaa6262063) | Scoped to Sumble source keys / professional fields. ARV2 writes no `sumble_*` source keys — never applies. |
| `claim_artifact_key_fk` → `artifact.storage_key` (d091e3962833) + `claim_artifact_scope_compatible` (d0c2e361f7d4) | `artifact_key` is only ever stamped from a snapshot the same job just persisted through the existing B2 storage path (same workspace) — FK and scope hold by construction. |
| Append-only triggers `claim_no_immutable_update` / `claim_no_delete` | ARV2 never UPDATEs a claim; corrections supersede (`superseded_by` via the existing writer). |
| `check_claim_writable` (code, `claimstore/registry.py`) — field registered, value matches `value_schema`, resolvable reuse scope | The tool resolves the `FieldDef` first and validates the value against `value_schema` **before** insert; violations return as the tool refusal. Unregistered field → refusal listing the nearest registered keys. |

**Conclusion:** a correctly stamped ARV2 claim cannot trip any existing constraint, and no
constraint needs to be relaxed, added, or migrated for ARV2 to write everything the dossiers
contain.

## 3. The stamping matrix (normative)

| Origin tool | `source_key` | tier | `extraction_method` | born status | reuse_scope / ws | Notes |
|---|---|---|---|---|---|---|
| `apollo_org` / `apollo_contact` (adapter-normalized values) | `apollo` (existing seed: tier 1, `CLUE_APOLLO_API_KEY`) | 1 | `api` | UNVERIFIED | tenant_private + ws | `source_url` = the Apollo record URL per the corrected contract (`ARV2-apollo-api-contract.md`). |
| `lookup_registry` (NPI/DUNS/CIK/LEI) | existing registry keys | 1 | `api` | UNVERIFIED | tenant_private + ws | Public registries; strongest identity anchors. |
| Agent-authored claim grounded in a fetched page (quote in `evidence_span`) | `exa_search` (new seed) | 4 | `llm_synthesis` | UNVERIFIED | tenant_private + ws | The tier-4⟺synthesis CHECK forces tier 4 for anything the model authored; tier is provenance metadata, not authority, in this lane. |
| Agent-authored claim from an Exa deep-research report | `exa_research` (new seed) | 4 | `llm_synthesis` | UNVERIFIED | tenant_private + ws | Full lineage triple + artifact when written off the persisted snapshot. |
| Role/committee inferences, derived summaries | `exa_search` or `exa_research` per grounding | 4 | `llm_synthesis` | UNVERIFIED | tenant_private + ws | Rationale goes in `evidence_span` context; provenance kind marks platform/LLM derivation per the existing `ClaimProvenanceKind` vocabulary. |
| **Facet claims** (`contact.facet.*`), any origin | as above | as above | as above | UNVERIFIED | tenant_private + ws | **Plus mandatory:** `identity_binding` (STRONG only after the agent's identity-confirmation step against a primary source; WEAK otherwise — WEAK never drives outreach) and `use_class` from the category map: professional → `professional-public`; hometown/alma mater/hobby/pet → `personal-public-non-sensitive`; faith/health/politics/family tragedy → `sensitive` (recorded, excluded from outreach by the existing hard floor). |

Additionally every claim: `run_id` = the entity-research run, and a `record_run_lineage` call —
this is what makes the claim appear in the frontend's project-scoped sections (`run_lineage` is
the FI-2 join the account screens read). Skipping it makes research invisible; it is part of the
write, not an option.

## 4. Database objects ARV2 reuses vs leaves dormant (all unchanged either way)

**Reused (rows written, schema untouched):** `fleet_task` + work-lease tables;
`entity_research_run`, `entity_research_job`, `_job_wait`, `_job_event`, `_job_finalization`;
`entity_research_agent_turn`, `_agent_event`; the LangGraph `AsyncPostgresSaver` checkpoint
tables; `external_research_operation` / `_snapshot` / `_receipt` / `_result_artifact`; `artifact`;
`claim` (+ `run_lineage`); `account_entity` / `contact_entity` via the existing identity writers;
`field_definition` (+rows); the project-run tables (unchanged phases).

**Left dormant by ARV2 (not written, not read, not dropped):** `entity_research_tool_request`,
`_provider_operation`, `_provider_observation`, `_result*`, `_provider_settlement_fold`,
`_tool_batch*`, `_budget_reservation*`, `_provider_permit*`, `_account_coverage`,
`_account_committee_scope`, `_sumble_projection`, `entity_research_account_committee_unavailable`,
and every `sumble_*`/committee-acquisition table. These are the old lane's authority/settlement
machinery — the layer whose job-scoped folds and replayed-poison-call semantics produced the live
wedges. They stay in place untouched (dropping them would be a schema change and is Phase-6
cleanup, separately ratified). **Trade-off stated honestly:** ARV2 gives up the per-call
tool-request journal and R9 budget admission; it keeps what those existed to protect — paid-call
idempotency and evidence durability — via the `external_research` snapshot family, and turn-level
replay via the R3 journal + checkpointer.

## 5. Field-registry additions (data rows, listed for review)

New pack module (code file registering rows; no DB DDL): the ARV2 dossier pack.

- Account: `account.ownership_structure`, `account.owned_facilities`, `account.locations`,
  `account.expansion_path`, `account.timing_signals`, `account.ad_audience_feasibility`,
  `account.research_audit` (the link-audit annotation). Existing rows reused as-is:
  the 21-field profile's `core.*`, `account.operational_pain`, `account.strategic_moves`,
  `account.resonance.*`.
- Contact: existing 15-field profile + `contact.facet.awards`, `contact.facet.board_roles`,
  `contact.facet.memberships`, `contact.facet.openers`, `contact.research_audit`.
  (Postal address / Melissa is **deferred** out of the build — see the runbook §1.)
- Industry qualifiers (healthcare first): registered under the existing `HEALTHCARE_PRACTICE`
  pack namespace (e.g. EHR vendor, disqualifier flags, owned-ASC count) — each with
  `description` (agent-facing, per Aryan's requirement), `reuse_scope`, `research_scope`
  declared at registration, which `check_claim_writable` requires for `<pack>.*` keys.

Every row ships with a `description` — the registry column exists (`register_field(...,
description=)`); ARV2 additionally renders registry descriptions into the agent's field-catalog
resource so the model reads the same text (pydantic-class descriptions per Aryan's note).

## 6. The complete list of application-level "schema-adjacent" edits (each documented)

1. **`Settings` gains ARV2 flags** (`arv2_account_research_enabled: bool = False`, model id
   override). Additive pydantic fields with conservative defaults; the frozen-defaults tests
   (`tests/test_config_settings.py`) freeze *existing* defaults and are unaffected by additive
   fields. No env-schema break: `extra="ignore"`.
2. **`sources/seeds.py`** gains `exa_search` + `exa_research` entries and extends `apollo.yields`.
   This moves the frozen expectations in `tests/sources/test_source_manifest.py` — that file is a
   deliberate drift guard, and this is a deliberate, documented drift (same precedent as Slice-B
   task B3, which did exactly this for the 21-field profile). **This is the single existing-test
   edit in the entire build.**
3. **`.env.example`** gains the ARV2 flag lines. Documentation, not schema.
4. **No edits** to: any Alembic file, any `clue_core` model/enum, any old-lane module, any frozen
   agent-catalog version, any Zod schema, any `/frontend/v1` handler.

## 7. Testing impact (the "testing schema")

- **`make db-smoke` unaffected** — no migration, same single head `612428f3731f`.
- **Enum-parity tests unaffected** — no enum touched.
- **Frozen old-lane pins untouched** (R10 cutover manual pins, agent-registry aggregate digests,
  descriptor SHAs, replay-identity tests) because no old-lane file is edited. This is the concrete
  payoff of quarantine-don't-refactor: editing those files moves dozens of pinned digests for code
  we are abandoning.
- **New test modules (added, not edited):** `tests/arv2/test_write_claims_stamping.py` (the §2
  matrix — every constraint red-proofed against a throwaway DB: one test per CHECK proving the
  tool refuses *before* the DB would), `test_arv2_driver_db.py` (launch → fleet → turns → claims →
  finalization on the existing tables), `test_arv2_failure_species.py` (poison-call replay renders
  as a refusal tool-message; recursion cap pushes to finalize; unknown exception pauses-resumable),
  `test_apollo_contract.py` (recorded-fixture normalization per `ARV2-apollo-api-contract.md`),
  and the acceptance fixture `test_arv2_dossier_acceptance_db.py` keyed to the Digestive
  Healthcare of Georgia dossier sections.
- **Gate:** `make check` green with the suite additions; the one fixture drift in §6.2 lands in
  the same commit as its cause, per house rule.

## 8. Environment posture ARV2 requires (config, not schema)

`CLUE_PRODUCT_PATH=integration_pilot` (or explicitly `CLUE_VERIFICATION_ENABLED=false`): tier-4
UNVERIFIED claims then win `current_value` merges (the already-ratified pilot posture). The
`/frontend/v1` account/contact reads filter only `REJECTED` and serve UNVERIFIED regardless, so
the accounts screens work in either posture. No code change to any read path is in ARV2's build
scope (the C7 research-view governance change from the v1 plan is **dropped from scope** — that
surface has no consumer today).
