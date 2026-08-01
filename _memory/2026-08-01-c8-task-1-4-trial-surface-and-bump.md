# 2026-08-01 — PC-C8 task 1.4: the trial capability surface + the one coordinated bump

Branch `platform/c8-task-1-4`, base `7d0397e` (`platform/c8-context-card`). Implements spec §8 in
full — including both v2.2 rows — plus the reword/recursion/B1 handoff list task 1.3 left.
One coordinated bump: skill `stage0-interview/v7` + profile `head-of-abm/v9`; v6/v8 byte-untouched.

## 1. The surface-policy mechanism (§8's core)

New `clue_agents.registry.AgentSurfacePolicy` — a frozen dataclass carrying
`surface`, `role`, `withheld_tools` (names), `withheld_reason_code`, `framing`.
`AgentProfileRegistry(..., surface_policies=...)` resolves every declared surface **eagerly** at
composition; `registry.resolve(role, surface=...)` returns it. An undeclared surface raises rather
than falling through to full authority.

**It is a ceiling, not a second profile.** The role keeps one reviewed profile resource (same
`profile_ref`, same prompt, same pinned digests); the surface subtracts addresses from the
effective ceiling `_resolve_resource` already computes for delegation. Everything downstream
therefore follows *automatically*, because it already reads the effective set:

- `build_agent_resource_manifest(tools=profile.tools)` → the manifest the constitution pins is the
  filtered set (asserted directly: `manifest names == effective names`, and it differs from base);
- `_capabilities_for` → withheld tools disclose `profile_unavailable` /
  `trial_manual_conversation_only`, so the generated map shows them under "not available";
- `ExactAgentToolSurfaceMiddleware._allowed` → a withheld tool arriving at model-call time is
  `undeclared runtime tools were installed`.

The **framing prose** lives on the policy and is rendered into `generated_resource_map` as a
`Surface policy:` block beside the withheld list — one place, so the words and the enforcement
cannot drift. It is not a pinned catalog resource; it is code-defined data, the same class as the
rest of the generated map (which the manifest has never covered).

**Guardrail:** a policy that withholds a tool the role's profile does not pin is refused at
composition (`does not pin`), as is an empty `withheld_tools`. That is the exact way a surface
restriction rots — a rename, a stale name, and the capability is quietly back.

Composition: `C6_SURFACE_POLICIES` + `STAGE0_CONVERSATION_TRIAL_SURFACE` in
`agent_registry_wiring.py`, passed into `build_agent_profile_registry`. Trial root threads the
surface through all four sites: `stage0_trial.py` (`create` + `run_turn` resolves),
`HeadOfAbmStage0Runtime(surface=...)`, `build_head_of_abm_stage0_execution(surface=...)`. The
runtime/execution sites *must* match, because they compare
`constitution.resource_manifest_sha256` against the resolution they make themselves.

### The `submit_onboarding_input` decision — WITHHELD

Withheld alongside `start_recon` and `synthesize_icps`, on **policy** grounds, not safety.
Reasoning recorded at `C6_SURFACE_POLICIES`:

- the trial's rule is that the agent never captures — `Stage0Trial.run_turn` writes the `user_turn`
  capture itself, `actor='human'`, before the model is woken;
- task 1.2's F1 fix (capture lookup scoped by `project_id` + `actor='human'`) already made an
  agent-written row harmless to the turn binding, so this is *not* re-fixing a hole — 1.2's
  scoping stays as defence in depth;
- what remains is that the tool has no honest use here. Its consumers of a fresh capture were
  `start_recon` (withheld) and the human upload boundary (absent on this surface), so every
  reachable call writes an `actor='agent'` capture record for a turn the platform already
  captured: durable noise with misleading provenance.

`submit_ingestion` is deliberately **kept** — it ingests an already-captured workspace artifact and
does no external research, so it does not cross this surface's boundary. Widening beyond the three
would have been unrequested scope.

### The regression this design could have shipped silently

`_resolve_resource` drops a skill when any `required_tool` is not effective. Skill v6 required
`start_recon`/`synthesize_icps`/`submit_onboarding_input`, so withholding them would have deleted
**the whole `stage0-interview` skill** from the trial. Skill v7 therefore drops those three from
its `tools:` pin list (they stay on the profile, so the full surface is unchanged), and the body
gained a generic paragraph: the resolved capability map is authoritative, a tool this skill names
may not be installed where you are running, never simulate an absent tool. There is a dedicated
test for exactly this (`test_the_stage0_skill_survives_the_narrowed_surface`).

## 2. Skill v7 body

