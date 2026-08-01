# 2026-08-01 — PC-C8 §6c: interview evidence ergonomics (quote-by-text + judge-gated typed values)

Branch `platform/c8-context-card`, base `bb7c6f4`. Implements spec
`docs/specs/PC-C8-stage0-context-card.md` §6c in full (both halves), plus §8's versioning
consequence. Closes the two product decisions the acceptance run left open (close-out findings 2
and 3).

## What landed

### (a) Quote-by-text — §6c-a

`InterviewStatement` drops `quote_start`/`quote_end` and gains **`quote: str`** plus optional
**`occurrence: int = 1`** (`ge=1`). **Mechanism chosen: the fields simply leave the domain model.**
Neither of the two candidates the task offered was needed — `TRUSTED_TURN_FIELD` stripping is
top-level-only by design (`contracts.py:143`; `statements` is a nested list), and an api-local
model-facing variant à la `DeclaredMaterialInput` would have meant maintaining a parallel shape.
The offsets were never authority to be *served* — they were a proxy the engine can compute, so they
have no place on the model-facing model *or* on the tool input model. The **durable row is
unchanged** (offsets + sha, now engine-computed): no migration.

`interview.locate_quote(answer, quote=…, occurrence=…)` is the engine-side locator: exact
`str.find`, character domain (the same decoded string `record_statement` hashes and
`resolve_statement_quotes` slices), non-overlapping occurrence counting so the "only N time(s)"
message agrees with `str.count`. **No fuzzy matching anywhere** — deliberately, per the spec.
Refusals are typed (`InterviewEvidenceRefused`, mirroring `InterviewClaimEntityRefused`):
`quote_not_found_verbatim` (message states "copy the span exactly from the message", and the field
description says the same — F8) and `interview_quote_empty`.

Routing is now **two passes**: `prepare_interview_statements` (locate + entity-resolve; DB) then
`judge_interview_values` (entailment; **no connection held**, since the gateway call is
synchronous), then writes. A turn whose third statement is unquotable therefore records nothing.
The governed tool runs the same pair in `preconditions` for typed model-visible feedback and the
engine re-runs it independently — the same "surfaced twice, guaranteed once" pattern
`resolve_claim_entity` uses.

### (b) Judge-gated typed values — §6c-b

**Type-discrimination rule (`interview.is_judged_value`): the JSON type of the value as it will be
stored in `value_json`, and nothing else.** A JSON *string* keeps the pre-§6c byte-substring check
byte-for-byte (`str(value).casefold() in quote.casefold()`); every other JSON type — bool, number,
list, object, null — goes to the judge. Honest consequence, documented: `"true"` (string) is
byte-checked, `true` (boolean) is judged; they are different values and the model picks.

**Port:** `clue_research.stage0.ClaimEntailmentJudge` —
`async entails(*, entity_id, field_key, value, quote) -> ClaimEntailment(supported, verdict, score)`.
`entity_id` rides along only so the judge's trace span names a real entity. Implemented api-side by
`clue_api.claim_entailment.FaithfulnessClaimEntailmentJudge` over the M9.3 `FaithfulnessJudge`
protocol; injected in `build_toolbelt` → `stage0_tools(entailment_judge=…)` exactly like
`StatementEvidenceReader`. `gateway is None` → no judge → typed values refused
(`claim_value_judge_unavailable`), which is *today's* behaviour, never worse. The judge's prompt,
threshold and persistence are untouched.

**The one deliberate deviation — what `faithfulness_verdict.claim_id` holds on this path.** The
judge caches on `(claim_id, judge_model, prompt_version)`, and an interview claim's id is
`uuid5(onboarding_input, entity, field_key)` — it contains neither the value nor the quote. Keying
the judgment on it would serve a refused attempt's stale `unsupported` to its own correction:
an unrepairable loop, the exact failure class §6c exists to remove. So the judgment is asked under
a **content-addressed question id**, `entailment_judgment_id(field_key, value, quote)` (uuid5 over
a NUL-joined, key-sorted canonical JSON digest; namespace prefix `stage0-interview-entailment:`, so
it can never collide with a claim id). The verdict row's `claim_id` is therefore a *question* id —
recomputable from any written claim's `field_key` + `value_json` + `evidence_span`, so "which
verdict admitted this claim?" is a deterministic lookup. `claim.source_key` is the flag that says
to go looking.

