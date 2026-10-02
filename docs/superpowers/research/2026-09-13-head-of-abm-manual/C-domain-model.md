# C — Domain model: the vocabulary the Head-of-ABM agent must speak

Read-only study of `san-salvador` @ branch `research-streaming`, 2026-09-13. Every value below is
quoted from code or from the lane database (read-only `SELECT`). Nothing is inferred; where a thing
was looked for and not found, it says **not found** and where it was looked for.

Two spellings run through the whole system and must not be confused:

- **the platform substrate** (`libs/clue-core/clue_core/*`, `claim` table, `field_definition`) — the
  claim-with-provenance model, shared with the older research lane.
- **the ARV2 lane** (`platform/api/clue_api/arv2/*`, `arv2_*` tables) — the runs, jobs, discovery,
  display pages and documents this agent actually drives. ARV2's own rows are the only truth
  (founder ruling 2026-09-09); it writes into the shared `claim` table but has its own run/job
  vocabulary.

---

## 1. Claims

`Claim` lives at `libs/clue-core/clue_core/claim.py:94`. Closed taxonomies at
`libs/clue-core/clue_core/enums.py`. Every field below is a real column on `claim`
(verified against `information_schema`).

### 1.1 The claim row

| Column | Meaning | Source |
| --- | --- | --- |
| `id` | claim id (uuid) | `claim.py:108` |
| `entity_id` | the resolved account or contact it is about — never a free-text name | `claim.py:109` |
| `entity_type` | `account` \| `contact` | `enums.py:15` (`EntityType`) |
| `field_key` | the registered field this asserts (open registry, not an enum) | `claim.py:111`, `field.py:5` |
| `value_json` | the value, as JSON | `claim.py:112` |
| `source_url` | where a reader can go and check. Nullable since ARV2 D1 | `claim.py:113` |
| `source_key` | the registered source/resolver that produced it (`source_manifest.source_key`) | `claim.py:115` |
| `artifact_key` | content-addressed snapshot of the bytes the fetch saw, so the span resolves after link rot | `claim.py:122` |
| `source_operation_ref` / `source_snapshot_ref` / `source_request_ref` | provider-neutral acquisition lineage; all three born together or omitted, and require an `artifact_key` | `claim.py:127-129`, validator `claim.py:182-189` |
| `provenance_kind` | who asserted it, independent of transport | `enums.py:32` (`ClaimProvenanceKind`) |
| `source_tier` | 1–4, see §1.2 | `primitives.py:56` |
| `extraction_method` | `api` \| `scrape` \| `llm_synthesis` \| `human` \| `crm_import` | `enums.py:22` |
| `evidence_span` | the verbatim quote the value rests on. **Mandatory for tier-4 *promotion*, not construction** | `claim.py:136`, `claim.py:291` |
| `confidence` | resolver-reported 0..1 | `primitives.py:59` |
| `corroborations` | count of independent tier≤3 sources agreeing | `primitives.py:62` |
| `observed_at` / `collected_at` | when the source published / when we saw it. Freshness measures from `observed_at or collected_at` | `claim.py:139-140`, `reference_time` `claim.py:307` |
| `cost_cents` | spend attributed to producing it (`Decimal`, never float) | `primitives.py:66` |
| `run_id` | the run that produced it | `claim.py:142` |
| `research_mode` | which of the 2×2 modes produced it | `enums.py:47` |
| `superseded_by` | the claim that replaced it. Append-only: the **only** permitted mutation | `claim.py:144`, `claimstore/claims.py:11` |
| `identity_binding` | `strong` \| `weak`, contact claims | `enums.py:99` |
| `use_class` | governance class of personal data | `enums.py:90` |
| `claim_flavor` | `discovery` \| `field_claim` \| `derived` | `enums.py:107` |
| `discovery_provenance` | the admission-evidence envelope on a `discovery`-flavored claim | `claim.py:63` |
| `reuse_scope` | `public_footprint` \| `tenant_private` | `enums.py:304` |
| `workspace_id` | the tenant. A `tenant_private` claim always has one; a `public_footprint` claim never does | validator `claim.py:256-259` |
| `product_id` | product-scoped client truth; requires `tenant_private` + a workspace | `claim.py:161`, validator `claim.py:260` |
| `verification_status` | `unverified` \| `verified` \| `rejected` \| `flagged` | `enums.py:57` |
| `signal_priority` | 1 = active buying intent, 2 = qualifying fact, 3 = context. **Orders display items; never gates** | `claim.py:166` |
| `outreach_safe` | appropriateness, distinct from accuracy. `false` confines the claim to restricted display sections and bars it from outreach copy | `claim.py:169` |
| `write_markers` | lenient-write annotations (§1.8) | `claim.py:173` |

### 1.2 Source tiers (the trust waterfall)

`libs/clue-core/clue_core/primitives.py:54-56`. One integer, four meanings:

| Tier | Meaning | Source |
| --- | --- | --- |
| 1 | deterministic API | `primitives.py:54` |
| 2 | official-source scrape | `primitives.py:54` |
| 3 | reputable third party | `primitives.py:55` |
| 4 | LLM synthesis — last resort | `primitives.py:55` |

**Tier 4 ⟺ `llm_synthesis`** is enforced at construction: `source_tier == 4` and
`extraction_method is LLM_SYNTHESIS` must agree or the claim cannot be built
(`claim.py:210-217`).

Lane reality (`SELECT source_tier, extraction_method, count(*) FROM claim GROUP BY 1,2`):
tier 1/`api` 691, tier 1/`human` 12, tier 2/`scrape` 34, tier 3/`api` 1, tier 4/`llm_synthesis` 2644.
**The ARV2 lane is overwhelmingly tier-4.**

### 1.3 `verification_status`

| Value | Meaning | Source |
| --- | --- | --- |
| `unverified` | born state; not yet judged | `enums.py:65` |
| `verified` | corroboration / the faithfulness judge promoted it | `enums.py:66` |
| `rejected` | the judge or the use gate refused it; the merge drops it | `enums.py:67` |
| `flagged` | surfaced for human review (e.g. two authoritative sources disagree) rather than silently resolved | `enums.py:68` |

`can_be_promoted(claim)` (`claim.py:274`) is the **structural** precondition, three kill switches:
a tier-4 claim with no `evidence_span` (except `derived`); a contact claim with `WEAK` binding; an
`api`/`scrape`/`llm_synthesis` claim with no `source_url`. Returning `True` means *eligible*, not
verified.

Lane reality: **every claim on this database is `unverified`** except 9 `rejected` rows — because
`CLUE_VERIFICATION_ENABLED=false` in `.env`. Consequence for the display gate, §1.9.

### 1.4 `use_class` (Doc D §2)

| Value | Meaning | Source |
| --- | --- | --- |
| `professional-public` | public professional fact | `enums.py:94` |
| `personal-public-non-sensitive` | public personal, not special-category | `enums.py:95` |
| `sensitive` | special-category. **Excluded from outreach by default** and excluded from *every* display section, restricted ones included | `enums.py:96`; gate `display/gather.py:338-339,448-450` |

A `contact.facet.*` claim **must** carry both `identity_binding` and `use_class` or it cannot be
constructed (`claim.py:199-208`); a plain `contact.*` claim need not.

The use gate's closed reason vocabulary is `UseReason` — `allowed`, `sensitive_locked`,
`use_class_disallowed_for_regime` (`enums.py:525`). There is deliberately **no** `objected` reason:
an Art. 21 objection is a substrate exclusion (tombstone before the merge read), not a use verdict.

### 1.5 `identity_binding`

| Value | Meaning | Source |
| --- | --- | --- |
| `strong` | it is true *and* it is this person | `enums.py:103` |
| `weak` | same-name-only. **Never promotes, never drives outreach** | `enums.py:104`, `claim.py:296-298` |

### 1.6 `outreach_safe` and `signal_priority`

Both are ARV2 D1 additions on the claim row, not part of the older substrate.

- `outreach_safe: bool` — "appropriateness, distinct from accuracy" (`claim.py:168-169`). A
  `false` row reaches **only** a `restricted` display section, and is dropped entirely from
  `read_account_research(section="claims")`.
- `signal_priority: 1|2|3` — 1 active buying intent, 2 qualifying fact, 3 context
  (`claim.py:165-166`). It is the primary display sort key (`display/gather.py:459`) and **never a
  gate**.

Two registry fields are *born* `outreach_safe=false` by declaration:
`account.icp_fit_verdict`, `account.reputation_risk`, `account.media_transcript_quality_warning`,
`contact.facet.excluded_lookalike` (see their `field_definition.description`).

### 1.7 `reuse_scope`, `research_scope`, `product_scope`

| Enum | Values | Meaning | Source |
| --- | --- | --- | --- |
| `ReuseScope` | `public_footprint`, `tenant_private` | privacy/tenancy class. Since B3 it is **only** the privacy classification — the cross-tenant sharing grant was retired | `enums.py:304`; CLAUDE.md `[B3×research]` |
| `ResearchScope` | `project_neutral`, `project_relative` | field *species*: world-fact vs answer-relative-to-an-ICP/product. Drives economics and lens, never privacy | `enums.py:322` |
| `ProductScopePolicy` | `forbidden`, `required`, `optional` | may claims for this field carry a `product_id` | `enums.py:342` |

Defaults: `default_reuse_scope` (`field.py:217`) — `core`/`account` public, `contact`/`contact.facet`/`account.resonance` private, **`pack` has no safe default and must declare one**.
`default_research_scope` (`field.py:286`) — relative iff key starts `account.scoring.` or is one of
`account.value_narrative`, `contact.persona`, `contact.role_on_committee`; everything else neutral.
`default_product_scope` (`field.py:248`) — `client.*` is `forbidden`, everything else `optional`.

Lane reality: 153 of 161 `field_definition` rows have `research_scope` NULL (falling through to the
default), 6 `project_relative`, 2 `project_neutral`.

### 1.8 `write_markers` (the lenient write gate)

`platform/api/clue_api/arv2/claim_writer.py`. With `CLUE_CLAIM_WRITE_LENIENT=true` (set on this
lane), what a strict gate would refuse becomes a durable annotation instead of a dropped fact.
Markers the writer itself stamps: `identity_binding_defaulted` (→WEAK, `claim_writer.py:118`),
`use_class_defaulted` (→professional-public, `:120`), `source_missing` (`:128`),
`proposed_field` (`:148`), `schema_valid: false` (`:153`).

Markers actually present on this database (`jsonb_object_keys` over `claim.write_markers`), most
frequent first: `schema_valid` 938, `structuring_mode` 815, `source_kind` 750, `media_timestamp` 750,
`evidence_verbatim` 750, `source_missing` 747, `source_kind_block` 604, `json_path` 454,
`provider_record` 348, `answer_key` 294, `source_row_id` 291, `unevidenced` 202,
`discovery_run_id` 124, `company_domain` 122, `opener_hook` 111, `board_url` 106, `repaired` 75,
`corrects_claim_id` 69, `proposed_origin` 65, `redacted` 52, `proposed_field` 46, `pass` 42,
`icp_artifact_sha256`/`icp_artifact_key`/`gates` 42 each, `logo_kind` 38, `unique_insight` 36,
`backfill` 31, `provider_verified` 22, `verdict` 22, `source_url_corrected` 18, `speaker_verified` 15,
`media_person`/`media_kind`/`duration_s` 12 each, `provider_value` 9, `quoted_context` 7,
`pipe_joined_key` 6, `transcript_model` 6, `currency_assumed` 4, `dropped_null_keys` 3,
`derived_role_from_persona` 3, `proposed_field_origin` 3, `proposed_key_raw` 1,
`self_announced_milestone` 1, `coerced_from` 1.

