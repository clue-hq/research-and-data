# Close-out: the seven-fix night (2026-08-20, ~03:00–07:30 IST)

Session arc: founder's retry-after-remediation design question → strict review of the background
session's `c7d6da82` → seven live defects found and fixed in one night, each red-proven, each
verified in production within minutes of landing. Companion notes:
`2026-08-20-projection-replay-loop-and-fold-visibility.md` (fixes 1–2 + amendments),
`2026-08-20-account-gap-window-reacquisition.md` (fixes 3–4),
`2026-08-20-channel2-raw-escape-foreign-read-refs.md` (fix 7),
`2026-08-20-grok-account-run-results.md` (the original forensics).

## The seven commits (local only, never pushed)

| commit | fix | live proof |
|---|---|---|
| `5dd1b3f8` | fold releases pending/terminal whichever job filed it (4 readers; spend stays job-scoped) | eea48931 assess stopped refusing, 05:20 |
| `15f27702` | never-admitted stored projection → serve fresh (first-write-wins = admitted history only) | eea48931 settled 28s after resume |
| `2030de45` | same-window field re-buy → governed refusal, not raw P0001 escape | 3cc0a4f2 replay landed as refusal, 06:18 |
| `b60824d4` | the already-acquired refusal names the owning op's exact field set (the one legal move); exact-set exemption NOT added — the starter rejoin runs before the pre-check (pinned by test) | Grok asked the exact set 7s after seeing it, 06:37/07:16 |
| `6d72859a` | settlement-fold replay guard compares settled cost only, never filer identity | hiring_velocity replay clean, 06:36/07:16 |
| `2540ffcc` | replay serves what the FIRST ADMITTED RESULT recorded (reconstructed from its digest-pinned artifact, span-hash-reconciled) — "a result exists" ≠ "the stored row was admitted" | hq_location exact-set replay admitted, 07:15/07:16 |
| `cd15398d` | raw-escape audit: foreign result/evidence refs, evidence paging, 7 contact tools' validation, 2 unwrapped channel tools, contact guard — model-input species refuse recoverably; money/truth re-typed to stay suspending | the three killer reads replayed as refusals, 07:15:45 |

## Final board

- `eea48931` (v5): terminal / needs_review, 05:20 — 11-ish fields, honest gaps, committee 402-era gap.
- `3cc0a4f2` (v6): terminal / **completed**, 07:15:17 — coverage closed clean.
- `5b8898e3` (v7, committee cap 7): terminal / needs_review, 07:17:02 — the committee attempt at
  06:22:52 was CORRECTLY COMPOSED (evidence_refs self-repair in 6s), reserved 72 units, and the
  precursor `sumble_teams` call TIMED OUT (~10s = `DEFAULT_TIMEOUT_S`, no httpx line = never
  completed) → `spend_outcome_unknown` quarantine → terminal attempt → honest empty committee.
  NOT a defect: the ambiguous-post-dispatch taxonomy working as ratified. Teams answered normally
  at 23:00 and 01:30, so the 10s ceiling is not systematically tight — transient stall.
- `16e846d6`: still relaunch-only (Grok encrypted-reasoning checkpoint).
- **Committee members still zero.** The one remaining move: a fresh v8 relaunch (cap 7, ~72
  units, fresh per-job committee operation) + founder approval. Offered; founder undecided at
  close.

## Open items, deliberately parked

