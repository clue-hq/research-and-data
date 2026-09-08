# R2 close — before / after (Probook + Zafran)

Before = R2 acceptance run `a0021ecf` (2026-09-08 05:49Z, branch at PR #49). After = R2-close re-run `e5c457d3`
(2026-09-08 12:05Z, `--directive "R2 close re-run"`, HEAD 303b1a084). Same workspace, ICP artifact
`d52f8e36…`, product selection v1, effort full, committee cap 5. Both runs measured with `collect.sh`
(identical queries) and `scripts/arv2_answer_key_recall.py` (leaf-value grading).

## Jobs

| | before Probook | after Probook | before Zafran | after Zafran |
| --- | ---: | ---: | ---: | ---: |
| status | completed | completed | completed | completed |
| model rounds | 17 | 15 | 12 | 13 |
| wall clock | — | 10m13s | — | 7m46s |
| claims written | 85 | 97 | 104 | 113 |

## Answer-key recall

| | before | after |
| --- | ---: | ---: |
| Probook (24 keys) | 0.50 (9 exact / 3 partial / 9 field-only / 3 missing) | 0.50 (9 / 3 / 9 / 3) |
| Zafran (66 keys) | 0.45 (16 / 14 / 27 / 9) | 0.52 (23 / 11 / 21 / 11) |

Zafran's eight gains are all `core.*` keys the widened AI Ark mapper now writes (legal_name, company_about,
employee_range, company_email, primary_tech_stack, tech_stack_categorised, industries_all, company_languages).
Its eleven losses: six `account.resonance.public_frustrations` keys and `media_layer_index` (the media layer was
empty this run — Sanaz Yashar's podcast feed resolved `feed_not_found`; Probook's YouTube episode returned 429),
`hq_location` exact→partial (the `{raw, city, country}` shape grades partial against the key's five-key object),
`total_funding`/`abm_program_maturity`/`named_customers` partial→field-only (the agent wrote its own object
shapes — see schema-invalid below). Probook: `hq_location` up one step, `recent_funding` down one step.

## Link audit (claims with a quote)

| | before Probook | after Probook | before Zafran | after Zafran |
| --- | ---: | ---: | ---: | ---: |
| EXACT | 39 | 55 | 38 | 52 |
| PARTIAL | 21 | 3 | 6 | 12 |
| NOT_FOUND | 27 | 15 | 26 | 18 |
| fetch_failed | 0 | 1 | 0 | 0 |
| EXACT share | 45% | 74% | 54% | 63% |

After-run verdicts all carry a reason in `detail_json`: `on_page`, `partial_on_page`, `not_on_page`,
`page_empty`. No `second_hand_from_report` or `quoted_context` rows this run. Zafran's receipt names its
NOT_FOUND set: Ashby JS boards and the homepage logo span (pages the fetcher cannot render).

## Schema-invalid claims (marker `schema_valid=false`, kept visible)

| | before | after |
| --- | ---: | ---: |
| Probook | 23 of 85 | 22 of 97 |
| Zafran | 22 of 104 | 15 of 113 |

The shapes the close fixed at source are gone: zero AI Ark `hq_location` / funding / revenue rows, zero
structuring rows with an unnamespaced key, one coercion (`coerced_from`). All 37 remaining rows come from the
agent's own `write_claims` (source_key `agent`) or the structuring pass, in four patterns:

1. **string or list into a bare-object field** — `abm_program_maturity` ×6, `gtm_tooling_stack` ×4,
   `claimed_outcomes_metrics` ×4, `product_packaging`, `public_frustrations`, `hiring_velocity` ×2 (18 rows).
2. **object with the agent's own keys where the field names required ones** — `reputation_risk` ×4 (needs
   `what`), `total_funding` ×2 (needs `amount_usd`+`estimate_kind`), `recent_funding` ×3, `employee_range`
   (needs `label`), `strategic_moves` ×2, `attrition_signal`, `buying_culture`, `named_customers`,
   `hiring_velocity_eng` (a number field given an object) (16 rows).
3. **explicit `name: null` on a vacant seat** — 2 rows. The close made `name` optional, but the agent writes
   the key with `null`, and `null` is not a string. `_without_nones` covers the mapper path only.
4. **persona outside the enum** — 1 row (`"marketing/growth leader"`).

Root cause for 1–2: the agent does not see the field's registered `value_schema` when it writes. The catalog
lists field keys and descriptions; the shape is only known to the writer, which records the marker.

## Cost (ledger, phase=result)

| | before Probook | after Probook | before Zafran | after Zafran |
| --- | ---: | ---: | ---: | ---: |
| provider USD | 0.152 | 0.128 | 0.221 | 0.153 |
| AI Ark credits | 3.6 | 2.6 | 3.6 | 2.6 |
| model USD (agent) | **not recorded** | 1.109 (15 calls) | **not recorded** | 0.979 (13 calls) |
| model USD (structuring) | 0.016 | 0.011 | 0.029 | 0.010 |
| total USD | 0.17 + missing | **1.24** | 0.25 + missing | **1.14** |

Every `openrouter/agent_completion` row is `cost_source=metered` (OpenRouter's own `usage.cost`); no
`/generation` lookups were needed and no `gateway.cost_lookup_failed` lines appeared. The agent's own model
spend is ~7¢ per round and is the dominant cost of an account — roughly 8× everything else combined.

## Defect found on the way

The worker refused to start on this DB: the close relaxed `account.committee_candidate`'s schema in place and
`register_field` refuses an in-place redefinition on any DB that already loaded the R2 pack. Fixed by data
migration `320e975d4c46` (commit 303b1a084), proven up→down→up and by reproducing the refusal one step down.

## Follow-ups (not done here)

- Surface each field's `value_schema` to the agent at write time (in the catalog the prompt renders, or in the
  `write_claims` result when the marker is set), and drop `null` optional keys on the `write_claims` path the way
  the mapper does. Expected to remove most of the 37.
- Media layer: two runs, zero media claims. YouTube 429 and `feed_not_found` are external, but the tool should
  try the RSS/YouTube alternates the answer key lists before giving up.
- Zafran's deep-call query was 34k chars (the agent pasted its whole "already established" block); Probook's
  was 2.9k. Cap or summarise that block.
- `hq_location` grading: the key carries five keys, the claim three; decide whether the mapper should emit
  `region`/`country_code` too.