There is **no closed schema** for `write_markers` — it is an open `dict[str, JsonValue]`
(`claim.py:173`).

### 1.9 Supersession, merge, and `merged_into`

- **Claims** are frozen and append-only. A new observation is a new row; the prior row's
  `superseded_by` is pointed at it — "the only permitted mutation"
  (`claimstore/claims.py:11`, `:256`, `:271`, `:301`).
- **Live claims** = `superseded_by IS NULL` plus a retention filter
  (`claimstore/claims.py:409-410`). ARV2 display and reads use *live claims*, deliberately **not**
  the merge: "the merge answers 'what is the current value of this field'; a page shows
  *everything the research found*, several rows of the same field included"
  (`display/gather.py:15-16`).
- **Entities** carry `merged_into` (`account_entity.merged_into`, `contact_entity.merged_into`). A
  merge loser is not a person and not an account: it is excluded from the project account list
  (`read_tools.py:174`), from `read_account_research` (`read_tools.py:359-364`), and from the
  committee (`display/gather.py:273`). Memberships are repointed onto the survivor by
  `repoint_project_accounts` inside the merge transaction (`membership.py:20-26`).

### 1.10 `ClaimFlavor`

| Value | Meaning | Source |
| --- | --- | --- |
| `field_claim` | the default — value + span + tier | `enums.py:120` |
| `discovery` | *admission* evidence: where an entity was found and why it matched. Carries `DiscoveryProvenance`; the merge never treats it as truth | `enums.py:119`, `claim.py:63` |
| `derived` | a C7 inference supported by an immutable ordered support-claim set + an entailment verdict. Must be tier-4, and must carry **no** `source_url` and **no** `evidence_span` | `enums.py:121`, validator `claim.py:240-251` |

### 1.11 The display gate — what the account page holds back, exactly

`platform/api/clue_api/arv2/display/gather.py:401-470` (`gather_section_inputs`). One
workspace-scoped read of the subject's **live** claims, then per-recipe filtering in Python.

Selection (`_candidates`, `gather.py:347-376`), in order:
1. If the recipe is `restricted` **and** `claim.outreach_safe is false` **and** the claim is on a
   subject entity → take it (a restricted section is not a field recipe; it exists to show the
   operator every fact they must not use).
2. Else if `field_key` is not in `recipe.allowed_field_keys` → drop.
3. Else route: a `contact.` key resolves over the *people* of the page (the committee on an account
   page, the subject on a contact page); every other key resolves over the *account*.

Exclusions (`gather.py:445-457`), in this order, each **counted**:

| Test | Rule | Counter | Source |
| --- | --- | --- | --- |
| special category | `claim.use_class is UseClass.SENSITIVE` → never enters **any** section | `excluded_sensitive` | `gather.py:338-339, 448` |
| unverified synthesis | **only if `settings.verification_enabled`**: `source_tier == 4 and verification_status is not VERIFIED` → held back | `excluded_unverified` | `gather.py:342-344, 451` |
| appropriateness | `not recipe.restricted and not claim.outreach_safe` → held back | `excluded_unsafe` | `gather.py:454` |

Then near-duplicates are folded **within one person or the account, never across two of them**
(`_dedupe_per_subject`, `gather.py:379-398`; two committee members legitimately share a title), and
survivors are ordered `(signal_priority, field_key, collected_at, claim_id)` (`gather.py:459`).

`SectionInput.empty` plus the three counters is the section's honest account of its own gaps: "a
section that renders empty because every row was special-category reads differently from one the
research never filled" (`gather.py:91-95`).

**On this lane `CLUE_VERIFICATION_ENABLED=false`, so the tier-4 test does not run** — every tier-4
synthesis claim is displayable. Only `sensitive` and `outreach_safe=false` hold anything back today.

`read_account_research` applies **the same predicates, predicate for predicate**
(`read_tools.py:437-445`), with one difference: it has no restricted section, so an
`outreach_safe=false` row is held back outright. Its `excluded` dict keys are `sensitive`,
`unverified`, `outreach_unsafe` (`read_tools.py:320-323`). "Exclusions are counted, not hidden."

The committee itself: contacts under the account that are not merged losers and hold **at least one
live claim**, ordered by persona rank then name then id (`committee_members`, `gather.py:283-332`).

---

## 2. The field registry

`field_definition` is the open registry that makes fields and verticals pluggable by registration
(`libs/clue-core/clue_core/field.py:5-13`; `FieldDef` at `field.py:151`). Columns actually present:
`field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate, field_class,
value_schema, corroboration_min, description, active, pack, version, created_at, signal_class,
reuse_scope, single_source_sufficient, equality_mode, research_scope, product_scope`.

**161 rows, all `active = true`. 139 distinct `field_key`s carry claims. 22 registry keys have no
claims. Zero claim keys are outside the registry** — because the lenient writer auto-registers a
proposed key (`claim_writer.py:148`), so a "pack field" never stays unregistered here.

`pass_kind`: 111 `deep`, 50 `scoring`. `signal_class`: **NULL on all 161 rows** — the two-tier
signal linkage (`FieldDef.signal_class`, `field.py:172`) is declared in the contract but unused on
this lane. `freshness_ttl`: 90d ×50, NULL ×50, 30d ×18, 75d ×17, 60d ×8, 365d ×8, 180d ×8, 45d ×1,
14d ×1.

Grouping note: the task asked for "first two dotted segments". For two-segment keys that is the key
itself, so the registry is rendered below by **namespace / `field_class`** (the registry's own
column), and the *claim* counts in §2.8 are the literal first-two-segment grouping.
`(rs)` marks a declared `reuse_scope = tenant_private`; everything else declares none and falls
through to `default_reuse_scope`.

### 2.1 `core.*` — commodity firmographics (field_class `core`)

