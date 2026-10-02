# Live defect #29 — "projected evidence span is absent from retained artifact" (2026-08-20)

Job `eea48931-2798-54d7-b631-5320fd65b869` (run `1d39023a`, account Millennium Physician Group
`17aab088-…`) suspended at `2026-08-19T20:44:08Z` with
`EntityResearchResultIntegrityError: projected evidence span is absent from retained artifact`.
No commit (orchestrator commits); no live-DB writes; services untouched.

## The exact call

Journal (`entity_research_agent_event`, job `eea48931`):

* event **2910** — `enrich_account {core.industry, core.employee_count, core.hq_location}` /
  `sumble_organizations` → governed refusal `account_gap_ineligible` (industry already resolved).
* event **2914** — the model's repair: `enrich_account {core.employee_count, core.hq_location}`.
* event **2915/2916** — `tool_failed` / `execution_failed` with the span error.

That retry is `account_gap_operation 7e29c0bf-…` (succeeded, 3 credits). Its receipt settles
`core.employee_count` **resolved** and `core.hq_location` **conflict** with
`conflicting_claim_ids = [06a15aa3 (sumble_organizations), 5c8d81fa (exa_websets),
4a03dca8 (exa_websets)]`. So the crash only reached the projection path on the *retry*, because the
first shape was refused before dispatch — exactly the "preceding governed refusal" lead.

## Which span, and what the artifact actually holds

The Sumble claim is fine — `06a15aa3` cites `"headquarters_country":"US"`, which is literally in
`ws_…/110291e2…` (`{…,"headquarters_country":"US",…}`). The failing spans are the two **contender
`exa_websets` claims** the conflict projection published:

| claim | span at rest | cited artifact | present? |
|---|---|---|---|
| `4a03dca8` `core.hq_location` | `Exa company properties company.headquarters\|company.location: {"city":"Fort Myers","country":"United States","country_code":"US","raw":"Fort Myers, United States","region":"Florida"}` | `ws_…/367dd5cf…` | **no** |
| `5c8d81fa` `core.hq_location` | same text | `ws_…/b361cc97…` | **no** |

The retained Exa item holds `"headquarters":{"address":"6321 Daniels Pkwy Suite 200","city":"Fort
Myers","country":"United States","countryCode":"US","postalCode":"33919","state":"Florida"}` and
`"location":"Fort Myers, United States"`. The span was a *sentence about the normalized platform
value*, not a quotation of the provider bytes — so the guard was right and the writer was wrong.

**Blast radius (read-only audit of all 246 live claims carrying an `artifact_key`):** every one of
the 187 `exa_websets` claims fails the guard (11 field keys); **every other source passes**
(`sumble_organizations` 17, `sumble_jobs` 8, `sumble_tech_stack` 4, `exa_deep` 21,
`firecrawl_site` 5, `client_interview` 2). The Sumble resolver already quotes canonical members
(`resolvers/sumble/__init__.py::_json_member_span`); Exa never did.

## Two defects, both fixed at the root

### D1 — `exa_websets` spans were described, not quoted

`platform/api/clue_api/exa_websets_materialization.py:420` (`_base_span`, pre-fix) built
`f"Exa company properties {provider_field}: {canonical_json(value)}"`; `_enrichment_span` joined
reasoning + reference snippets with `\n`; `_candidate_span` joined evaluation criteria. None of the
three is findable in the retained item. `core.employee_range` / `core.revenue_band` inherit the
source claim's span (`account_field_derivation.py:310`), so they were collateral.

Fix: new `_RetainedItem` cuts every span **out of the retained bytes**. Retained webset items are
stored as canonical JSON (`json.dumps(sort_keys=True, separators=(",",":"))` — D3
`exa_websets_lifecycle.py:770` and targeted enrichment `exa_targeted_enrichment.py:1149`), so
re-rendering any contained object reproduces the exact bytes and any contiguous slice of it is a
literal substring:

* `provider_member_span("company.employees")` → `"employees":819`
* `provider_member_span("company.headquarters|company.location")` → one contiguous run
  `"headquarters":{…},"industry":null,"location":"Fort Myers, United States"` (alternatives must
  share a container, so the cut is never a fabricated join)
* `enrichment_span(id)` → the retained `enrichments[i]` object verbatim (reasoning + references +
  result)
* `evaluations_span()` → the retained `"evaluations":[…]` member (the discovery-provenance span)