1. **`EntityResearchFinalizationRejected` repair round** — model-authored but raised at
   `entity_research_runtime.py:1252` AFTER the graph returns, outside every tool-rendering path.
   Needs a repair-round mechanism, not a species change. (Audit agent's flag.)
2. **Committee ADMITTED-path test fixture** — `2540ffcc`'s reconstruction is account-covered in
   both worlds; the committee branch shares it but has no dedicated admitted fixture.
3. **Retry-after-remediation design** — now FOUR instances in one night (402 fold after plan
   upgrade; defective draft after code fix; window-acquired after conflict; unknown-spend
   quarantine after timeout). Ratified direction stands: minimal governed fresh-attempt
   (relaunch/epoch), never blanket retries. The v8 relaunch IS the pattern in practice.
4. **Tunis fleet worker is DOWN** — my blanket `pkill -f clue_api.fleet_main` (~06:1x) killed it
   alongside missoula's. No launch context found in tunis's `.context/`; left for the founder or
   its own session to restart. Queued work there just waits (crash-safe by design).
5. **56 pre-existing full-gate failures** recorded in the projection-replay note — byte-identical
   at pre-fix HEAD, not tonight's lanes. Triage against the default dev DB someday.
6. Sumble credits: founder reported 391 before the v7 attempt; the quarantined teams call recorded
   0 charged — verify on the Sumble dashboard before trusting the number.

## Process notes that held up

- Every fix: red-proof re-run independently by the orchestrator (revert prod file, run test,
  restore) except where imports made it impossible (window fix — accepted agent's captured red +
  live proof). Fleet rolls only between drives, targeted PID kills after the pkill mistake.
- The night's two ratified principles, now encoded in seven places: **first-write-wins protects
  admitted history only** (and "admitted" means the result's own record, not a draft row), and
  **model-input failures refuse recoverably; money/truth failures suspend** — the engine
  disposes, it never quizzes, and it never dies on a model's typo.

## Addendum: v8 — the first complete committee execution (2026-08-20 ~11:30 IST)

Directive v8 (cap 7) confirmed 11:29:26 → job `4e1bc4fd` → committee operation `8500325f`
succeeded end to end: teams 16 units, people 56 units (303 credits remain), operation `ready`,
result `f482643e` admitted. **Outcome: 7 candidates → 2 excluded, 5 ambiguous, 0 admitted;
`confirmed_empty_discovery=true`; job terminal/needs_review with 17/21 fields completed.** The
`same_office_strict` gate could not evidence Fort Myers HQ placement for any candidate from
profile values — fail-closed-to-review, exactly the Doc-D-era posture (office assignment is never
guessed). TWO OPEN REVIEW ITEMS on coverage `9b14fee8…`: `committee_office_candidates_ambiguous`
(the designed human path — founder confirms which of the 5 are real committee members) and
`account_fields_unresolved`.

Paths to actual members: (a) resolve the ambiguous-candidates review item (human confirmation —
check what the review surface renders); (b) relaunch with a bigger cap for more explicit-evidence
candidates (~8.5 units each, 303 remaining); (c) a looser match policy DOES NOT EXIST —
`match_policy: Literal["same_office_strict"]` is the only value; loosening is a product/code
decision, not a knob.

## Founder ruling 2026-08-20 (~11:50 IST): same-office gate retired for now

"Remove the same-office gate for now — retire that policy." Implementation direction (this
session): reversible policy flip, not deletion — new `match_policy: "company_wide"` becomes the
DEFAULT (no office-placement veto; candidates never excluded/ambiguous on office geography);
`same_office_strict` stays in the schema, byte-identical when explicitly selected. Identity and
relevance gates (current-employer, target functions) untouched. Historical strict scopes replay
untouched; the new policy affects new operations only. Fix lane dispatched; after it lands:
review → commit → fleet roll → v9 relaunch (cap 7) → the five-ambiguous class admits.

## FINIS: the first committee member (v9, 2026-08-20 ~11:57 IST)

After the gate retirement (`addc8364`), directive v9 (cap 7) → job `cd6a779e` → committee op
succeeded (72 units; 231 credits remain) → **contact `fa1afe6b` admitted to coverage: Lenny
Brunson, Divisional CIO at Millennium Physician Group, CXO / Information Technology, Fort Myers
FL, persona technical_evaluator** — identity-resolved, persona-tagged, role-claim with rationale,
organization-relationship provider-returned, full provenance. The platform's third required
output exists for the first time. Job terminal/needs_review (1 of 7 candidates admitted; the
rest fell on function gates — a wider cap fills more seats). Required-output pillar 3: live.

## Founder rulings 2026-08-20 (~12:3x IST): committee formation is agent-judged, provider-grounded

Three explicit rulings, overriding orchestrator counsel (counsel given and recorded; founder
decided; pilot posture, revisit later versions):

1. **Truth floor = provider-returned, nothing more.** A committee candidate returned by Sumble
   (people OR teams rows) or Exa is admissible ground, period — founders have vetted these
   providers. No additional hard mechanical blockers on provider-returned values "for now at
   least; we will improvise on truth gates in future, but not now." Consequence: the admission
   ladder's people-vs-teams source-key discrimination dies (teams rows are provider data too);
   the function string-match dies; the agent proposes members from the grounded pool with
   role + rationale. Provenance/evidence-span STAMPING stays (passive bookkeeping, DSAR spine,
   never a blocker).
2. **Spend caps exist but do not block, for now.** Provider credit-cap / unbounded-charge guards
   flip to record-only in the pilot posture (log + exact accounting, never refuse). "It's like
   making the same mistake again and again" — the 15-day lesson: gates before the loop.
3. **Teach via prompt, including truth and money discipline.** Terra was a weaker model; Grok-4.6
   and future models are smarter. No over-engineering; prompt emphasis over mechanical checks;
   "if it won't work out we will improve it in a later version."

Also ruled earlier in the thread: role inference moves INTO the per-account agent (the roles.py
M8.3 leaf call retires from this path — same relocation pattern as the [C1×C6] coverage-evaluator
backlog item); the deepagent must co-define the four committee personas (champion / economic
buyer / technical evaluator / blocker) WITH THE USER before account research launches — strong
steering emphasis, ratified plan carries personas/functions/levels, account agents copy and never
invent.
