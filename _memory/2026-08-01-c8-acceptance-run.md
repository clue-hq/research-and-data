# PC-C8 Slice 1 live acceptance run — 2026-08-01 (PASSED with one gap found)

Branch `platform/c8-context-card` at `3715122` ("fix(c8): key the captured-turn cache on the turn, not
on the turn's bytes"). Task 1.6, contract `docs/specs/PC-C8-stage0-context-card.md` §12 item 12.
Live run against the local trial server (`clue_api.trial_main`, `http://127.0.0.1:8010`) with real
OpenRouter spend on `openai/gpt-5.6-terra`. **No Sumble spend** — Stage-0 conversation scope only;
`/account add` and `/research` were never called.

Driver: a programmatic HTTP client over the same surface `scripts/clue_trial.py` uses
(`POST /v1/trials`, `/turns`, `/product:confirm`, `/icps:synthesize`, `/icps/N:confirm`,
`GET /v1/trials/{id}`, `/report`). `doctor` reported `ready: true`, single migration head
`933c7b604f1c`.

## Verdict

**The slice meets its §12-12 live gate.** Every criterion the gate enumerates — statements routed,
product gate, grounded ICP, quit/resume, 25+ turns with no 422, breadth extension exercising the
statement cap and its omission path — passed live.

**One separate gap was found: AC-3 does not hold live.** Both §7 inspection tools are refused at the
C5 slot, so the omission cursors the card hands the model cannot be resolved by anything. Details
below. This is not one of the §12-12 clauses, but it should be fixed before the slice is considered
complete against §12 as a whole.

## Scale of the run

80 conversation turns total, **zero HTTP 4xx of any kind** (no 422 anywhere in either access log),
zero client-side errors. 75 turns finalized `awaiting_input`, 5 finalized `blocked` — all five
honestly, with actionable repair text and nothing fabricated.

| Trial id | Workspace | Turns | Purpose |
|---|---|---|---|
| `trial-acceptance-c8-aura` | `s0-trial-acceptance-c8-aura-b6a29a3f` | 49 | Phase A script, Phase B 25+-turn extension, Phase C3 cap extension |
| `trial-acceptance-c8-breadth` | `s0-trial-acceptance-c8-breadth-962aaa50` | 31 | Phase C paste-breadth extension |

## Phase A — the Aura/neurosurgery script (PASS)

- **Statements routed.** 10 turns, one durable `onboarding_input_id` each, 14 statements. Every
  material turn returned a routing receipt in the assistant text.
- **Correction/supersession live.** The mid-conversation narrowing ("not all providers → independent
  practices only") wrote a second `project_state/target_market` statement carrying
  `correction_of_id`, and every downstream summary honored it.
- **Summary probe.** The agent reproduced product, target market (correction applied) and the buying
  committee accurately, and kept the documentation-time claim explicitly customer-reported — the
  card carried the interview faithfully.
- **Product gate.** `/product:confirm` → `{"confirmed": true}`.
- **Grounded ICP.** `/icps:synthesize` → `status=grounded`, `reason_codes=["no_client_kb_claims"]`,
  `excluded_statement_ids=[]`, **one** proposal, no generic fallback:
  - `icp_key`: `independent_neurosurgery_practices_us`
  - label: *"Independent U.S. neurosurgery practices with 2–15 neurosurgeons"*
  - rationale: *"Target independent neurosurgery practices in the United States, excluding
    hospital-employed neurosurgery departments. Qualified practices have 2–15 neurosurgeons, operate
    their own billing, and are physician-owned or private-equity-backed. Early traction is strongest
    in Texas, Florida, and Arizona. Priority expansion triggers are hiring a surgeon and opening a
    second location."*
  - justifications non-empty everywhere: 6 `justifying_statement_ids` at proposal level and on
    `firmographic`, `source_profile`, every rubric weight and every candidate signal class.
  - `healthcare_practice` pack, NPI-weighted rubric (55/25/20), US-geo discovery strategy.
- **Post-synthesis turn.** The old stale-lineage brick did not recur.
- **`/confirm-icp 1`** → `independent_neurosurgery_practices_us@1`.
- **Quit/resume from a cold process.** The server was killed and restarted; the resumed trial
  returned all statements, readiness decisions and the confirmed ICP, and a fresh recall turn
  correctly restated both the earlier correction and the confirmed ICP.
- **Durable state in the report bundle.** No duplicate writes at any point: zero repeated
  `(onboarding_input_id, route_kind, route_key, quote_start, quote_end)` tuples; all statement ids
  unique; **all** readiness decisions `created_by_actor='system'`; `failures.json` empty.

## Phase B — the 25+-turn extension (PASS)

49 turns on the Aura trial. Zero 422 (the old code 422'd around turn 18) and no context-budget error
in either server log.

**F1 — repeated identical messages each bind their own turn (PASS).** Two triplets of byte-identical
messages:

- `"confirm"` ×3 → three statements, three **distinct** `onboarding_input_id`s
  (`57b059f1…`, `6173eb5b…`, `f01bc091…`), identical `quote_sha256` `3f267c2ab4…` (correct — the
  bytes *are* identical), offsets `(0,7)` each.
- `"Note this for the record: the champion usually wants faster clinic throughput."` ×3 → three
  `project_state/champion_desired_outcome` statements, three **distinct** `onboarding_input_id`s
  (`a1edc23a…`, `70d61ec1…`, `3bfe3fdf…`).

No `NO_ROUTING_RECEIPT` death, no repair loop, no duplicate write. This is the HEAD commit's fix
(cache keyed on the turn, not the turn's bytes) confirmed live.

## Phase C — the breadth extension (PASS, on the second attempt)

1. **`trial-acceptance-c8-breadth`** (31 turns, 45 statements). All 26 short prose turns succeeded;
   the two long bulleted paste-shaped briefs blocked (finding 1). The model routed **all 45**
   statements as `unmapped`, so `total_effective` stayed 0 and the card stayed at ~1,543 B with
   `unmapped_count: 43` — correct by design (unmapped contributes a count, not card entries) but it
   does **not** reach the statement cap. Useful negative result: card breadth is driven by
   *effective* (`project_state`) statements, not raw statement volume.
2. **Phase C3 on the Aura trial** — 20 further campaign-scope turns drove effective statements past
   40. **The cap engaged exactly as specified, live:**

   | turn | card bytes | included | total_effective | omissions |
   |---|---|---|---|---|
   | 40 | 10,431 | 38 | 38 | `readiness_history` 29 |
   | 41 | 10,819 | 40 | 40 | `readiness_history` 30 |
   | 42 | 10,797 | **40** | 42 | **`statements_over_cap` 2** + `readiness_history` 31 |
   | 45 | 10,617 | **40** | 47 | **`statements_over_cap` 7** + `readiness_history` 34 |
   | 49 | 10,747 | **40** | 49 | **`statements_over_cap` 9** + `readiness_history` 36 |

   `included` pins at 40, `total_effective` keeps climbing, `statements_over_cap` tracks the
   difference exactly and carries a cursor, `selection.cursor` appears, and the card **plateaus**
   around 10.7 KB — max observed card across the whole run **10,819 bytes**, well under the
   24,000 B cap. Every turn kept succeeding. No `Stage0CardTooLarge`.

## L3 / card-size evidence

Card size is not logged, but it is durable — every turn persists a `project_card` artifact ref.
Queried from Postgres (`agent_artifact_ref` ⋈ `artifact` on `content_sha256`):

- Aura trial across 49 turns: **1,538 → 10,819 B**, then flat once the cap bound. 49 refs over **48
  distinct artifacts**.
- **Content-addressed dedup observed live, twice.** Refs 11/12 share sha `9c6b82e816f6…` (turn 11
  wrote nothing durable, so turn 12's card compiled byte-identical and the existing artifact was
  reused), and turns 48/49 likewise. AC-8/AC-9 behavior in the wild.
- Opening-context growth (`model_call_usage.prompt_tokens`, first round of each turn): **13,479 →
  ~25,800 tokens** across 49 turns — sublinear in the ledger, and the readiness ledger (36 rows by
  the end) never entered the prompt; it appears as one `readiness_history` omission with a cursor.
- Rounds per turn held at **3** (opening → tool call → final), 4 when a repair fired.

**AC-5 spot check on the real assembled context** (a `model_input` artifact, 71,202 B): `to_jsonb` 0
occurrences, `quote_sha256` 0 occurrences, `current_effective_statements` exactly 1 (one card, not
duplicated). `onboarding_input_id` appears twice — the L7 captured-turn envelope (§6b), the intended
surface. The card's `project` block carries `client_entity_id` (the §8 v2.2 fix).

## Readiness lineage (AC-2, both branches live)

- Cards 5, 8, 9: `verdict=ready`, `effective_verdict=ready`, with metrics; card 5's
  `decision_lineage` carries no `product_id`, cards 8/9 carry the confirmed one — lineage tracks.
- Card 10 onward (immediately after `/confirm-icp` changed the pinned lineage):
  `not_evaluated_for_current_lineage` with empty metrics, rather than a silently stale verdict.

The card carries exactly one `latest_by_gate` entry plus `ledger_length` — the readiness duplication
the slice set out to kill is gone.

## The four watch-points

1. **Repeated-message turns bind correctly** — PASS. 6 repeated turns, 6 distinct bindings, 0
   failures. See F1 above.
2. **F3 round economy** — **0 occurrences.** Across all 80 turns there is not one attempt at
   `start_recon`, `synthesize_icps` or `submit_onboarding_input`; the withheld-tool surface (§8 /
   AC-7) means the model never sees them. Adjacent: **1** `submit_ingestion@1` attempt refused with
   `IncompatibleRecipe` (installed but recipe-incompatible), burning one round, and **3**
   `c5_tool_not_allowed` refusals of the inspection tools (finding 3).
3. **`client_knowledge` cursor handed to the model** — **0 occurrences.** `client_knowledge_over_cap`
   never appeared in any card or in the assembled model context.
4. **Empty inspection page with `has_more: true`** — **not observable.** The inspection tools cannot
   be called at all in the trial (finding 3), so pagination was never exercised.

## Findings

1. **Engine-side quote-offset binding (§6a) misses on long/bulleted messages.** The dominant tool
   failure was `ValueError: interview quote offsets fall outside the captured answer` — **12**
   occurrences. The model authors offsets and the engine applies them to engine-loaded bytes, so any
   drift between the model's view of the message and the captured bytes fails closed. Five turns
   finalized `blocked` with honest, actionable text ("the captured-answer offsets were
   unavailable/refused on two attempts, so no project-state change was recorded… please resend").
   No 422, no crash, nothing fabricated — the fail-closed path is truthful and survivable, but it
   costs a turn and correlates with message length and bulleted structure. Worth a skill/description
   round or a wider offset tolerance before this surface meets real users.
2. **Claim-route entailment strictness persists** (carried from the 2026-08-01 pre-C8 run, finding
   1): **8** `claim value is not textually entailed by the exact interview quote` failures. The
   Client KB stayed at 0 claims across both trials; every fact landed as interview evidence instead.
   Unchanged by C8; the deliberate decision noted in the prior run is still open.
3. **AC-3 gap — the two §7 inspection tools are advertised but not callable.** Asked directly to
   retrieve statement and readiness history, the agent's plans were rejected:
   `plan.steps[0].tool: c5_tool_not_allowed: inspect_statement_history@1 is absent from the active
   C5 slot` (and the same for `inspect_readiness_history@1`; 3 refusals total). The agent's own
   words: *"absent from this execution's active C5 slot, despite appearing in the broader capability
   listing."* The tools are registered on the role and are deliberately **not** in the trial's
   `withheld_tools`, so this is a C5-slot/recipe wiring gap, not a surface-policy decision.
   Consequences: AC-3 ("full statement/readiness history retrievable via the two bounded tools") does
   not hold live; and the card's `readiness_history` and `statements_over_cap` cursors are handed to
   the model with **nothing installed that can resolve them** — the same hazard watch-point 3 was
   guarding against, arriving through a different door. AC-7's clause "a profile advertising an
   omission-resolving tool it doesn't install is a failing contract test" is the rule that should
   have caught this. Good behavior under the gap: both turns finalized `blocked` and the agent
   refused to invent history. **Fix the C5 slot before closing §12.**
4. Minor: **2** `agent.finalize_refused` (`NO_ROUTING_RECEIPT` guard) fired across 80 turns; both
   were repaired within the turn and neither killed a turn.

## Evidence locations

- Server logs: `/tmp/c8acc/server-phaseA-part1.log` (turns 1–9), `/tmp/c8acc/server2.log`
  (post-restart, everything after).
- Turn transcript (every request/response, JSONL): `/tmp/c8acc/transcript.jsonl`; per-phase stdout
  `/tmp/c8acc/phaseB.out`, `phaseC.out`, `phaseC2.out`, `phaseC3.out`.
- Report bundles: `.context/sumble-trials/trial-acceptance-c8-aura/` (`report.json`,
  `trial-report.json`, `session.json`, `icp-proposals.json`, `failures.json` — empty) and
  `.context/sumble-trials/trial-acceptance-c8-breadth/`.
- Card artifact bodies: `.artifacts/<workspace_id>/<content_sha256>`.
- Card sizes per turn:
  `SELECT r.created_at, r.artifact_sha256, a.size_bytes FROM agent_artifact_ref r LEFT JOIN artifact a
   ON a.content_sha256 = r.artifact_sha256 AND a.workspace_id = r.workspace_id
   WHERE r.workspace_id = :ws AND r.ref_role = 'project_card' ORDER BY r.created_at;`

The trial server was stopped at the end of the run.