Routing-procedure only. Two additions: the surface paragraph above, and a §3b bullet **"Never
author an entity id"** (the routing-procedure half of B1 layer 2). No trial-specific content —
asserted: the body contains neither "manual-conversation-only" nor "trial".

## 3. Description rewording (8 fields / 5 tools)

Per 1.3's corrected list: `brand_id` on `submit_onboarding_input`, `start_recon`,
`record_interview_answer`, `evaluate_stage0_readiness`; `client_entity_id` on
`submit_onboarding_input`, `record_interview_answer`, `evaluate_stage0_readiness`,
`start_confirmed_project_run`. All now read "Trusted brand/client-entity authority; supplied by the
platform, never by you." The three bare `client_entity_id` declarations (`confirm_icp`,
`import_accounts`, `synthesize_icps`) left alone. The `stage0_tools.py` NOTE block and the F8
comment block both record that 1.4 closed this.

## 4. B1 layer 2 — engine-defaulted entity + typed refusal

`InterviewStatement._route_shape` no longer requires `entity_id` on the claim route; it requires it
only when `entity_type=contact` (there is no trusted default for a person).

New `interview.resolve_claim_entity(...)` (public, exported) owns both rules:

- **default** — an `account` claim with no `entity_id` becomes the caller's trusted
  `client_entity_id` (the constitution value);
- **existence check** — the resolved id must be a live `account_entity`/`contact_entity` **in this
  workspace**; otherwise `InterviewClaimEntityRefused(reason_code=...)`.

**Chosen typed outcome: refuse.** `interview_entity_not_found` (unresolvable id) and
`interview_entity_required` (contact with no id). The behaviour it replaces accepted any well-formed
UUID and expressed its doubt as a *silent* `source_tier=3` downgrade — a durable claim about an
entity that does not exist, signalled only by a tier the model never saw. Tiering is now an
explicit statement about a **verified** entity: tier 1 = the client about itself, tier 3 = the
client about another resolved entity.