| key | type | gate | description |
| --- | --- | --- | --- |
| `core.account_name` | str | | Evidence-bearing canonical account name observation. |
| `core.annual_revenue` | object | | Annual revenue with currency, as-of date, and explicit reported/estimate semantics. |
| `core.claimed_customer_logos` | json | | *auto-registered:* claimed on the unregistered key 'core.claimed_customer_logos' |
| `core.company_about` | str | | Provider-sourced public company description/about text. |
| `core.company_crunchbase_url` | str | | Crunchbase profile URL. |
| `core.company_email` | str | | Public general company contact email; not a person's work email. |
| `core.company_languages` | list[str] | | Languages the company publishes in. |
| `core.company_linkedin_url` | str | | Canonical public LinkedIn company page URL. |
| `core.company_phone` | str | | Public general company contact phone; not a person's direct number. |
| `core.company_twitter_url` | str | | Company X/Twitter profile URL. |
| `core.company_type` | str | | Provider company type label (private, public, non-profit…). |
| `core.direct_phone` (rs) | str | `selected-contact-channel` | Selected contact's observed direct phone. Delivery data; never an identity key. |
| `core.employee_count` | int | | Total headcount. |
| `core.employee_range` | object | | Evidence-backed employee range used only when exact headcount is unavailable. |
| `core.founded_year` | int | | Year the company was founded. |
| `core.hq_location` | object | | Normalized headquarters or primary location plus the source's raw value. |
| `core.industries_all` | list[str] | | Every industry label the provider records, primary first. |
| `core.industry` | str | | Primary industry classification returned with account evidence. |
| `core.legal_name` | str | | The registered legal entity name. |
| `core.logo_url` | str | | Mark-type company logo image URL (a square symbol: LinkedIn's company mark). |
| `core.primary_domain` | str | | Primary web domain. |
| `core.primary_tech_stack` | list[str] | | Detected primary technologies. |
| `core.revenue_band` | `enum:under_1m\|1m_10m\|10m_50m\|50m_100m\|100m_500m\|500m_1b\|1b_plus` | | Bounded revenue band used only when exact sourced annual revenue is absent. |
| `core.tech_stack_categorised` | list[object] | | Technology stack grouped by category as the provider reports it. |
| `core.total_funding` | json | | *auto-registered:* claimed on the unregistered key 'core.total_funding' |
| `core.work_email` (rs) | object | `selected-contact-channel` | Selected contact's observed work email with the provider's deliverability verdict and check time. Delivery data until corroboration, reachability, use permission and optional identity promotion pass. |

### 2.2 `account.*` — account facts (field_class `account`)

| key | type | gate | description |
| --- | --- | --- | --- |
| `account.abm_program_maturity` | object | | Evidence of the company's own ABM program: open ABM roles, named ABM tooling, stated ABM motion. |
| `account.abm_reporting_line` | json | | *proposed:* ABM role's reporting line, from a job posting. |
| `account.aed_partnerships` | json | | *proposed:* named ongoing partnership (Aledade / value-based care). |
| `account.asc_project` | json | | *proposed:* ambulatory surgery centre announcement with specifics. |
| `account.ashc_project` | json | | *auto-registered:* claimed on the unregistered key 'account.ashc_project' |
| `account.ats_open_reqs_count` | json | | *proposed:* ATS live requisition count. |
| `account.claimed_customer_logos` | list[str] | | Customer logos the company shows on its own site (proposed by the structuring pass). |
| `account.claimed_outcomes_metrics` | object | | Outcome metrics the company claims for customers (proposed by the structuring pass). |
| `account.claimed_partners` | json | | *proposed:* named partner programs / integrations / strategic investors. |
| `account.clinical_research_capacity` | json | | *proposed:* on-site research facilities, chart counts, recruitment capability. |
| `account.committee_candidate` | object | | **One buying-committee candidate the account agent confirmed on a non-provider URL**: name, title, persona from the ICP persona map, LinkedIn URL, what confirmed the identity. A vacant seat is recorded with `vacant_seat=true` and no name (R3 creates the contact). |
| `account.crm_relationship_status` | str | | Client-CRM relationship (already a customer / open opportunity / …); M4.5. |
| `account.employee_roster_sample` | list[object] | | A provider sample of employees (name, title) used to sketch org shape; **never a committee source**. |
| `account.gtm_tooling_stack` | object | | CRM, outbound and ABM tools the company demonstrably uses (present) and tools explicitly named as not used (absent). |
| `account.hiring_velocity` | object | | Open roles by department and their ages, from the company's own job board. |
| `account.hiring_velocity_eng` | number | `tier>=3` | Engineering hiring velocity (signal field). |
| `account.icp_fit_verdict` | object | | The agent's **lenient** fit verdict for one ICP hard gate, with the claim ids behind it. Information for the human; never a reason to stop research. Born `outreach_safe=false`. |
| `account.locations_list` | json | | *proposed:* multiple clinic addresses / phones. |
| `account.media_layer_index` | list[object] | | Podcasts and videos found for the account's people: media URL, duration, whether transcribed. |
| `account.media_transcript_quality_warning` | object | | A recorded defect in a media transcript (model, media, symptom). Born `outreach_safe=false`; context only. |
| `account.named_customers` | list[str] | | Customers the company itself names publicly (logos, case studies, press). |
| `account.npi_numbers` | json | | *proposed:* NPI records for the organization and individual. |
| `account.open_requisitions` | list[object] | | Open job requisitions read from the company's own ATS board: title, department, publish date, days open, salary band, whether still listed, URL. |
| `account.operational_pain` | str | `deep-pass` | Synthesized operational pain. |
| `account.owner_background` | json | | *proposed:* owner's personal/professional background. |
| `account.product_features` | json | | *proposed:* named product features. |
| `account.product_packaging` | object | | How the company packages and names its products (proposed by the structuring pass). |
| `account.proposed_fields` | json | | *auto-registered:* claimed on the unregistered key 'proposed_fields' |
| `account.recent_funding` | object | | Most recent funding round. |
| `account.reputation_risk` | object | | A negative or contested public claim about the company with its status (confirmed, refuted, unresolved). Born `outreach_safe=false`. |
| `account.shared_emr_partner` | json | | *proposed:* shared EMR / technology partner. |
| `account.strategic_moves` | str | `deep-pass` | Strategic moves / initiatives. |
| `account.summary` (rs) | object | `faithfulness` | Neutral account prose summary (Lane E E1) — a tier-4 `llm_synthesis` claim composed on research completion; frontend `summaryParagraphs`. |
| `account.total_funding` | object | | Total funding in USD with explicit estimate semantics. |
| `account.value_narrative` (rs) | object | `faithfulness` | Per-(account, persona) value narrative — Output 4. A tier-4 `llm_synthesis` claim-with-provenance; tenant-private. |

### 2.3 `account.resonance.*` — culture / sentiment (field_class `account.resonance`, all `deep-pass`)

| key | type | description |
| --- | --- | --- |
| `account.resonance.attrition_signal` | object | Morale / attrition / layoff signal (tier-4). |
| `account.resonance.buying_culture` | object | "What it's like to buy here" — procurement culture (tier-4). |
| `account.resonance.culture` | str | Cultural resonance signal (tier-4, governed). |
| `account.resonance.employee_sentiment` | object | Aggregate employee sentiment, Glassdoor-style (tier-4, governed). |
| `account.resonance.eng_blog_tone` | object | Tone/voice of the company's engineering blog (tier-4). |
| `account.resonance.public_frustrations` | list[object] | Publicly aired frustrations about the account (tier-4). |

### 2.4 `account.scoring.*` — the project-relative scores (field_class `account`, all `tenant_private`)

| key | type | description |
| --- | --- | --- |
| `account.scoring.fit` | object | Decomposed ICP fit score (Output 1). Tenant-private (per-client ICP). |
| `account.scoring.intent` | object | Decomposed buying-intent score (Output 1). Tenant-private. |
| `account.scoring.tier` | object | Approved tier assignment + cutoff version (Output 1 tiering). Tenant-private. |

**42 claims exist on `account.scoring.*` — all on `account.scoring.fit`. `account.scoring.intent`
and `account.scoring.tier` have zero claims on this lane.** The ARV2 lane does not tier.

### 2.5 `client.*` — the Client Knowledge Base (field_class `pack`, all `tenant_private`)

| key | type | description |
| --- | --- | --- |
| `client.buyer_profile` | object | Likely-buyer persona / segment evidence (open-web) — persona claims only, never invented account entities. |
| `client.competitor` | object | Named competitor / alternative to the client, grounded in a record naming the client. |
| `client.customer` | list | Existing-customer references (name/domain) — a LIST; these double as seed accounts for lookalike discovery. |
| `client.delivered_value` | str | What the client's own customers say they bought it for (reviews-as-signal). |
| `client.differentiator` | str | What differentiates the client (owned positioning + third-party category). |
| `client.icp_evidence` | object | Industries / sizes / geos of existing customers (ICP evidence). |
| `client.kb_version` | object | Client Knowledge Base version marker `{version, run_id, …}`. |
| `client.market_reputation` | str | Third-party category standing / reputation (G2 / Capterra / directories). |
| `client.pricing_posture` | str | Pricing posture / model (pricing page). |
| `client.product` | str | Product / offering description (product, docs, pricing pages). |
| `client.product_capability` | object | One explicitly stated capability of the selected product. |
| `client.product_catalog` | list | Bounded official portfolio catalog: product name, short description, aliases. |
| `client.product_competitor` | object | One grounded competitor or alternative for the selected product. |
| `client.product_customer_evidence` | object | One customer, testimonial, case study, or outcome for the selected product. |
| `client.product_differentiator` | str | An explicitly stated differentiator for the selected product. |
| `client.product_integration` | object | One explicitly supported integration or ecosystem connection. |
| `client.product_overview` | str | Selected product overview grounded in its official product surfaces. |
| `client.product_positioning` | str | Product-specific audience, category, and positioning statement. |
| `client.product_pricing` | object | Product-specific pricing posture, plan, or quote-led buying model. |
| `client.product_use_case` | object | One grounded use case or workflow for the selected product. |
| `client.proof_point` | str | Case study / testimonial / logo proof point. |
| `client.value_prop` | str | What the client sells and the problem it solves (owned surfaces). |

### 2.6 `contact.*` — plain contact facts (field_class `contact`)

Governed keys (`committee-gated`) first:

| key | type | gate | description |
| --- | --- | --- | --- |
| `contact.class` | str | committee-gated | Optional pack/workspace contact-class value. Separate from committee persona; an absent claim means unknown. |
| `contact.current_location` | object | committee-gated | Provider-returned current professional location/country. |
| `contact.current_title` | str | committee-gated | Provider-returned current professional title for an admitted contact. |
| `contact.job_function` | str | committee-gated | Provider-returned current job function. |
| `contact.job_level` | str | committee-gated | Provider-returned current job level. |
| `contact.organization_relationship` | object | committee-gated | Exact-account current-employment relationship with returned or modeled basis. |
| `contact.persona` | str | committee-gated | **Buying-committee persona key for (account, persona) addressing.** |
| `contact.role_on_committee` | object | committee-gated | Inferred buying-committee role + role-plausibility verdict (Output 3). |
| `contact.team_membership` | list[object] | committee-gated | Provider-modeled organization-team membership with explicit relationship basis. |

Ungated plain contact keys: `contact.headline` (LinkedIn headline as published),
`contact.member_badges` (creator / premium / open-to-work), `contact.network_statistics`
(follower and connection counts), `contact.reports_to` (the committee member this person reports to
— a contact entity id), `contact.x_url`, `contact.jurisdiction` (rs — resolved data-protection
regime, value `{regime, region, confidence, derived_from}`), `contact.overview` (rs, gate
`faithfulness` — neutral contact prose overview, tier-4, frontend `overviewParagraphs`).

Model-proposed, auto-registered `contact.*` keys (all `json`, description = the proposing rationale):
`contact.asc_project_participation`, `contact.best_channel`, `contact.board_and_advisory_roles`,
`contact.board_and_committee_roles`, `contact.board_memberships`, `contact.board_president_since`,
`contact.board_seats`, `contact.co_founder_spouse_note`, `contact.current_employer_role_variants`,
`contact.education`, `contact.founded_companies`, `contact.founded_company_exit_details`,
`contact.founded_company_history`, `contact.historical_officer_role`, `contact.languages`,
`contact.license`, `contact.licenses`, `contact.locations_operated`,
`contact.preferred_announcement_quote`, `contact.preferred_official_title`, `contact.role_scope`,
`contact.role_variants`, `contact.source_confirmation_note`, `contact.started_in_beauty_year`,
`contact.team_membership_board_seats`, `contact.total_experience_years`,
`contact.uscis_designation`, `contact.uses_clinical_software`, `contact.uses_technology`,
`contact.value_based_care_partnerships`.

### 2.7 `contact.facet.*` — personal hooks (field_class `contact.facet`; require binding + use_class)

| key | type | gate | description |
| --- | --- | --- | --- |
| `contact.facet.alma_mater` | list[str] | committee-gated | School(s) / university the person attended. |
| `contact.facet.best_channel` | str | | The channel the research judges most likely to reach this person first. |
| `contact.facet.career_history` | list[object] | committee-gated | Professional history beyond the current title — prior roles. |
| `contact.facet.causes` | list[object] | committee-gated | Publicly supported causes — religion/politics-adjacent, so **sensitive by default**. |
| `contact.facet.certifications` | list[str] | | Professional certifications the person lists. |
| `contact.facet.communication_style` | object | committee-gated | Inferred communication style / tone from public activity. |
| `contact.facet.conference_talk` | list[str] | | Conference talks the person gave, title and venue. |
| `contact.facet.education_highschool` | str | | High school, when self-published. |
| `contact.facet.excluded_lookalike` | object | | A same-name candidate the research rejected and why. Born `outreach_safe=false`; context only. |
| `contact.facet.hobby` | list[str] | | Hobbies the person states publicly themselves. |
| `contact.facet.hooks` | list[str] | | Specific, recent, self-published facts usable as outreach hooks, each grounded in a quote. |
| `contact.facet.nickname` | str | committee-gated | Preferred / known-by name beyond the legal first name. |
| `contact.facet.openers` | list[str] | | **Three grounded opening lines the marketer can send, each tied to a hook.** |
| `contact.facet.other_roles` | list[str] | | Board seats, advisory and side roles the person lists. |
| `contact.facet.preferred_announcement_quote` | json | | *proposed:* first-person announcement language for outreach openers. |
| `contact.facet.public_appearances` | list[object] | committee-gated | Podcasts / talks / panels the person appeared in. |
| `contact.facet.publications` | list[object] | committee-gated | Articles / papers / books the person authored. |
| `contact.facet.recent_award` | list[str] | | Awards or recognitions the person announced. |
| `contact.facet.recent_post` | str | committee-gated | Recent public post (personal hook). |
| `contact.facet.self_summary` | str | | The person's own summary of themselves, verbatim or lightly trimmed. |
| `contact.facet.stated_interests` | list[str] | committee-gated | Publicly stated interests/topics (an interest tied to a religious/political cause is tagged sensitive **per claim**). |
| `contact.facet.stated_skills` | list[str] | | Skills the person lists on their own profile. |
| `contact.facet.voice_quote` | object | | A verbatim spoken quote with the media URL and timestamp it came from. |

### 2.8 Which families actually carry claims (lane DB, first-two-segment grouping)

`SELECT split_part(field_key,'.',1)||'.'||split_part(field_key,'.',2), count(*) FROM claim GROUP BY 1 ORDER BY 2 DESC`
— 3382 claims total. Top of the distribution:

`contact.facet` 1477 · `account.committee_candidate` 128 · `account.open_requisitions` 122 ·
`contact.current_title` 116 · `account.icp_fit_verdict` 95 · `account.reputation_risk` 92 ·
`contact.current_location` 65 · `contact.persona` 64 · `contact.network_statistics` 59 ·
`contact.headline` 58 · `contact.current_employer_role_variants` 51 · `core.employee_count` 50 ·
`contact.role_on_committee` 50 · `account.scoring` 42 · `account.resonance` 41 ·
`account.gtm_tooling_stack` 39 · `core.logo_url` 38 · `contact.member_badges` 36 ·
`core.work_email` 32 · `core.company_about` 28 · `core.company_linkedin_url` 26 ·
`core.hq_location` 25 · `core.account_name` / `core.revenue_band` / `core.primary_domain` 23 ·
`core.industry` / `core.company_email` / `core.founded_year` 22 · `account.hiring_velocity` 21 ·
`account.named_customers` / `account.recent_funding` / `core.company_type` 19 ·
`account.claimed_partners` 18 · `account.strategic_moves` / `account.operational_pain` 17 ·
`core.legal_name` / `account.claimed_outcomes_metrics` / `contact.preferred_official_title` 16 ·
`core.employee_range` / `account.abm_program_maturity` / `account.product_features` 15 ·
then a long tail of 14 → 1.

`client.*` is thin: `client.kb_version` 6, `client.pricing_posture` / `client.proof_point` /
`client.product` / `client.differentiator` / `client.value_prop` / `client.customer` 2 each,
`client.competitor` 1.

**Registry keys with zero claims (22):** `account.crm_relationship_status`, `account.scoring.intent`,
`account.scoring.tier`, `account.summary`, `account.value_narrative`, `client.buyer_profile`,
`client.delivered_value`, `client.icp_evidence`, `client.market_reputation`,
`client.product_capability`, `client.product_catalog`, `client.product_competitor`,
`client.product_customer_evidence`, `client.product_differentiator`, `client.product_integration`,
`client.product_overview`, `client.product_positioning`, `client.product_pricing`,
`client.product_use_case`, `contact.class`, `contact.jurisdiction`, `core.direct_phone`.

**Claim keys not in the registry: none.** Model-proposed keys are auto-registered at write with a
`proposed_field` marker and a description that begins "claimed on the unregistered key …" or states
the model's own rationale, so a "pack field" outside the registry cannot exist on this lane.

---

## 3. Accounts and contacts (ARV2)

### 3.1 `account_entity`

`id, canonical_name, primary_domain, aliases[], hq_geo, registry_ids, status, merged_into,
created_at, updated_at, workspace_id, canonical_version, owner_user_id, created_by_user_id`.

- `status` is the `entity_status` enum: `candidate` \| `active` \| `merged` (`enums.py:296`
  `AccountStatus`).
- `workspace_id` is **NOT NULL**. Accounts are workspace-local — no global account identity, no
  cross-tenant enrichment reuse (founder ruling 2026-07-22; migration `82a80fb80c9e`). A
  cross-workspace read is *not found*, never "empty".
- `merged_into` points at the survivor. Every ARV2 read filters `merged_into IS NULL`.
- There is **no `brand_id`** on the account: target accounts are brand-neutral (migration
  `068426c5ea34`).

### 3.2 `contact_entity`

`id, account_entity_id, full_name, linkedin_url, verified_email, aliases[], geo, jurisdiction,
status, merged_into, created_at, updated_at, workspace_id, canonical_version`.

A contact always hangs under exactly one account (`account_entity_id` NOT NULL). Same `entity_status`
enum, same workspace and merge rules.

### 3.3 `project_account` — how an account joins a project

`workspace_id, project_id, account_entity_id, added_via, added_at`
(`subsystems/research/clue_research/membership.py`).

`added_via` ∈ `("discovered", "imported", "manual", "directive")` (`membership.py:53-55`, mirrored
by the `project_account_added_via_check` CHECK in migration `61b00ee9c70a`). On this lane:
`manual` 39, `discovered` 8.

Semantics (`membership.py:8-27`):
- **The first add wins.** A later add through another channel is a no-op on the row.
- `memberships_for_accounts` orders `added_at` ascending, so element 0 is the recorded
  `primaryProjectId` policy — earliest membership, not a guess.
- On a merge, the loser's memberships are repointed onto the survivor; where both already belonged,
  the survivor's row is kept and the loser's earlier `added_at` is deliberately not adopted.
- Both workspace anchors are composite FKs, so a cross-workspace membership is *unrepresentable*.

**Approval of a discovered account is membership.** `frontend_read/bulk_actions.py:478-496`: adding a
discovered account to the project *is* its approval — `ensure_project_accounts(added_via="manual")`
then `mark_candidates_approved(...)`. Rows never added stay **unapproved, not rejected**.

### 3.4 How "Researched" / "Not started" / "refreshing" are derived

Two statements, deliberately identical in their tie-break.

- `platform/api/clue_api/arv2/read_tools.py:170-192` (`_LIST_PROJECT_ACCOUNTS`, the agent's
  `read_project_accounts`).
- `platform/api/clue_api/frontend_read/v1_shared.py:1209-1234` (`_ARV2_RESEARCH_STATUS`, the
  accounts screen).

Rules:

| Term | Rule | Source |
| --- | --- | --- |
| research status | `arv2_research_job.status` of the account's **latest `subject_type='account'` job**, served **verbatim** — `not_started` \| `in_progress` \| `needs_review` \| `completed` \| `suspended` | `read_tools.py:127-129`, `v1_shared.py:1247-1256` |
| "Not started" | **no account job at all** → the reader spells it `not_started` at the one place it builds the row. An account with no job is *absent* from `arv2_research_status_for`'s result, deliberately, so it stays distinguishable from a genuine `not_started` job row | `read_tools.py:257-258`, `v1_shared.py:1255-1259` |
| `refreshing` | a **non-terminal** job (`not_started`/`in_progress`; `suspended` is halted, not running) exists that is *newer* than a `completed` one for the same account. "Newer" is the tuple compare `(created_at, job_id)`, the same total order both statements sort "latest" by | `read_tools.py:176-182`, `v1_shared.py:1190-1202` |
| account jobs only | person jobs share the table and the account column. A committee member still being researched is **not** the account being re-researched and must not light the account's spinner | `read_tools.py:160-161`, `v1_shared.py:1204-1208` |
| project-independent | the run's `project_id` is deliberately not consulted: an account researched under one project is not unresearched when read under another (D4-b decision 1) | `v1_shared.py:1186-1189` |
| merge losers | `JOIN account_entity a ON … AND a.merged_into IS NULL`. The `total` repeats the same join *and* the same name/domain filter so "showing 100 of 240" is two measurements of one population | `read_tools.py:174, 195-204` |
| default order | `a.created_at DESC, a.id DESC` — the accounts screen's own default, so "the first ten accounts" means the same ten to the agent and to the marketer | `read_tools.py:184-186` |
| cap | `MAX_ACCOUNTS = 200`, `MAX_CLAIMS = 120`, `MAX_CANDIDATES = 50`; over the cap the read says `truncated` rather than dropping the tail silently | `read_tools.py:99, 326, 624` |

`ProjectAccountView` fields: `account_entity_id, name, domain, research_status, refreshing,
added_via, added_at` (`read_tools.py:120-136`).

### 3.5 The display pages

Three pages, fixed grammar. `display_block.page` CHECK: `overview` \| `insights` \| `contact`;
`subject_kind` CHECK: `account` \| `contact` (migration `65fb2128c904_arv2_d1_display_substrate`).
`PAGE_SUBJECT_KIND` (`display/page.py:85-89`): overview→account, insights→account,
contact→contact.

`display_block` columns: `display_block_id, workspace_id, subject_kind, subject_id, page,
section_key, body_json, cited_claim_ids[], model, prompt_version, recipe_version, generated_at,
superseded_at`. A block is live while `superseded_at IS NULL`.

`display_section_recipe` columns: `page, section_key, workspace_id, h1, position,
allowed_field_keys[], restricted, default_open, instruction_version, created_at`. System rows carry
`workspace_id = ''`; a workspace row with the same `(page, section_key)` overrides it; a workspace
row for a section the page grammar does not have is ignored — **the page grammar is fixed**
(`display/recipes.py:325-330`).

`SELECT page, section_key, position FROM display_section_recipe ORDER BY page, position` (matches
`SYSTEM_RECIPES` in `display/recipes.py:38-274` exactly):

| page | pos | section_key | h1 | restricted | default_open | narrative |
| --- | --- | --- | --- | --- | --- | --- |
| overview | 0 | `what-they-do` | What they do | | yes | yes |
| overview | 1 | `why-they-fit` | Why they fit | | yes | yes |
| overview | 2 | `why-now` | Why now | | | |
| overview | 3 | `buying-committee` | Buying committee | | | |
| overview | 4 | `how-to-approach` | How to approach | | | |
| overview | 5 | `watch-outs` | Watch-outs | **yes** | | |
| insights | 0 | `buying-signals` | Buying signals | | yes | |
| insights | 1 | `money-and-momentum` | Money & momentum | | | |
| insights | 2 | `tools-they-already-use` | Tools they already use | | | |
| insights | 3 | `how-they-sell` | How they sell, and who they win | | | |
| insights | 4 | `contact-insights` | Contact insights | | | |
| insights | 5 | `context-only` | Context only | **yes** | | |
| contact | 0 | `why-this-person` | Why this person | | yes | |
| contact | 1 | `problem-right-now` | Their problem right now | | yes | |
| contact | 2 | `openers` | Openers | | yes | |
| contact | 3 | `angles` | Angles | | | |
| contact | 4 | `do-not-mention` | Do not mention | **yes** | yes | |

`RESTRICTED_SECTION_KEYS = {"context-only", "watch-outs", "do-not-mention"}`
(`display/recipes.py:20`). All three carry the same two keys, `_UNSAFE_CONTEXT =
("account.reputation_risk", "account.resonance.attrition_signal")` (`recipes.py:35`), **plus every
`outreach_safe=false` row on the subject** (the restricted branch of `_candidates`).
`RECIPE_VERSION = 1`.

Live blocks on this lane: overview 48 rows across all six sections, insights 19, contact 34.

### 3.6 When a page is written — `ensure_page`

`platform/api/clue_api/arv2/display/page.py:288`.

1. Refuse if `PAGE_SUBJECT_KIND[page] != subject_kind` (`PageSubjectMismatch`).
2. Resolve the subject, the client context, the recipes (system + workspace overrides), and — for
   an account page — the committee.
3. Read the live blocks and compute `stale_sections` over the page's whole entity expansion (a
   contact page watches the person *and* their account; an account page watches the account and its
   committee — `_people_of`, `page.py:275-286`).