*Key sorting is load-bearing and was found live:* `jsonb` does not preserve object key order, so an
order-sensitive digest recomputed from a stored object value missed every time. Fixed before the
final probe; regression-tested.

**Provenance stamp.** `extraction_method` cannot carry it (closed enum; `llm_synthesis` is pinned to
tier 4 by a DB CHECK and these claims are tier 1/3), and there is no free-text column, so the
distinction lives on **`claim.source_key`**: `client_interview` (byte-literal) vs
`client_interview_judged` (judge-entailed), the latter a newly *registered* source manifest (same
modality/scope/tier — open by registration, not enumeration). **Tier logic is untouched** (1.4's
rule: tier 1 = the client about itself, tier 3 = about another resolved entity). Confidence stays
1.0 — grading it by the judge score was considered and rejected as unrequested scope. The claim
still stores the verbatim quote as `evidence_span`.

### (c) Versioning + F8

One coordinated bump. `record_interview_answer@1` input digest
`5d826d0c…c5af8` → **`6e597a939a364afc1774e32331256d02c14101d33b2641e3851d449eef7c7ecc`**; no other
tool's digest moved. Re-pinned in exactly two places (no other role pins it):

| artifact | version | note |
|---|---|---|
| `skills/stage0-interview/v8/SKILL.md` | **v8** | v7 + new tool sha + §3/§3b rewritten for quote-by-text and the typed-value judge; v7 byte-untouched |
| `profiles/head-of-abm/v11/profile.yaml` | **v11** | v10 + skill v8 sha `016146642ffa…8233` + new tool sha; v10 byte-untouched |

`C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM]` v10 → **v11**. New head-of-abm resource-manifest
aggregate `8fd96075e17a52b33763261e206e4f95c86110d60ad7e175d0564f6a09dd6cf1` (re-pinned in
`tests/api/test_agent_registry_wiring.py`). **`recipe0-stage0-v4.json` pins tool name+version only,
no schema digests — checked, unaffected, no recipe bump.**

F8 rows (`tests/api/test_stage0_tool_guidance.py`): the two offset rows are **removed** (the model
has no such field to break) and replaced by `quote` → `("exactly", "captured user message",
"quote_not_found_verbatim")` and `occurrence` → `("first", "repeats")`; the `value` row now requires
both halves (`verbatim`, `quote`, `claim`, `typed`, `judge`).

### (d) Config fix the live probe forced

`GatewayConfig.judge_model`'s code default is **stale**: `anthropic/claude-3.5-sonnet` returns
"No endpoints found" from OpenRouter, so *every* judged claim failed closed as
`claim_value_judge_unavailable` (and, by the same route, the M9.3 judge and the C1 coverage
evaluator are dead on this deployment). Picking the platform's judge model is a deployment
decision, so the fix is the env seam `synthesis_model` already has — new `Settings.judge_model`
(`CLUE_JUDGE_MODEL`, default `None` = keep the code default), threaded through
`default_gateway_config()`; `.env`/`.env.example` set `openai/gpt-5.6-terra`. **The stale code
default is deliberately left in place** — rewriting a platform-wide policy id is not §6c's call.
Flagged for whoever owns the M9 judge.

## Tests

New `tests/stage0/test_c8_evidence_ergonomics.py` (13, DB + pure, judge stubbed):
`test_locate_quote_is_exact_character_domain_and_never_approximate`,
`test_locate_quote_defaults_to_the_first_occurrence_and_counts_the_rest`,
`test_a_long_bulleted_turn_lands_every_span_the_offsets_used_to_miss` (the 12-failure replay),
`test_a_retyped_span_is_refused_with_repair_feedback_and_writes_nothing`,
`test_a_repeated_span_locks_onto_the_occurrence_the_model_names`,
`test_two_byte_identical_turns_each_locate_into_their_own_capture` (F1-adjacent),
`test_is_judged_value_discriminates_on_the_json_type_and_nothing_else`,
`test_the_hipaa_boolean_lands_as_a_judged_claim_with_its_own_source_key`,
`test_the_document_format_list_lands_as_a_judged_claim`,
`test_a_text_value_never_reaches_the_judge_and_lands_exactly_as_before` (the byte-compare fixture:
the whole claim row, plus "the judge was not consulted"),
`test_an_unwired_judge_refuses_a_typed_value_and_writes_nothing`,
`test_an_unsupported_verdict_refuses_and_a_re_quote_is_a_different_question` (the repair
guarantee), `test_a_judge_that_cannot_be_reached_is_reported_as_unavailable_not_as_disbelief`.