`ensure_exa_company_field_claim` now **requires** `retained_item: bytes`, checks the bytes are the
cited artifact (`content_address`), and takes `enrichment_id` to pick the enrichment branch
explicitly. `ExaRetainedSpanError` fails closed: a span that cannot be cut is not written.
Both call sites thread the bytes they already have (`_PreparedItem.retained`; `item_bytes`).

### D2 — the Sumble conflict projection published contenders' evidence

`sumble_entity_research_tools.py::_field` projected `ResearchEvidenceProjection` for **every**
conflicting claim, so a `sumble_organizations` result carried `exa_websets` artifacts and spans.
That is what walked the foreign claim into the guard — and D1 alone would not have unblocked the
run: the very next engine check (`entity_research_tools.py:2135`, "projected evidence violates
exact field/source authority") refuses it too, because the live request's authority is
`{core.hq_location: [sumble_organizations]}`. A Sumble result citing an Exa artifact is provenance
laundering, not corroboration.

Fix: evidence is filtered to `row["source_key"] == field.source_key`; contenders stay fully
reported as `claim_refs` + the durable `conflict:` decision ref. Also: the provider's own claim is
now explicitly added to the contender set when the corroborator's group omits it (the
`AccountGapFieldResult` validator does not require membership), so a CONFLICT can never project
zero evidence.

**Note:** D1 stops new bad spans being born; it does **not** rewrite the 187 live claims. D2 is
what makes the live data safe to project, and the regression is written against the legacy span
shape for exactly that reason.

## Red-proof

`tests/api/test_evidence_span_provenance_db.py` (new, 2 tests). The engine's own predicate
(`_json_contains_text`) and the engine's own validators (`EntityResearchResultStore._validate_*`)
are the oracles — no re-implementation of the rule.

* `test_every_exa_websets_claim_span_is_verbatim_in_the_retained_item` — real D4 materializer over
  a live-shaped Millennium item. **Verified red** with D1 reverted: 8 described spans
  (`core.annual_revenue`, `core.hq_location`, …).
* `test_a_sumble_conflict_projects_only_its_own_retained_evidence` — real `SumbleAccountGapStarter`
  + `SumbleAccountSemanticEnrichmentAction` + `SumbleEntityResearchLineageReader` +
  `EntityResearchResultStore._validate_artifacts/_validate_fields`, with the contender planted
  carrying the **legacy** live span. **Verified red** with D2 reverted, raising the exact live
  message `projected evidence span is absent from retained artifact`. Its last assertion re-adds
  the contender's evidence by hand and requires the guard to still refuse — the strictness is not
  relaxed.

Also proved directly against the real live artifact `ws_…/367dd5cf…`: every `_RetainedItem` span
is verbatim.

## Verification

* Green: `tests/api/test_evidence_span_provenance_db.py`,
  `test_exa_websets_materialization_d4.py`, `test_sumble_account_gaps_s1.py`,
  `test_fi2_63_sumble_freshness_db.py`, `test_sumble_unreconciled_spend_settlement_db.py`,
  `test_exa_targeted_enrichment_e1.py`, `test_account_field_derivation.py`,
  `test_comprehensive_account_execution_db.py`,
  `tests/integration/test_comprehensive_research_harness_db.py`, the four other
  `test_exa_websets_*` files.
* `tests/durable` + `tests/discovery_scoring`: 15 failures, **identical set at HEAD**
  (pre-existing). `tests/api/test_research_derivations.py`: 5 failures, identical at HEAD
  (`EntailmentReasonCode` enum, unrelated).
* ruff + ruff-format clean on all changed files; `uv run mypy` clean (732 files).
* Throwaway DB `clue_span_checks` created, migrated, used, dropped.

## Residuals

* **187 live `exa_websets` claims keep their described spans.** They are not fabricated (the values
  do come from the cited artifacts) but they are unquotable, so any *other* surface that projects
  an `exa_websets` claim's evidence into a governed result will hit the same guard. D2 covers the
  Sumble conflict path; nothing else projects them today. A backfill would have to recompute each
  span from its retained item — mechanical, since `_RetainedItem` is the recipe, but it rewrites
  append-only claim rows and needs its own decision.
* **`git stash` is unsafe in this workspace.** A concurrent agent races the stash reflog: a
  `push`/`pop` pair during red-proofing popped someone else's stash and left mine orphaned
  (recovered via `git fsck` → `git restore --source=<dangling>`). Red-proof by reverting with
  `git restore --source=HEAD --worktree -- <files>` and restoring from a copy instead.