4. `force=True` supersedes every live block first and rewrites the whole page. Otherwise `missing` =
   sections with no live block, **plus** stale ones only when `regenerate_stale=True`.
   Without it, "a stale section is served exactly as it was written and named in `stale_served` —
   the operator decides whether to spend, and the page never silently costs money it was not asked
   to spend" (`page.py:310-313`).
5. A section whose `SectionInput.empty` is true is **not written** (`skipped_empty`).
6. Sections are written in parallel under `arv2_display_max_parallel` (8 on this lane), all inside
   the caller's transaction: "a page is one atomic replacement of its own sections, or it is none of
   them."
7. A section the model failed to write twice is not stored.

Activity feed text by page: `{"overview": "Overview written", "insights": "Insights written",
"contact": "Contact page written"}` (`page.py:77-82`).

`CLUE_ARV2_DISPLAY_GENERATE_ON_READ=true` on this lane. `read_account_research(section="overview")`
refuses with `overview_not_written` when no live block exists (`read_tools.py:411-415`).

---

## 4. Research runs and jobs

`alembic/versions/a3602967bb73_arv2_r2_account_research_jobs.py` (runs + jobs),
`60e51eba0123_arv2_r3_person_jobs.py` (person subjects),
`c90aaea30a88_arv2_research_job_stage.py` (stage).

### 4.1 `arv2_research_run` — the authorization record

`run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key, icp_artifact_sha256,
icp_key, icp_version, product_selection_version, effort, committee_cap, directive_text, profile_ref,
profile_sha256, requested_by_user_id, request_sha256, status, created_at, finished_at`.

"The run row **is** the authorization record: the exact account set, the confirmed ICP artifact and
its digest, the product-selection version, the agent profile and *its* digest. A job that later
finds any of those bytes moved refuses and asks to be relaunched, because moved bytes are a
different thing to have approved." (`account_research_launch.py:3-7`)

