# ARV2 R0 — Seam freeze: the launch contract and the ICP artifact

**Status: Seam 1 RATIFIED 2026-09-07 (both columns signed; boxes 1a and 1b recorded inline). Seam 2: boxes 2b (automatic registration at confirmation — ratified in `ARV2-ONBOARDING-PLAN.md` §6.1) and 2c (add `user` to the enum — master plan D8, shipped by D1) are recorded; box 2a is master plan D9 and remains the one open founder call, so Seam 2's row stays unsigned until D9 is ruled.** Signing note: one person now executes both founders' lanes, so both columns carry the same signature on the same day. Parent plan:
`docs/specs/ARV2-R0-foundations-plan.md` (ratified 2026-09-01). Purpose: freeze the two seams
that let the two workstreams run fully parallel — Aryan (tech founder) on the platform
deepagent / onboarding / ICP / project context, Shashank (co-founder) on the ARV2 research lane +
accounts frontend integration. (Roles corrected 2026-09-04; earlier text had the names swapped.) Once these two pages are signed, neither workstream needs to consult the other
until integration.

Everything here is a *strawman with decision boxes* — the session's job is to initial or amend
each box. Nothing below is binding until both founders sign the header.

---

## Seam 1 — the launch contract (Head-of-ABM → account research)

### 1.1 The forward edge: what launch carries

One call, from the Head-of-ABM deepagent's tool surface into the research lane:

```
launch_account_research(
    workspace_id,        # tenancy scope — fail-closed, as everywhere
    project_id,          # the project this research run belongs to
    account_ids[],       # the human-approved cohort (account_entity ids, never names)
    icp_artifact_ref,    # content-addressed ref to the FROZEN ICP artifact (Seam 2)
    product_selection_version,  # the project's product-set version at launch (D14/D15; added 2026-09-07)
    directive_text       # free text PLUS the structured block {effort, committee_cap} (box 1a)
)
```