New `tests/api/test_c8_claim_entailment.py` (5, no live LLM): content-addressed judgment identity
incl. jsonb key-order independence; the probe claim's shape (span as evidence, tier 1 so no status
side effect); verdict→admission mapping incl. the sub-threshold `supported`; outage ≠ disbelief;
list values reaching the judge whole.

**Flipped, not deleted** (offset-era tests): `test_c8_turn_binding.py` — `…_of_offsets_alone_…` →
`test_a_governed_call_of_a_quote_alone_lands_the_statement_on_engine_loaded_bytes` (now asserts the
*located* offsets equal the hand-computed pair); the CJK/astral matrix test now proves
`locate_quote`'s character domain (asserts the located offsets are **not** the byte positions);
`test_an_offset_past_the_captured_message_…` →
`test_a_quote_absent_from_the_captured_message_is_refused_and_writes_nothing`;
the entailment and smuggled-authority tests re-expressed in quote terms.
`test_c8_slice0_evidence.py` test 4 now asserts `{quote, occurrence} ⊆ schema` and
`{quote_start, quote_end}` **disjoint**. Also updated: `test_governed_tool_arguments`,
`test_governed_tool_feedback` (its simulated plan issue is now the §6c refusal),
`test_stage0_routing_honesty`, `test_phase_c4_governed`, `test_phase_c5_recipe0`,
`test_icp_synthesis`, `test_c8_project_card_wiring`, `test_catalog`, `test_agent_registry_wiring`,
`test_c8_trial_surface`.

Green: `tests/api tests/agents tests/stage0 tests/clue_trial tests/projections tests/architecture
tests/verification` — the only failure is the documented pre-existing
`test_agent_runtime_wiring_db.py::test_delegation_is_durable_…` (hand-built registry pinning a
stale `evaluate_stage0_readiness` sha). `tests/execution`'s RecipeVersionConflict pair + the
`test_graph_exit` SIGKILL flake are the documented branch-family debt. mypy clean (459 files),
`lint-imports` 24/24, ruff check + format clean on every touched file. `tests/db/test_db_migrations.py`
deliberately not run.

## Live probe — PASS (trial `trial-c8-6c-final`, 5 turns, OpenRouter only, no Sumble)

Server `clue_api.trial_main`, log `/tmp/c8-6c/server3.log`, transcript
`/tmp/c8-6c/probe-final.json`. Server killed afterwards.

**0 HTTP 4xx, 0 offset failures, 0 entailment refusals, 0 Sumble calls.** 10 statements: 3 `claim`,
5 `project_state`, 2 `unmapped`. Turn 1 was the long bulleted multi-fact message — the exact shape
that failed 12× on 2026-08-01 — and every span landed with a receipt.

**The Client KB is populated for the first time from the interview** (3 claims):

| field_key | value_json | source_key | tier | evidence_span |
|---|---|---|---|---|
| `client.product` | `"Aura AI automates surgical scheduling and pre-authorization paperwork"` | `client_interview` | 1 | same text |
| `client.delivered_value` | `"throughput certainty for the practice"` | `client_interview` | 1 | `"what it delivers is throughput certainty for the practice"` |
| `client.icp_evidence` | `{"states":["Texas","Florida","Arizona"],"surgeon_count":{"max":15,"min":2},"customer_profile":"independent neurosurgery practices"}` | **`client_interview_judged`** | 1 | `"they are independent neurosurgery practices, sized 2 to 15 surgeons, located in Texas, Florida and Arizona"` |

Recomputing `entailment_judgment_id` from that stored claim yields
`5ec0d797-3d04-5b54-8e30-92f975f1ec09`, which resolves to its `faithfulness_verdict` row:
`verdict=supported, score=1.0, judge_model=answering_model=openai/gpt-5.6-terra, prompt_version=v1`.
The provenance join works end to end.