**The run id is the digest of the request** — `uuid5(_RUN_NS, request_sha256)`
(`account_research_launch.py:131, 322`). Relaunching the same signed-off request returns the same
run, inserts no second job, and buys no second task.

| Column | Values / rule | Source |
| --- | --- | --- |
| `status` | `not_started` \| `in_progress` \| `needs_review` \| `completed` \| `suspended` | CHECK `arv2_research_run_status`; `account_research_store.py:67` |
| `effort` | `full` \| `reduced` \| `cheap-pass` | CHECK `arv2_research_run_effort`; `Arv2Effort`, `account_research_launch.py:149` |
| `committee_cap` | `>= 1`; how many committee members the account agent may resolve. The person launch sets it to "how many people the human named" | CHECK `arv2_research_run_cap`; `account_research_launch.py:756` |
| `directive_text` | free text — the human's own words about what to look for. Default `''` | `account_research_launch.py:177` |
| `icp_artifact_sha256` / `profile_sha256` / `request_sha256` | `^[0-9a-f]{64}$` | three CHECKs |
| `finished_at` | biconditional with `status IN ('completed','needs_review')` | CHECK `arv2_research_run_finished` |
| `product_selection_version` | `>= 1` | CHECK `arv2_research_run_selection` |

### 4.2 `arv2_research_job` — one job per subject

`job_id, run_id, workspace_id, account_entity_id, status, attempt, started_at, finished_at,
finalization_json, failure_code, failure_message, model_rounds, tool_calls, cost_usd, credits,
media_seconds, created_at, updated_at, subject_type, subject_entity_id, profile_sha256, stage`.

| Column | Values / rule | Source |
| --- | --- | --- |
| `status` | same five as the run — "the seam-1 states, shared by runs and jobs so a reader learns one vocabulary" | `account_research_store.py:66-67` |
| `subject_type` | `account` \| `person`. `subject_entity_id IS NOT NULL` **iff** `person` | CHECKs `arv2_research_job_subject_type`, `_subject`; `JobSubject`, store `:70` |
| `stage` | `deep_research` → `synthesis` → `committee` → `member_research` for an account job; a person job stamps **only the first two**. NULL before the job's first claim | CHECK `arv2_research_job_stage`; `JobStage`, store `:72-75`; driver `account_research_driver.py:619, 938, 943` |
| `failure_code` | biconditional with `status = 'needs_review'`; `UNSPECIFIED_FAILURE = "unspecified"` is the placeholder when the caller named no reason | CHECK `arv2_research_job_failure`; store `:81-84` |
| `finished_at` | biconditional with `status IN ('completed','needs_review')` | CHECK `arv2_research_job_finished` |
| cost columns | `cost_usd` (numeric), `credits` (numeric), `media_seconds` (int), plus `model_rounds` and `tool_calls`. `JobSpend` is "one job's settled spend, summed from `provider_call_ledger`" | store `:197-201` |
| `account_entity_id` | composite FK to `account_entity(id, workspace_id)` — a person job still carries the account it belongs to | CHECK `arv2_research_job_account_fk` |

`TerminalJob = Literal["completed", "needs_review"]` — "the two statuses a job can *finish* on.
**`suspended` is a pause, not a terminal**" (`account_research_store.py:77-78`).

Job id is deterministic: `arv2_job_id(run_id, subject_id) = uuid5(_JOB_NS, f"{run}:{subject}")`
(`account_research_launch.py:135-145`). Three writers key it this way — the account launch, the
person launch, and the committee step — so a relaunch or a re-settle lands on the row that is
already there.

Stage → progress fraction (`research_progress.py:59-60, 106-109`): not claimed or still
`deep_research` → 0; `synthesis` → 0.25; `committee` → 0.5; `member_research` → 0.75 + 0.25 ×
(person jobs finished ÷ person jobs); a **finished** account job that never reached
`member_research` (no committee) → 1.0.

### 4.3 "Settled"

The word the skill uses in §7/§8 ("once the account job settles") and never defines. In code it is
the job's **terminal transaction**: the transaction in which the driver writes `finish_job` with
`status ∈ {completed, needs_review}` and, for an account job, runs the committee step inside that
same transaction (`committee_step.py:6-8, 13-17`). Hence:

- "A member that cannot be written is a recorded skip" — the step must not raise, because a raised
  error would cost the job the `finish_job` row it just wrote.
- "It queues nothing": the step reports what to offer, the driver offers it once the settling
  transaction has **committed**. Rows first, offer second.

### 4.4 Launch preconditions

`launch_arv2_account_research` (`account_research_launch.py:240`). Checks run in cost order, free
ones first, and **nothing is written until every check passes**. Typed refusal codes
(`Arv2LaunchRefused`, `account_research_launch.py:183-192`):

`lane_disabled` · `project_not_found` · `account_not_found:<id>` · `account_not_in_workspace:<id>` ·
`project_icp_not_pinned` · `icp_artifact_not_found` · `icp_artifact_not_confirmed` ·
`icp_digest_mismatch` · `icp_front_matter_invalid` · `icp_artifact_not_project_pin` ·
`product_selection_version_unknown`.

Order: (1) `settings.arv2_account_research_enabled`; (2) the **project** exists in this workspace
("every check after this one is a question *about* a project"); (3) `_check_accounts`; (4)
`_pinned_icp` — the document a project pinned, read **by id**, "the exact version a human approved,
never 'the newest row that happens to carry these bytes'" (`account_research_launch.py:152-156`),
with `_ICP_KIND = "icp-definition"` and `_ICP_STATUS = "confirmed"` ("a `proposed` ICP is a draft
nobody has agreed to, and researching against it would spend money on an audience the client never
confirmed", `:126-129`); (5) `_check_product_selection`.

Then: `ensure_project_run(phase=ProjectPhase.DEEP)` with
`project_run_id = uuid5(f"arv2-project-run:{project}:{icp_key}:{icp_version}")`; `create_run`;
`record_run_lineage(kind="entity_research")`; per account `ensure_project_account(added_via="manual")`
then `create_job(subject_type="account")`.

`launch_arv2_person_research` (`:662`) adds: `no_contacts`, `contact_not_found:<id>`,
`contact_merged:<id>`, `contact_without_account`, `product_set_not_confirmed`. It **never creates a
person** — "creating one is an identity act with its own evidence, and a launch that could invent
people would be a launch that could research someone who does not exist" (`:640-644`). It writes a
run of its own (a different human act, a different approval), `effort="full"`,
`committee_cap = len(contact_entity_ids)`, and it **seats** each contact with a `persona` (default
`Persona.USER`) because "a person launched on demand is otherwise **nobody**: the account's contact
list is read from the committee claims, so a person with no `contact.persona` claim is researched at
cost and then invisible on their own account's screen (walk finding W2, 2026-09-09)" (`:651-658`).

Neither launch queues anything. `enqueue_launched_jobs(queue, receipt)` (`:378`) is the caller's,
after commit: an offer made inside the launch transaction is visible to a polling worker *before*
the rows it names, and that worker reads "no such job" as "already done" and drops the account's
research permanently (`Arv2LaunchReceipt`, `:210-217`). **Every** job of the run is re-offered on a
replay, because the queue's dedup key makes a re-offer a no-op and that is how a lost offer is
repaired.

Fleet: `FleetTaskKind.ARV2_ACCOUNT_RESEARCH` / `ARV2_DISCOVERY` (`fleet_task_kind` enum).
Ceilings on this lane: `MAX_MODEL_ROUNDS=100`, `MAX_TOOL_CALLS_PER_ROUND=50`,
`MAX_RUNTIME_S=1800`, `MAX_PARALLEL_JOBS=4`, `PROVIDER_CONCURRENCY=4`.

### 4.5 The persona / committee flow

1. The account agent resolves a committee and finalizes. Each confirmed candidate is written as one
   **`account.committee_candidate`** claim *on the account* — "a finding about the account. It is
   not yet a person the platform can research, address or govern" (`committee_step.py:3-6`).
2. `run_committee_step`, inside the settling transaction, turns each candidate into: a **contact
   entity**, **three claims keyed to it** — `contact.persona`, `contact.role_on_committee`,
   `contact.current_title` (`committee_member_claims`, `account_research_claims.py:1543`) — and a
   **person job** (`create_job(subject_type="person")`, `committee_step.py:210-220`).
3. Skips are named, not silent: `vacant_seat` (a seat with `vacant_seat=true` and no name creates
   no contact, no claims and no job), `unconfirmed` (a name with no confirming URL — the account
   job never wrote it as a claim either).
4. "One member is one savepoint": the contact, its three claims and its person job land together or
   not at all.
5. The confirming URL and the candidate's own quote travel onto all three claims, so a reader of any
   of them reaches the page that named this person in this seat.
6. `method` defaults to `LLM_SYNTHESIS` (the model read a page and assessed the committee); the
   on-demand person launch passes `HUMAN` instead, "because there the persona is the requesting
   human's own statement — recording that as synthesis would put a false provenance (and a tier-4
   stamp) on a tier-1 fact" (`account_research_claims.py:1566-1570`).
7. No persona ⇒ no persona claim and no role claim: "a role with no role in it is not a committee
   assessment."

`Persona` (`enums.py:358`): `champion`, `economic_buyer`, `technical_evaluator`, `blocker`, `user`
(appended 2026-09-07, ARV2 master plan D8 — "the person who operates the tool daily"; **not a DB
enum**, it lives in registered value schemas).

Display order is **not** the enum order. `PERSONA_RANK` (`display/personas.py:28-34`):
`economic_buyer` → `champion` → `technical_evaluator` → `user` → `blocker`; an unknown persona sorts
last, then by name, then by id. `PERSONA_LABELS` (`:37-43`): Economic buyer / Champion / Technical
evaluator / User / Blocker — "a persona outside the vocabulary has no label we can vouch for, so it
gets none."

Lane reality (`contact.persona` claim values): `economic_buyer` 21, `user` 16, `champion` 15,
`technical_evaluator` 8, `blocker` 4.

### 4.6 `arv2_claim_annotation` — the link audit

`annotation_id, claim_id, job_id, kind, verdict, detail_json, checked_at`. `kind` CHECK: only
`link_audit`. `verdict` CHECK: `EXACT` \| `PARTIAL` \| `NOT_FOUND` \| `fetch_failed`. Lane counts:
EXACT 1288, NOT_FOUND 196, PARTIAL 162, fetch_failed 15.

---

## 5. Discovery

`alembic/versions/2cd622be2da0_arv2_r4_discovery.py`; store
`platform/api/clue_api/arv2/discovery_store.py`; verifier `discovery_verifier.py`; launch
`discovery_launch.py`.

### 5.1 `arv2_discovery_run`

`run_id, workspace_id, project_id, brand_id, project_run_id, icp_artifact_key, icp_artifact_sha256,
icp_key, icp_version, requested_by_user_id, request_sha256, target_count, strict_count,
relaxed_enabled, relaxed_requested, criteria_gate_keys, status, webset_id, strict_search_id,
relaxed_search_id, asked, found_strict, found_relaxed, analyzed, recall_estimate, receipt_json,
created_at, started_at, finished_at`.