*Amendment 2026-09-07 (signing session):* `product_selection_version` joins the signature so a run
pins the product **set** it was launched against (master plan §5.1, rulings P1/P2 in
`ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.4); a later set version never touches a running or finished
run. The onboarding plan's Head-of-ABM integration (§8) carries the same two pins on launch.

Rules:

1. **A human approves the cohort and the launch.** The existing human-authority pattern stays:
   the agent may propose and open the confirmation gate; only a human confirms. (This is Gate 2
   of the guardrail charter — product, not friction.)
2. **Research never reads the conversation.** Its entire client-side context is the ICP artifact
   plus the compiled field catalog plus the account entities. If something matters to research,
   it belongs in the ICP artifact or the directive text — not in chat history.
3. **The ICP ref is pinned.** The run records the exact artifact ref it was launched with;
   a later ICP edit never silently changes a running or past run's meaning.
4. **Job identity is sha-pinned** (existing mechanism): each job records the ARV2 agent profile
   ref + sha; a profile change relaunches, never resumes.

> **DECISION BOX 1a** — is `directive_text` free-form only, or does it carry a small structured
> block (e.g. depth: full|reduced|cheap-pass, committee size cap)? Strawman: free-form only for
> v1; depth knobs arrive with tiering.
> **Amended recommendation (2026-09-03, `ARV2-plan-delta-2026-09-03.md` §4):** carry a small
> structured block — `effort: full|reduced|cheap-pass` and `committee_cap: int` — beside the
> free text. The runs priced the rungs ($0.155 / $0.086 / $0.015 per account) and an explicit
> ladder lets the human choose spend without a mechanical gate.
> **RULED 2026-09-07 (master plan D6): yes — the structured block ships in v1.** Signed both columns.
>
> **DECISION BOX 1b** — does launch accept accounts *not yet* in the store (domains to create),
> or must discovery/import have landed them as `account_entity` rows first? Strawman: entities
> must exist first; discovery/import owns entity creation (identity resolution stays in one
> place).
> **RULED 2026-09-07 (master plan D7): entities must exist first.** Signed both columns. The
> answer-key loader seeds the R2 acceptance accounts (Zafran, Probook) as `account_entity` rows for
> exactly this reason.

### 1.2 The reverse edge: what research exposes back

The project-context compiler (Aryan's side) reads only these, all existing surfaces:

| Read | Backing |
|---|---|
| Accounts in this project (count + list) | run-lineage-attributed reads (as the accounts list already does) |
| Per-account research status | research job state (the honest 5-state enum: not_started / in_progress / needs_review / completed / suspended) |
| Run/job progress + finalization | `entity_research_run` / `entity_research_job` rows + finalization receipts |
| The claims themselves | the claim store (the one shared substrate — never a side channel) |

Rule: **the claim store is the only data seam.** Research returns claim references, never blobs;
project context and the frontend read claims and job state, never research internals.

### 1.3 Failure semantics at the seam (the failure-species law, restated for the contract)

- A launch that cannot compose (lane flag off, missing key) refuses with a **typed, actionable
  message** — never a crash, never a silent no-op.
- Zero yield on an account is an **honest terminal outcome** (finalization with empty coverage),
  never a job death.
- Nothing on the research side can veto or reorder the launch: no coverage floors, no quality
  ladders, no secondary judges. The one write-side gate is the claim write-shape check.

---

## Seam 2 — the ICP artifact

### 2.1 What it is

One markdown document per confirmed ICP, agent-authored during onboarding, human-confirmed in
the interview, then **frozen** (a new confirmation mints a new version; nothing edits in place).
It is simultaneously:

- the human-readable record of "who we sell to" (lives under the project and under the brand
  context, marked with which projects use it),
- the research charter the ARV2 account agent reads verbatim,
- the source the field-catalog compiler reads to register client-qualifier fields.

### 2.2 Format (strawman)

```markdown
---
kind: icp-definition
icp_key: <slug>              # stable identity across versions
version: 1                   # bumped on each human re-confirmation
brand_id: <id>
confirmed_by: <human>        # the interview confirmation
confirmed_at: <iso8601>
hard_gates:                  # pass/fail — an account failing any gate is out
  - key: stage
    rule: "Series A or A-extension raised within 24 months"
  - key: geography
    rule: "US-headquartered"
  - key: hiring
    rule: "actively hiring now, GTM roles especially"
  - key: intent
    rule: "at least one citable, dated buying-intent signal"
exclusions:
  - "direct competitors (sells ABM orchestration / AI GTM agents)"
  - ">1,000 employees"
persona_map:                 # committee shape for this ICP
  economic_buyer: "CEO/founder or CRO"
  champion: "growth/marketing/GTM lead"
  user: "sales lead / the person who operates the tool daily"
  technical_evaluator: "technical co-founder / CTO"
qualifier_fields:            # compiled into the field catalog (registered, described)
  - field_key: vertical_saas.gtm_stack
    description: "CRM/outbound/ABM tools present AND explicitly absent"
  - field_key: account.hiring.gtm_open_roles
    description: "open GTM roles: title, dept, published, days-open, salary band, URL"
---

# ICP — <name>

<the full human-readable definition: who they are, why they buy, what signals matter,
 in priority order — the prose the research agent actually reads>

## Sections the interview should fill (amended 2026-09-03)
- TAM / list-math estimate and the widen | tier | shrink choice the client made
- Disqualifiers and red flags (incl. "direct competitor" wording)
- Closed-won / closed-lost patterns from the client's last deals, in their own words
- The client's own phrasing of who they sell to (verbatim, quoted)
- The qualification-floor verdict: is this motion ABM-shaped, and if not, what to do first
```

Rules:

1. **The description IS the research instruction.** Every qualifier field ships with a
   researcher-facing description; a vague description produces vague claims (sources-and-
   variables doc §2, already ratified in spirit).
2. **Hard gates are worded as pass/fail with a citable test** — the smoke test proved the gates
   do the work (stage + hiring + intent produced 4 of 5 picks).
3. **The persona map is data**, so committee mapping is consistent across accounts and the
   frontend's persona chips render without interpretation.
4. Storage: the durable artifact store (same machinery as every platform artifact), surfaced
   into the deepagent's workspace via the existing project-context materialization path — no new
   transport.

> **DECISION BOX 2a** — the G8 ruling (smoke-test gap register): does "Series A and above"
> get an equivalence clause ("or demonstrably funded/scaled equivalently — e.g. self-funded,
> 150+ people, open GTM reqs")? Needs an explicit yes/no; it changed a real verdict (Oscilar).
> **OPEN — this is master plan D9.** Until ruled, the stand-in ICP artifact
> (`.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md`) states the strict reading: a
> self-funded operator fails the stage gate.
>
> **DECISION BOX 2b** — do qualifier fields register at ICP confirmation time (automatic), or
> does field registration stay a separate reviewed step in Settings? Strawman: automatic at
> confirmation — the confirmation *is* the review.
> **RECORDED 2026-09-07: automatic at confirmation** (`ARV2-ONBOARDING-PLAN.md` §6.1: approval
> "registers the `qualifier_fields`"). The D1 lenient claim writer already auto-registers an
> unknown key as a proposed field, so the research lane tolerates either timing.
>
> **DECISION BOX 2c** — the `Persona` enum has four values today and the persona map above uses
> five (adds `user`). Adding `USER` to the enum is a contract-delta on frozen core + a migration,
> proposed twice by the PoC runs (v2 §7.4, v3 §7.4). Ratify now or map `user → champion` for v1?
> **Amended recommendation (2026-09-03):** the ICP `persona_map` is THE single persona vocabulary
> — the research lane's committee claims, the Head-of-ABM skills, and the frontend's free-text
> persona chips (the new `chat-shell` fixtures carry ten ad-hoc values) all map onto it. Add
> `user` to the enum now; the PoC runs hit its absence three times.
> **RULED 2026-09-07 (master plan D8): `user` added to the enum** — shipped by the D1 migration
> (`65fb2128c904`), and the stand-in ICP's `persona_map` speaks the five-value vocabulary.

---

## Sign-off

| Decision | Shashank | Aryan |
|---|---|---|
| Seam 1 contract (1.1–1.3, incl. the 2026-09-07 `product_selection_version` amendment) + boxes 1a, 1b | ✓ (2026-09-07) | ✓ (2026-09-07) |
| Seam 2 format (2.1–2.2) + boxes 2a, 2b, 2c | ☐ — 2b, 2c recorded; 2a (= D9) open | ☐ — 2b, 2c recorded; 2a (= D9) open |

Seam 1 is frozen as of 2026-09-07: changes require a new session and a version note here. Seam 2
becomes RATIFIED the day D9 is ruled — record the ruling inline at box 2a, tick both cells, and
update the Status line.