Transcript excerpts (assistant, verbatim): *"I've recorded the ICP boundary, buying roles, campaign
exclusion, and early-traction geography through the interview routing receipt."* /
*"The interview-routing receipt completed for the customer ICP evidence."*

## Findings / deviations to carry forward

1. **The client field pack has no boolean and no string-list field**, so the two *original*
   acceptance facts — "we are fully HIPAA compliant" (boolean) and "SOAP, APSO, and H&P" (list) —
   still land as `unmapped`, and the model said so precisely and honestly: *"no registered client
   field currently fits HIPAA/BAA posture"*, *"no registered client field currently fits it"*. The
   §6c-b mechanism is proven live on the registered **object**-valued field (`client.icp_evidence`,
   the field's documented purpose), which is the same typed-value class. Adding
   `client.compliance_posture` / `client.document_formats` to `CLIENT_KNOWLEDGE_PACK` is the honest
   next step, but it changes reverse-profiling coverage denominators and the surface-class mapping
   (`test_stage0_static`), so it is a **product decision about which client facts exist**, not a
   §6c change. Deliberately not taken. (The unit tests register the two fields locally to exercise
   the bool/list paths.)
2. **`GatewayConfig.judge_model`'s code default is dead** — see (d). Every LLM-as-judge call site is
   affected, not just this one. Owner: whoever owns M9.3 policy.
3. **Interview claim identity still excludes the value.** `_write_claim`'s
   `uuid5(onboarding_input, entity, field_key)` means two different values for one field in one turn
   collapse to the first written claim. Unchanged by §6c and correct as an idempotency key, but it
   is *why* the judgment needed its own content-addressed identity; if claim identity is ever
   revisited, revisit the two together.
4. **`faithfulness_verdict` rows now exist for questions whose claim was refused** (append-only
   audit, no FK). Harmless and useful as a cache, but a reader that assumes every verdict's
   `claim_id` names a live claim will find orphans on this path. Documented at the site.
5. **CORRECTED (review round, see below) — this entry was wrong as first written.** It said the
   backlog's `faithfulness_verdict.rationale` gap merely gained "a second producer: same fix, wider
   blast radius". That is factually false: the existing redaction does not apply *at all* on this
   path. `compliance/dsar.py` redacts `WHERE claim_id = <erased claim id>`, and a §6c-b verdict is
   keyed on the *entailment-question* id, so the WHERE matched **zero** rows — verified live —
   while the rationale went on quoting the client's own words. Left as written, the scheduled
   follow-up would have been implemented, believed complete, and missed every row on this path.
   **Fixed in the review round** (below); the real mechanism is now in the repo `CLAUDE.md`
   backlog.
---

## Review round (2026-08-01) — NEEDS-FIX-ROUND addressed

The mechanism was verified correct end to end; two must-fixes and three pin-downs landed in one
follow-up commit.

**F1 — the judge-model seam broke `tests/gateway/test_gateway.py::test_model_id_is_config_swappable`.**
`Settings` reads `.env` through `env_file`, so the on-disk `CLUE_JUDGE_MODEL` reaches
`default_gateway_config()` even with the variable unexported, and the test's hardcoded
`anthropic/claude-3.5-sonnet` base assertion failed. My green-list never included `tests/gateway` —
the suite owning the file I changed. **Fix shape:** the test's property is "an overlay swaps the id
with no code change", so the base is now asserted against `default_gateway_config().judge_model`
(whatever the deployment resolved) plus `swapped_model != default_model`; the *code* default is
asserted separately and deployment-independently as `GatewayConfig().judge_model ==
"anthropic/claude-3.5-sonnet"`. Whole gateway suite green both with the env sourced and under
`env -u CLUE_JUDGE_MODEL -u CLUE_SYNTHESIS_MODEL`. `tests/test_config_settings.py::
test_c7_activation_controls_are_independently_default_off` fails **only** when `.env` is exported
into the process env (`CLUE_C7_RESEARCH_VIEW_READ_ENABLED=true` leaks past that test's
`_env_file=None`); verified pre-existing by running it on a stashed tree and with `env -u` —
verified, not fixed, as instructed.

**F2 — DSAR redaction could not reach §6c verdict rows. Fixed, not just ledgered.**
`entailment_judgment_id` **moved to `clue_research.claimstore`** (new
`claimstore/entailment_identity.py`, exported from the package). That is the least-invasive legal
home: `compliance` and `stage0` are in an import-linter *independence* contract so compliance may
not import stage0, and `clue_api` is off-limits to both — but `claimstore` is the shared substrate,
already imported by `compliance/dsar.py`, `stage0/interview.py` and `clue_api`, and its own rule
("imports only `core` and `db`") is satisfied by a dependency-free sha256+uuid5 function. So: **no
`clue_core` contract-delta, and no compliance-local duplicate + drift-guard** (the
`conflict_tier_threshold` precedent was the fallback, not needed). One definition, three importers.
`compliance/dsar.py::_tombstone` now recomputes the question id from the erased claim's
`field_key` + `value_json` + `evidence_span` and redacts `claim_id = ANY(...)` over both ids; a
span-less claim was never judged this way and contributes no second id. Documented consequence: two
subjects whose claims share field + value + span share one question, so erasing either redacts the
shared rationale — correct, since the rationale quotes that exact text.

**Red-proof of the new test.** `tests/compliance/test_dsar.py::
test_dsar_erases_the_rationale_of_a_verdict_keyed_on_the_entailment_question` inserts a verdict
under the recomputed question id, erases the contact, and asserts the rationale is NULL, redacted-at
is stamped, the reason is `erasure`, the bounded audit metadata (`verdict`, `judge_model`) survives,
and the sentinel appears in **no** rationale in the table. Reverting the WHERE to the claim-id-only
match fails it loud on `assert row[0] is None, "the judged claim's rationale survived erasure"`
(reproduced by temporarily re-adding `AND claim_id = :legacy_only`); restored and green.

**Pin-down 1 — the corroboration-independence invariant is now stated and tested.**
`independent_source_count` unifies claims sharing a `source_url` host **or** a `source_key`. Two
turns of one conversation carry different `interview://<onboarding_input_id>` hosts, so `source_key`
was the *only* thing stopping the client's own repetition from corroborating itself — and §6c-b
split that key in two. It is safe for exactly one reason: the two species can never land in the same
value group, because `is_judged_value` sends every non-string to the judge (so a `client_interview`
value is a JSON string by construction, a `client_interview_judged` value never is) and
`values_agree` equates nothing across JSON types under any `equality_mode`. That is a coupling
across three files and would break silently if either side moved (the `semantic` mode equating
`"true"` with `true` is the plausible route). Documented at the `source_key=` stamp in
`interview._write_claim`; pinned by `tests/stage0/test_c8_evidence_ergonomics.py::
test_one_conversation_is_one_source_however_its_values_earned_entry`, which routes two real turns
and asserts `independent_source_count == 1` for the byte-literal pair, `values_agree` false across
**every** `EqualityMode`, and — stated as the property it protects — that the cross-species pair
*would* count as 2 if they ever co-grouped.

**Pin-down 2 — M12/review blind spot ledgered** in the repo `CLAUDE.md` backlog alongside F2's
entry, naming the recompute mechanism explicitly: `narrative/support.py::read_faithfulness_citation`
and the review annotation reader (`clue_api/review/composition.py:~89`) both key on the real claim
id, so a `client_interview_judged` claim reports as never-judged to M12 provenance and the review
surface. Owner is the C6/M12 tool-output & provenance owner, not PC-C8.

**Pin-down 3 — cosmetic.** `locate_quote` now refuses `occurrence < 1` as the caller error it is
(`ValueError("occurrence must be 1-based")`) instead of falling through and reporting a span that is
right there in the message as absent — unreachable through the schema's `ge=1`, but the function is
public. The two documentation mentions (coverage-report phantom channels; the C7 provider label
rendering the raw string) went into the `CLAUDE.md` ledger entry, not into code.

**Re-run:** `tests/api tests/agents tests/stage0 tests/clue_trial tests/projections tests/gateway
tests/verification tests/compliance` — only the documented pre-existing
`test_agent_runtime_wiring_db.py::test_delegation_is_durable_…` fails. mypy clean, `lint-imports`
24/24, ruff check + format clean on every touched file.