| Term | Meaning | Source |
| --- | --- | --- |
| `status` | `not_started` \| `in_progress` \| `needs_review` \| `completed` \| `suspended` — "the seam-1 states, **verbatim** — the same vocabulary the R2 runs and jobs carry" | CHECK; `discovery_store.py:66-68` |
| `target_count` | **how many companies the human asked for**; `> 0` | CHECK; `discovery_launch.py:146` |
| `strict_count` | **how many the provider is asked for**; `> 0`; default `settings.arv2_discovery_strict_count` (35 on this lane) | CHECK; `discovery_launch.py:147-148, 509` |
| `relaxed_enabled` | whether a relaxed re-search may run; default `settings.arv2_discovery_relaxed_auto` (true here) | `discovery_launch.py:149-150, 514` |
| `relaxed_requested` | the human asked for the relaxed pass on a **finished** run — "its counters, the human read them, and *asking for the relaxed pass is their decision*" | `discovery_launch.py:594-600` |
| `criteria_gate_keys` | which of the ICP's hard gates become webset **criteria** (at most `MAX_CRITERIA`); a key the confirmed document does not define refuses the launch *before* any webset is bought | `discovery_brief.py:152-179`; `discovery_launch.py:20-23` |
| `asked` / `found_strict` / `found_relaxed` / `analyzed` / `recall_estimate` | "the §4 'a short list is information, never padded' record: a run that exhausts the pool says so with numbers instead of quietly returning fewer companies" | `discovery_store.py:9-11` |
| `request_sha256` | `UNIQUE (workspace_id, request_sha256)`; the run id is the digest of the request — "asking the same thing twice is one run, one webset and one bill" | CHECK + `discovery_launch.py:13-16` |

Refusal codes (`Arv2DiscoveryRefused`, `discovery_launch.py:159-162`): `lane_disabled`,
`target_count_invalid`, `project_not_found`, plus the ICP-pin family; `request_relaxed_pass` adds
`run_not_found`, `run_not_finished`.

### 5.2 `arv2_discovery_candidate`

`candidate_id, run_id, workspace_id, project_id, pass, domain, websets_url, name,
provider_snapshot_json, verdicts_json, fit, disposition, decision, decided_by_user_id, decided_at,
account_entity_id, created_at`. `UNIQUE (run_id, domain)` — one company, keyed by its **verified
domain** inside its run.

| Column | Values | Meaning | Source |
| --- | --- | --- | --- |
| `pass` | `strict` \| `relaxed` | the full criteria, or the widened re-search | CHECK; `Pass`, `discovery_store.py:70-71` |
| `disposition` | `pending`, `pass`, `partial`, `unclear`, `duplicate_of_existing`, `not_chosen_before` | **what a verified candidate *is*, never what it was refused for** | CHECK; `Disposition`, `discovery_store.py:73-76` |
| `decision` | `NULL` or `approved` — **nothing else is representable** | the human's approval; there is no recorded rejection | CHECK `arv2_discovery_candidate_decision`; `discovery_store.py:15-21` |
| `fit` | `numeric(4,3)`, nullable | `passes / gates`, an `unclear` counted as **half a pass** | `fit_score`, `discovery_verifier.py:329-336` |

`SHOWN_DISPOSITIONS = ("pass", "partial", "unclear")` (`discovery_store.py:85`) — "the dispositions
that mean the human was shown this company, and equally the candidates a later run still remembers
as 'seen but not chosen'. A duplicate is already an account, and a pending one was never verified,
so neither is re-surfacing news."

`PENDING_DISPOSITION = "pending"` (`:88`) — a candidate nothing has verified yet.

`VERIFIED_PREDICATE = "jsonb_array_length(c.verdicts_json) > 0"` (`:102`). **This is what "verified"
means, in one place.** It used to be the complement of `pending`, and that was wrong: the pre-spend
dispositions `duplicate_of_existing` and `not_chosen_before` are stamped **before any gate is
asked**, so "not pending" counted them as verified "and the agent told the founder the platform had
checked companies it had skipped" (`:94-99`).

`disposition(verdicts)` (`discovery_verifier.py:339-350`): all `pass` → `pass`; any `fail` →
`partial`; otherwise `unclear`. **There is deliberately no `fail` disposition** — "a candidate on the
list is one the human is being shown, and a failed gate is a reason to read the verdict, never a
reason to hide the row (ruling 1′)."

**Unapproved is not rejected** (ruling 1′, rev 5, `discovery_store.py:15-21`). Nothing in the store
can mark a candidate rejected. `unapproved_domains` is how a *later* run in the same project
remembers not to re-surface a company, and `not_chosen_before` is what that later run stamps.
"The absence of a rejection vocabulary is the product's, not an oversight."

### 5.3 `verdicts_json` shape

One array element per gate, `GateVerdict.as_json()` (`discovery_verifier.py:241-251`):

```
{gate_key, verdict, reasoning, evidence_quote, evidence_url, evidence_date, guard, model_verdict}
```

- `VERDICTS = ("pass", "fail", "unclear")` (`:59`). "`fail` means a source **contradicted** the
  test; it is not the answer for 'we found nothing' (that is `unclear`)."
- `GUARDS = ("ok", "quote_not_on_page", "wrong_company", "outside_window", "no_source",
  "malformed")` (`:62`). `ok` means the model's answer survived unchanged.
- `model_verdict` is kept beside `verdict` on purpose: "the point of the experiment is to measure
  how often the model's answer had to be overturned."
- The three hard guards (`:1-20`): the quote must actually appear on a citation's page (compared
  after `normalise`, prefix of `QUOTE_PREFIX_CHARS = 60`); the page carrying the quote must be on
  the company's own domain or name the company; date arithmetic for a window is done **in code**,
  not by the model. A guard-overturned answer becomes `unclear`, **never `fail`** — "a gate we could
  not evidence is an open question for the human, not a rejection."

### 5.4 The run-level read the agent sees

`DiscoveryRunView` (`read_tools.py:602-621`): `run_id, status, icp_key, icp_version, target_count,
asked, found, verified, shown, approved, relaxed_requested, started_at, finished_at, candidates,
candidate_total`.

The three tallies are "what a human asks for by other names" (`read_tools.py:637-645`):
`verified` = candidates with ≥1 verdict; `shown` = `disposition = ANY(SHOWN_DISPOSITIONS)`;
`approved` = `decision = 'approved'`.

Candidate ordering (`_candidate_order`, `:663-676`): shown first, then best `fit`, then by name —
"a candidate with no fit sorts *after* every scored one rather than as a zero: an unscored company
is unknown, not bad."

`DiscoveryCandidateView`: `name, domain, pass` (serialization alias — the Python attribute is
`pass_`), `disposition`, `decision`, `fit`.

### 5.5 Approval

There is no approve-candidate tool. Approval happens on the accounts table bulk action
(`frontend_read/bulk_actions.py:478-496`): `ensure_project_accounts(added_via="manual")` then
`mark_candidates_approved(...)`, guarded `decision IS NULL` so "a second bulk action over an
overlapping selection re-stamps nobody's earlier decision" (`discovery_store.py:584-593`).
"Adding a discovered account to the project **is** its approval" (ARV2 R4 ruling 2, rev 2).

---

## 6. Knowledge documents

### 6.1 `brand_knowledge_document`

`document_id, workspace_id, brand_id, folder, path, kind, version, status, artifact_key,
artifact_sha256, produced_by_step_id, produced_by_turn_id, supersedes_document_id, created_at,
updated_at, project_id, derived_from_document_id`.

| Column | Values | Source |
| --- | --- | --- |
| `kind` | `company-overview`, `product-catalog`, `product-research`, `customer-reviews`, `icp-definition`, `audience-persona`, `design-brief`, `project-plan` | CHECK `brand_knowledge_document_kind` |
| `folder` | `company`, `product`, `audience`, `proof`, `design`, `project` | CHECK `brand_knowledge_document_folder` |
| `status` | `running`, `ready`, `empty`, `failed`, `proposed`, `confirmed`, `superseded` | CHECK `brand_knowledge_document_status` |
| `path` | must start `folder || '/'` | CHECK `brand_knowledge_document_path_in_folder` |
| `version` | `>= 1` | CHECK |
| producer | `produced_by_step_id` (onboarding) XOR `produced_by_turn_id` (agent turn) — never both | CHECK `brand_knowledge_document_one_producer` |
| bytes | a `ready`/`proposed`/`confirmed`/`superseded` row **must** have `artifact_key` and a 64-hex `artifact_sha256` | CHECK `brand_knowledge_document_body_when_served` |

**The servable set is three statuses: `ready`, `proposed`, `confirmed`** — "a document is servable
while it has bytes and has not been superseded." Restated (never imported) in **six** modules because
`clue_api.arv2` may not import `clue_api` modules outside the lane (Global Constraint 7), and pinned
equal by `tests/arv2/test_servable_statuses_agree.py`:

`arv2/project_documents.py::_SERVABLE_STATUSES` · `arv2/icp_authoring.py::_SERVABLE_STATUSES` ·
`arv2/icp_confirmation.py::_SERVABLE_STATUSES` · `arv2/onboarding_store.py::_SERVED_STATUSES` ·
`brand_knowledge_context.py::SERVABLE_STATUSES` · `frontend_read/brand_knowledge.py::SERVABLE_STATUSES`.