Surfaced twice, deliberately: `RecordInterviewAnswerTool.preconditions` calls the *same* function
and maps the refusal to a model-visible `PreconditionFailure`; `route_interview_answer` refuses
independently, so the guarantee does not depend on the precondition being called. The resolved id
(not the model's) is what `_write_claim` and `record_statement` both persist.

## 5. M1 — HOIST, not recurse

Chosen deliberately, and it is the cheaper *and* stronger option:

- recursing the strip means generating variant sub-models with fields deleted, which breaks nested
  `model_validator(mode="after")` bodies that read them (`DeclaredMaterialContext._validate_routes`
  reads `project_id`), plus a matching nested injector and nested plan-arg guard — permanent
  machinery defending a shape that should not exist;
- hoisting leaves the seam as one simple top-level rule and removes the thing it could not reach.

`ProposalScopeInput` lost `brand_id`/`project_id` (`for_workspace` → `for_execution`, joined by the
new `_resolved_scope` helper). `SubmitIngestionInput` gained them at top level; its
`declared_context` is now an api-local `DeclaredMaterialInput` (the caller-authored remainder), and
the **domain** `DeclaredMaterialContext` is untouched — rejoined engine-side by `for_execution`, so
the durable idempotency key (declared-context hash) keeps its exact shape and values. The domain
model's own route rules now bind across the split and are reported as a typed
`ingestion_context_invalid` precondition rather than a bare `ValidationError` from a spend path.
The HTTP upload transport's `X-Ingestion-Context` header contract is unchanged; the route splits it
(`DeclaredMaterialInput.of`).

**The permanent gate:** `tests/architecture/test_model_facing_authority.py` walks every toolbelt
descriptor's model-facing schema (post `_with_trusted_runtime`, post provider transform) at **every**
depth — `properties`/`items`/`$defs`/`anyOf`/`allOf`/`oneOf`/`prefixItems`/`additionalProperties` —
and fails if any `MODEL_FORBIDDEN_AUTHORITY_KEYS` name appears. A second test guards the guard (a
walk that silently stopped at depth 1 would pass forever). The `contracts.py` docstring's
"three live exceptions" paragraph is replaced by a pointer to it.

## 6. Digests that moved, and where re-pinned

Eight of the ten head-of-abm tools. `get_research_view` and `synthesize_icps` did **not** move.

| tool | new `input_schema_sha256` | why |
|---|---|---|
| `evaluate_stage0_readiness` | `6e33bb67…1196` | brand/client reword |
| `propose_field` | `ee3cfb5f…513f` | M1 hoist |
| `propose_source` | `64125234…ef5b` | M1 hoist |
| `record_interview_answer` | `5d826d0c…5af8` | brand/client reword + `entity_id` description |
| `start_confirmed_project_run` | `5d855fe7…3cac` | client reword |
| `start_recon` | `f16f3118…0f9e` | brand reword |
| `submit_ingestion` | `9b0a3d6c…83c9` | M1 hoist |
| `submit_onboarding_input` | `bb138205…4ce7` | brand/client reword |

Re-pinned in **two** places only (no other role pins any of them):
`platform/agents/catalog/skills/stage0-interview/v7/SKILL.md` (6 of them; the other 3 left the
skill's required-tool list) and `platform/agents/catalog/profiles/head-of-abm/v9/profile.yaml`
(all 8, plus the v7 skill sha `2b76bd6c…17b2`). `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM]` v8 → v9.
New head-of-abm resource-manifest aggregate `48a2abd0d2031db67625e58f8eb62b19ef1ddae2fdc627a7f97636a6b544270d`
(re-pinned in `tests/api/test_agent_registry_wiring.py`).

## 7. Tests

New `tests/api/test_c8_trial_surface.py` (8, AC-7): withholds exactly the three; the manifest is
the filtered set and differs from base; the capability map names the surface, its framing, and
`trial_manual_conversation_only`; the skill survives; the middleware refuses a smuggled
`start_recon`; a policy withholding an unpinned tool or nothing at all is refused; an undeclared
surface raises; every declared policy resolves.

New `tests/architecture/test_model_facing_authority.py` (2): the repo-wide depth walk + the
guard-the-guard.

`tests/api/test_c8_project_card_wiring.py`:
- `test_a_claim_route_statement_from_the_cards_id_lands_as_a_tier_1_claim` — **R1**, end to end
  through the real `route_interview_answer` (card → statement → durable claim, `source_tier == 1`).
  Replaces 1.3's construction-only version.
- `test_an_account_claim_defaults_its_entity_and_an_unknown_one_is_refused` — the default lands
  tier 1; an unknown id raises `interview_entity_not_found` and the claim count does not move; a
  contact claim with no entity is still a validation error.

Updated: `tests/api/test_stage0_tool_guidance.py` (F8 rows — `entity_id` must now state
`claim`/`leave it out`/`already exist`/`refused`/`contact`; comment block rewritten),
`tests/agents/test_catalog.py` (v7/v9 in the listing), `tests/api/test_agent_registry_wiring.py`
(manifest sha, skill address, materialized path), `tests/api/test_stage0_trial.py` (profiles stub
takes `surface=`), `tests/api/test_toolbelt_wiring.py` + `tests/proposals/…` +
`tests/ingestion/test_tools.py` (hoisted inputs).

## 8. Verification

`tests/api tests/agents tests/stage0 tests/clue_trial tests/projections tests/architecture` — the
only failure is the pre-existing `test_agent_runtime_wiring_db.py::test_delegation_is_durable_…`
(it hand-builds a registry selecting the frozen `head-of-abm@v1`, whose pins are stale on a clean
tree). Whole-tree run diffed against a stashed-baseline run of the same command: **identical
37-failure set**, plus one flake (`test_graph_exit.py::…[after_cursor_update-0]`, a SIGKILL timing
test that passes in isolation). `mypy` clean (456 files), `lint-imports` 24/24, `ruff check` clean
repo-wide, `ruff format` clean on every touched file. `tests/db/test_db_migrations.py` deliberately
not run; no live trial run.

## Deviations / notes for review

1. **The framing prose is code-defined data, not a pinned catalog artifact.** Spec §8 allows
   "surface policy artifact / profile prompt of the trial variant". A separate pinned artifact
   would have needed its own catalog kind + sha discipline for ~2 sentences; putting it on the
   policy keeps it adjacent to the enforcement it describes. If a later slice wants it byte-pinned,
   promoting `AgentSurfacePolicy` to a catalog resource is additive.
2. **Skill v7's required-tool list shrank by three.** Necessary (see §1's regression), and it is the
   honest reading of `required_tools` — a disclosure gate, not a claim that the procedure is
   useless without them.
3. **AC-7's last clause** ("a profile advertising an omission-resolving tool it doesn't install is
   a failing contract test") is not covered here: the card carries typed omission *kinds* and
   cursors and names no tool, and the inspection tools land in task 1.5. That clause belongs with
   1.5's tools.
4. **`stage0_recipe.pins_for`'s nested fallback** (`scope`/`declared_context`) is now live for
   `product_id` only; commented rather than narrowed, since the loop is uniform over three fields.
5. **`start_confirmed_project_run.client_entity_id`'s old description** carried lineage wording
   that the reword drops. It is a stripped field no model reads, and the model-visible siblings
   (`client_kb_version`, `icp_key`, `icp_version`, `product_context_version_id`) still carry
   "lineage" — the F8 gate asserts that.