(`account_research_store.py:86-88` carries a seventh copy, `SERVED_DOCUMENT_STATUSES`, with the same
three values — it is not in the guard's `_COPIES` map.)

**Scope rule.** The unique index is
`brand_knowledge_document_scope_path_version (workspace_id, brand_id, COALESCE(project_id,''), path,
version)`. So a brand's document at a path and a project's own document at the same path are **two
histories that never interleave** (`project_documents.py:29-31`). `project_id IS NULL` = brand scope;
`project_id` set = project scope, with a partial index `brand_knowledge_document_project`.

`derived_from_document_id` is a self-FK: a **project-local ICP variant** points at the brand profile
it adapts (`icp_authoring.py:5-6, 16-17`). "A `derived_from` the model typed is dropped; a
`derived_from_icp_key` that names nothing is refused."

`supersedes_document_id` is the version chain's backward edge. A new version retires the prior
servable one — **`confirmed` is deliberately absent from what a new version retires**
(`icp_authoring.py:86-87`): "a human's yes is some project's pin, and the confirmed row stays
servable because some project may still be pinned to precisely those bytes."

Path naming: a document owns the **plain** name of its path unless another version of that path in
that scope is pinned, in which case the unpinned one carries `.v<N>` before the suffix
(`icp_authoring.py:185-226`; e.g. `audience/icp-gi.v3.md`).

Lane contents: `audience-persona`/audience/ready ×4, `company-overview`/company/ready ×2,
`customer-reviews`/proof/ready ×2, `icp-definition`/audience/**confirmed ×4, proposed ×2,
superseded ×3**, `product-catalog`/product/ready ×2, `product-research`/product/ready ×29.

### 6.2 The ICP document format

Validated by `_validate_front` (`icp_authoring.py:239-275`) — "deliberately a floor, not a schema…
what is refused here is a document that could not be an ICP at all."

**Enforced** (refusal code `icp_front_matter_invalid` for each):

| key | rule | source |
| --- | --- | --- |
| `kind` | must equal `icp-definition` | `:246-251` |
| `icp_key` | must equal the requested key; lowercase kebab-case, `≤ ICP_KEY_MAX_LENGTH` (refusal `icp_key_invalid`) | `:253-258`, `:230-237` |
| `product_ids` | non-empty list of non-empty strings | `:259-268` |
| `hard_gates` | non-empty list | `:269-274` |

**Read but not validated here** — "the gates' shape, the persona map and the qualifier fields are
read by the surfaces that use them": each `hard_gates` entry is `{key, rule, test}` with an optional
window in months parsed out of `rule`/`test` (`discovery_brief.py:67-78, 130-147`; a gate with no
`key` or no `rule` is a `BriefError`); `exclusions` (compiled by R4 and **asked of nobody today** —
`discovery_brief.py:94-103`); `persona_map`; `qualifier_fields`.

The authoring skill states the same shape to the agent (`stage0-interview/v26/SKILL.md` §5b) and
`icp-synthesis/v3/SKILL.md:38-77` gives the generator's template: `exclusions: [one sentence each]`,
`persona_map` over `economic_buyer, champion, user, technical_evaluator, blocker` (omit a role that
does not exist at this account type), `qualifier_fields`.

**Platform-owned front-matter keys the model may not write** — stripped and re-stamped from the
request and resolved rows (`_PLATFORM_OWNED_KEYS`, `icp_authoring.py:99-110`): `confirmed_by`,
`confirmed_at`, `confirmed_for_project_id`, `product_selection_version`, `user_edit`,
`derived_from`, `project_id`, `brand_id`, `status`. "A draft cannot confirm itself, scope itself, or
claim a lineage."

Other authoring refusals: `icp_key_taken_by_brand` (a project variant needs its own key).
Authoring always stores `status = proposed`; **only the gate mints `confirmed`**.

### 6.3 The persona document format

`platform/agents/catalog/skills/audience-persona/v2/SKILL.md`. Written to
`outputs/audience/persona-<key>.md`, one section per `persona_map` role, in the order
`economic_buyer, champion, user, technical_evaluator, blocker`. Front matter, exactly:

```yaml
kind: audience-persona
icp_key: <the ICP's key>
icp_version: <the ICP version the user message names>
personas:
  - role: economic_buyer
    titles: [<the section-2 titles>]
    buying_triggers: [<the section-7 triggers>]
    evidence_urls: [<every URL the evidence tool returned that you used>]
```

Body: 11 numbered sections per role (role and snapshot; titles that hold this role; daily reality;
core fears; deep motivations; critical pain points; buying triggers; trust builders; trust killers;
language and channels; how the products serve them), 300–450 words per role, every specific fact
cited by file path or URL, inference marked as inference.

### 6.4 The plan format

`platform/api/clue_api/arv2/project_documents.py`. One plan per project.

`PLAN_KIND = "project-plan"`, `PLAN_FOLDER = "project"`, `PLAN_PATH = "project/plan.md"`,
`PLAN_WORKSPACE_PATH = "inputs/project/plan.md"`, `PLAN_SOURCE_KEY = "arv2-project-plan"`,
`USER_EDIT_SOURCE_KEY` for a human edit — "a plan the agent wrote and a plan the human edited are
different acts and are told apart at the artifact, not only in the front matter"
(`project_documents.py:79-101`).

Front matter stamped by the platform (`:438-446`):

```yaml
kind: project-plan
project_id: <…>
brand_id: <…>
version: <the version this write mints>
status: ready
authored_by: {turn_id: <…>, user_id: <…>}
authored_at: <iso8601>
```

Rules (`project_documents.py:1-31`):
- **A plan is born `ready`; there is no confirmation gate for a plan.**
- Two hands write it, so the agent must say which version it read: `expected_version` is compared
  against the version at rest and a mismatch is refused by name
  (`project_document_revision_conflict`) rather than overwriting the human's words. `None` means "no
  plan exists yet" and is only correct for the first write.
- The version this write mints is stamped **into** the front matter, so the version of the file the
  agent reads is legible in the file it reads (ruling P).
- A human's text edit of a `confirmed` document comes back **`proposed` with the approval stamp
  dropped** (ruling I); the confirmed row it came from stays servable.
- Human-editable kinds through this surface are gated by *kind*: the plan, and the audience
  documents (ICP variants and their personas) a project authored for itself (`:109-112`).

### 6.5 `project_icp_pin`

`workspace_id, project_id, pin_seq, brand_id, document_id, icp_key, artifact_key, artifact_sha256,
product_selection_version, pinned_by_user_id, pinned_at`. PK `(project_id, pin_seq)`, `pin_seq >= 1`
— **append-only**; the current pin is the highest `pin_seq`. The pin names a `document_id`, not a
path: the exact version a human approved. Migration `71e80c777cf6_arv2_project_icp_pin`.

Founder ruling 2026-09-10: projects pin **one** ICP version by id and it is **never auto-moved**;
a newer proposal appearing later does not change what this project confirmed.

### 6.6 `project_product`

`workspace_id, project_id, brand_id, product_id, selection_version, gate_id, confirmed_by_user_id,
confirmed_at`. PK `(project_id, selection_version, product_id)`, `selection_version >= 1`. The whole
*set* is one version; "a later change of the set is a new gate and a new version, never an edit"
(`stage0-interview/v26/SKILL.md` §4). `gate_id` FK-anchors the human act that confirmed it.
`arv2_research_run.product_selection_version` pins which set a run was authorized against.

### 6.7 `onboarding_run`

`run_id, workspace_id, brand_id, client_entity_id, company_domain, requested_by_user_id,
requested_at, status, lane_version, cost_usd, finished_at, kind, project_id,
persona_icp_document_id`.

| Column | Values | Source |
| --- | --- | --- |
| `kind` | `full` \| `personas` | CHECK `onboarding_run_kind` |
| `status` | `queued`, `running`, `completed`, `completed_with_gaps`, `failed` | CHECK `onboarding_run_status` |
| `lane_version` | default `'onboarding-v2'` | column default |
| shape | `kind = 'personas'` **iff** `persona_icp_document_id IS NOT NULL` | CHECK `onboarding_run_persona_shape` |
| `finished_at` | biconditional with `status IN ('queued','running')` being false | CHECK `onboarding_run_finished_when_terminal` |

Lane reality: 2 runs, both `full` / `failed`.

---

## 7. Project state and decisions

**There is no `project_state` table.** Looked for: `pg_tables LIKE 'project_%'`, and
`grep -rn "project_state"` across `platform/`, `subsystems/`, `libs/`. Project decisions are rows in
**`volunteered_statement`** with `route_kind = 'project_state'`
(`subsystems/research/clue_research/stage0/governed.py`, written by `record_interview_answer`,
`platform/api/clue_api/stage0_tools.py:997`).

### 7.1 `volunteered_statement`

`id, onboarding_input_id, workspace_id, brand_id, product_id, project_id, client_entity_id,
entity_id, route_kind, route_key, route_ref, quote_start, quote_end, quote_sha256,
correction_of_id, created_by_actor, created_at`.

| Column | Values / rule | Source |
| --- | --- | --- |
| `route_kind` | `claim`, `memory`, `project_state`, `field_proposal`, `source_proposal`, `unmapped` | CHECK `volunteered_statement_route`; `InterviewRoute`, `stage0/interview.py:56-62` |
| `route_key` | "short stable label for what this statement is about (the field key, preference topic, or project decision). Recorded verbatim" — **free text, no closed vocabulary** | `interview.py:90-95` |
| `route_ref` | the proposal it references, on the `field_proposal` / `source_proposal` routes | `interview.py:153-157` |
| `quote_start` / `quote_end` / `quote_sha256` | `quote_end > quote_start >= 0`; sha 64-hex. **The quote text is not stored here** — the statement is offsets into the captured `onboarding_input` artifact | CHECKs `_offsets`, `_sha` |
| `correction_of_id` | self-FK. "Recorded as durable correction lineage" | `interview.py:160-164` |
| `created_by_actor` | `human` \| `agent` \| `system` | CHECK `volunteered_statement_actor` |
| idempotency | `UNIQUE (onboarding_input_id, entity_id, route_key)` | CHECK |

Route requirements (`interview.py:211-230`): the `claim` route requires `entity_type`, `field_key`,
`value` — and a **contact** claim additionally requires `entity_id`; the `memory` route requires a
memory species (`preference` \| `behavioral_learning`) and a scope level. `unmapped` "is always
legal and is the honest route when nothing else fits: it preserves the quote as evidence without
asserting a fact."

### 7.2 The quote / entailment rule

- **The model quotes text; the engine computes offsets** (PC-C8 §6c-a, `interview.py:70-78`). The
  statement used to carry `quote_start`/`quote_end` and the model miscounted (12 refusals in the
  2026-08-01 acceptance run). Now the model copies the span it means, `locate_quote` finds it by
  **exact substring search** over the captured answer the platform loaded. "There is deliberately no
  fuzzy matching anywhere on this path: the evidence lock's whole guarantee is 'this exact span',
  and approximate location readmits paraphrase through the back door."
- The tool refuses an `answer` whose sha256 does not match the captured `onboarding_input`
  (`stage0_tools.py:1035-1045`) — the model never sends the message back.
- A **typed** value (bool / number / list / object) is admitted only when the quoted sentence entails
  it: `judge_interview_values` runs the M9.3 faithfulness judge **before** the claim exists, in the
  tool's `preconditions` (`stage0_tools.py:1058-1076`), so a failure is a typed refusal the model can
  read and act on.

### 7.3 "Current effective" semantics

`read_statements` (`governed.py:617-671`): the table is append-only, so a client who changes their
mind lands a **new** statement carrying `correction_of_id`. **Latest-correction-wins**: a statement
another statement corrects is superseded and excluded by default — "a retracted 'we target
healthcare' must not keep steering downstream synthesis." `include_superseded=True` gives the full
audit history. Ordered oldest first.

`count_statements_for_input` (`:673`) is the durable answer to "did this turn actually record
anything?" — it spans **every** route kind, keys on the onboarding input (one captured user turn),
and **counts superseded rows**, "because a correction is still a receipt for the turn that made it".
This is what backs the platform's refusal to let a substantive turn finalize `completed` /
`awaiting_input` with no routing receipt.

### 7.4 DSAR reverse binding

The statement stores only offsets + a sha into `onboarding_input.artifact_key`, so erasing the
captured input erases the client's words once. Two derived copies are the exception:

- A judged interview claim keys its `faithfulness_verdict` on
  `claimstore.entailment_judgment_id(field_key, value, quote)` — a content address — **not** on the
  claim id, so every reader must recompute it. `compliance/dsar.py::_tombstone` already does
  (CLAUDE.md `[C8§6c×M9.3/M10.5]`).
- `narrative/support.py::read_faithfulness_citation` and
  `platform/api/clue_api/review/composition.py:~89` still key on the real claim id, so a
  `client_interview_judged` claim reports as **never judged** to provenance and to the review
  surface. Open, owned by the C6/M12 tool-output owner.

### 7.5 `route_key` vocabulary actually used on this lane

`SELECT route_kind, route_key, count(*) FROM volunteered_statement GROUP BY 1,2` — 37 rows total,
**ad hoc, mostly one use each**:

`project_state`: `campaign_outcome` 2, `account_research_request` 2, `selected_product_ids` 2, then
one each of `persona_synthesis_retry`, `discovery_retry`, `operator_role_preference`,
`discovery_wave_size`, `product_set_confirmed`, `campaign_product_intent`, `icp_scope`,
`discovery_target_count`, `product_set_decision`, `program_outcome`, `project.product_focus`,
`icp_gates_accepted`, `product_identity`, `icp_gate_decision`, `icp_selection`,
`icp_draft_authorized`, `persona_seats`, `company_research_artifacts_available`,
`project.sequence.icp_before_strategy`, `campaign_product`, `program_motion`, `icp_gate_approved`,
`icp_spec_accepted`, `icp_change_requested`, `closed_won_pattern_unknown`, `operator_assist`,
`persona_synthesis_requested`, `icp_gi_dac_practices_confirmed`, `brandkit_approved`,
`channel.linkedin_ad_prevea`.

`unmapped`: `project_context_question`, `account_research_question`, `project_status_question`,
`account_discovery_names_request` — one each.

**No `memory`, `claim`, `field_proposal` or `source_proposal` statements exist on this lane.**

---

## 8. Gates

`alembic/versions/3caa27516b81_lane_d_d4_agent_gate_substrate.py` and
`f85ca69b93ba_enforce_unified_agent_gate_contract.py`. Three tables.

### 8.1 `agent_gate` — the question put to a human

`gate_id, workspace_id, project_id, thread_id, turn_id, kind, subject_ref, subject_revision,
expected_subject_sha256, subject_snapshot, max_spend_cents, currency, addressee_user_id, created_at,
permitted_decisions[], snapshot_erased_at, snapshot_erasure_reason`.

| `kind` | Meaning | Agent tool |
| --- | --- | --- |
| `product_set_selection` | confirm the set of products this project targets | `open_product_set_selection_gate@1` |
| `icp_confirmation` | confirm one exact ICP document version and pin it | `open_icp_confirmation_gate@2` |
| `product_selection` | (single-product predecessor) | none in the Stage-0 skill |
| `directive_confirmation` | confirm a research directive | **none** — no Stage-0 tool opens one |
| `plan_approval` | approve a plan | **none** — a plan is born `ready`, no gate |
| `budget_approval` | approve spend, paired with `max_spend_cents` + `currency` | **none** in the Stage-0 skill |

CHECK `agent_gate_kind` pins the six. Lane reality: `icp_confirmation` 3, `product_set_selection` 2.

Other invariants: `permitted_decisions` non-empty and `⊆ {approved, rejected, revised}`;
an `icp_confirmation` gate **must** permit exactly `[approved, rejected, revised]`
(CHECK `agent_gate_icp_decisions`); `expected_subject_sha256` 64-hex — the gate is bound to the
exact bytes presented; `max_spend_cents`/`currency` are both-or-neither and the currency is
`^[A-Z]{3}$`; `subject_snapshot` is an object and may be erased for DSAR, in which case
`snapshot_erased_at` + a non-blank `snapshot_erasure_reason` are set and the snapshot must be `{}`.

### 8.2 `agent_gate_answer` — what the human decided

`gate_id (PK), workspace_id, turn_id, action_ref, decision, answered_by_user_id, answered_at,
expected_subject_sha256, decision_payload, selected_option_ref`.

| Column | Rule | Source |
| --- | --- | --- |
| `decision` | `approved` \| `rejected` \| `revised` | CHECK `agent_gate_answer_decision` |
| PK on `gate_id` | **one answer per gate, forever** | PK |
| `action_ref` | must equal `'turn-action:' \|\| turn_id` | CHECK |
| `expected_subject_sha256` | 64-hex; the digest the human actually answered against | CHECK |
| `decision_payload` | a JSON object — carries a `revised` decision's requested changes | CHECK |
| `selected_option_ref` | only on `approved`, and then `decision_payload` must be `{}` | CHECK `agent_gate_answer_selection_valid` |

Lane reality: 5 answers, all `approved`.

`agent_gate_subject` binds a gate to the entities it is about:
`(workspace_id, gate_id, subject_entity_id)` PK plus a non-blank `binding_kind`.

### 8.3 What the gate means to the agent

From `stage0-interview/v26/SKILL.md` §4–§5:
- The agent **opens** a gate and ends the turn `awaiting_input` with
  `{object_type: "agent_gate", object_id: <gate_id>}` in `open_gate_refs`. It supplies no product
  ids, no project, no addressee — the platform derives the candidates and addresses the human.
- **Approved** mints a `confirmed` version of the ICP document and pins it to the project.
  **Rejected** leaves the proposal as it was. **Revised** carries the human's requested changes in
  the gate receipt; the agent drafts the revision in the same scope and opens a new gate on the new
  version.
- "**A gate receipt is the only authority for any of these outcomes. Ordinary prose such as 'looks
  good' confirms nothing.**"

`gate_decision` is a **different table** — the M9.1 pre-spend gate's append-only audit
(`PreSpendVerdict` = `pass` \| `reject`, `PreSpendKind` = `field` \| `enumeration`). Do not conflate
it with `agent_gate`.

---

## Terms the agent currently gets wrong or has no word for

Read: `platform/agents/catalog/prompts/head-of-abm/v8/SYSTEM.md` (82 lines) and
`platform/agents/catalog/skills/stage0-interview/v26/SKILL.md` (245 lines).

**Named loosely — the word exists in the prompt but points at the wrong thing, or at nothing:**

1. **"promote a claim"** (SYSTEM.md, the authority list). Promotion is `verification_status`
   leaving `unverified`, driven by M9. `CLUE_VERIFICATION_ENABLED=false` on this lane and **every
   ARV2 claim is `unverified`**. The agent is forbidden from an act nothing currently performs, and
   has no word for the state its claims are actually in.
2. **"confirm a research directive"** (SYSTEM.md). There *is* a `research_directive` vocabulary in
   the DB (`research_directive_status` = draft/confirmed/superseded, `agent_gate.kind =
   'directive_confirmation'`) — but it belongs to the old research lane. ARV2 carries the human's
   words as free-text `arv2_research_run.directive_text`, with no directive row and no gate. One
   word, two mechanisms, one of them dead here.
3. **"what tier gets deep research"** (SKILL.md §6b, the plan's required content). `account.scoring.tier`
   exists in the registry and has **zero claims**; `ProjectPhase.TIER_CHECKPOINT` is never reached
   by an ARV2 run (ARV2 launches straight into `ProjectPhase.DEEP`). The agent is told to write a
   plan section about a mechanism this lane does not have.
4. **"settles"** (SKILL.md §7, §8 — "once the account job settles"). Never defined anywhere the
   agent can read. It means the job's terminal transaction: `finish_job` with status ∈
   {`completed`, `needs_review`} **plus** the committee step running inside that same transaction.
   The agent cannot distinguish it from "the job finished".
5. **"There is no memory route on this surface"** (SKILL.md §6). True of the *skill*, but
   `InterviewRoute.MEMORY` exists in the contract and the tool's precondition still refuses a
   memory-routed statement with `memory_not_configured`. The agent is told a route does not exist
   when it exists and is merely unwired.
6. **`effort: "full"`, `committee_cap: 5`** (SKILL.md §7) are given as constants with no meaning
   attached. `effort` has three values (`full` / `reduced` / `cheap-pass`) and `committee_cap` caps
   how many committee members the account agent may seat — the agent has no vocabulary for either
   dial and cannot reason about a cheaper run.
7. **"fit"** (SKILL.md §7b, "lists them on the accounts table with a fit"). The agent is never told
   `fit = passes/gates with unclear counted as half`, nor that a `NULL` fit means unscored and sorts
   after every scored candidate. It can read a 0.5 and not know whether that is "half the gates
   passed" or "every gate was unclear".
8. **"the human approves accounts there by adding them to the project"** (SKILL.md §7b) is correct
   and is the *only* place the agent learns it. But the agent has no word for the consequence:
   an unapproved candidate is **not rejected**, it is unlabelled, and a later run stamps it
   `not_chosen_before` and does not re-surface it. "Rejected" is unrepresentable and the agent may
   well say it.

**No word at all — mechanisms the agent reads the output of and cannot name:**

9. **`outreach_safe` / the restricted sections.** Neither the prompt nor the skill contains
   "outreach_safe", "restricted", "watch-outs", "do-not-mention" or "context-only". The agent reads
   `read_account_research`'s `excluded` dict (keys `sensitive`, `unverified`, `outreach_unsafe`)
   with no vocabulary for what those three words mean or why a count is not a claim.
10. **`use_class` / `sensitive`.** Not named. The one hard rule of the display gate — special
    category never enters *any* section, restricted ones included — is invisible to the agent.
11. **`signal_priority`.** Not named. It is the primary display sort and the agent cannot say why
    one fact appears above another.
12. **`source_tier` and `evidence_span`.** SKILL.md §6 says "the exact quote it rests on" and
    "registered field" — good plain-English stand-ins — but never says tier, and never says that a
    tier-4 claim with no span cannot be promoted. The agent cannot explain *how well* a fact is
    known.
13. **`research_status` values and `refreshing`.** `read_project_accounts` returns
    `not_started`/`in_progress`/`needs_review`/`completed`/`suspended` verbatim plus a `refreshing`
    boolean. The skill names none of them. `needs_review` in particular is a job that failed and is
    waiting for a human, and the agent has no word for it.
14. **`stage`.** A job walks `deep_research` → `synthesis` → `committee` → `member_research`. The
    agent never sees the word and cannot answer "how far along is it" beyond the status.
15. **The three display pages and their 17 section keys.** SKILL.md §7c says
    `section: "overview"` — the *tool argument* — but the agent has no vocabulary for the overview /
    insights / contact pages, their sections, `default_open`, or the fact that an empty section was
    never written rather than written empty.
16. **`merged_into` / merge losers.** Every ARV2 read silently drops them. The agent has no word for
    "that account is the same company under another id".
17. **`added_via`.** Four channels (`discovered`, `imported`, `manual`, `directive`) with a
    first-add-wins rule. `read_project_accounts` returns `added_via` on every row; the skill never
    explains it, and it is wrong to read `manual` as "a human typed it" — a launch stamps `manual`
    too (`account_research_launch.py:336`).
18. **"live claims" vs "current value".** ARV2 shows *every* live claim for a field, not the merged
    winner. The agent will see several rows of the same `field_key` and has no word for why, nor for
    `superseded_by`.
19. **`route_key`.** `record_interview_answer` demands one and the skill never says what a good one
    is. The result is 33 distinct ad-hoc keys, almost all used exactly once — the vocabulary is
    effectively unusable for any later read.
20. **`write_markers`.** 46 distinct marker keys on this lane, including `source_missing` (747) and
    `unevidenced` (202). The agent has no word for "this claim exists but nobody can check it".
21. **The three gate kinds it cannot open.** `directive_confirmation`, `plan_approval`,
    `budget_approval` are permitted by the schema and have no Stage-0 tool. If a human asks "approve
    the budget", the agent has no word for why it cannot.
22. **`persona` order vs `persona` enum.** The skill never lists the five personas (only the
    `icp-synthesis` skill does), and the *display* order (`economic_buyer, champion,
    technical_evaluator, user, blocker`) differs from the enum's declaration order. An agent
    reciting the committee from the enum will list it in a different order than the screen.

**Looked for and not found:**

- A `project_state` table — **not found**. Looked in `pg_tables`, and grepped `platform/`,
  `subsystems/`, `libs/`. The statements live in `volunteered_statement` with
  `route_kind='project_state'`.
- A closed vocabulary for `route_key` — **not found**. It is free text by contract
  (`interview.py:90-95`).
- A closed schema for `write_markers` — **not found**. Open `dict[str, JsonValue]`
  (`claim.py:173`).
- `signal_class` values in use — **not found**. The column exists on `field_definition` and is NULL
  on all 161 rows.
- Any claim `field_key` outside the registry — **not found** (0 rows); the lenient writer
  auto-registers.
- A tool that rejects a discovery candidate — **not found**. `mark_candidates_approved` is the only
  decision write and it only ever writes `approved` (`discovery_store.py:17`).
