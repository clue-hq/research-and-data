# 11 — Deep behavioral audit of the live Head of ABM (profile v57), with the strings attached

**Date:** 2026-09-19 · **Audited against:** `origin/research-streaming` at `21e3ef1e9` (2026-09-19), which contains `integration/design-improvement` and is the newest branch carrying the Head of ABM catalog. Live pin: `PROJECT_CONVERSATION_AGENT_PROFILE_ID = head-of-abm@v57`, prompt v10, stage0-interview v33, recipe0-stage0 v28, manual v4, model `x-ai/grok-4.6`.

**The complaint this audit answers:** the agent asks questions instead of acting or planning, and it asks one kind of question ("what did your last three closed-won deals look like"). Every claim below is traced to the exact string the model reads, or to a recorded live turn. Nothing here is inferred from memory of earlier versions.

---

## 0. Verdict

The agent behaves exactly as its strings instruct. It is built, string by string, as a **recording clerk with a gate remote**: read the brand files, ask six founding questions one per turn in a fixed order, record each answer as a quoted statement, then open two human gates, and only after all of that may it write a plan, draft a profile, or launch anything. Planning is not merely un-taught; it is **explicitly prohibited** before the interview completes ("Write it once, not before, the founding questions ... are answered"; "Never write a plan on the first turn of a project"). Initiative is prohibited by five separate "never start anything the human has not asked for" rules. The only knowledge it can plan with is the brand's own onboarding documents; it holds roughly 3,100 lines of operating manual about the platform and about twelve lines about ABM. Its turn contract rewards ending on a question. And its success is currently defined as receipts: statements routed, gates opened, jobs queued, nothing fabricated.

So the monotony is not a model quirk. The six questions in skill v33 §2 are the entire strategic content the agent has, and "last three closed-won deals" is question two of six. An agent with one script and no repertoire replays the script.

**The bottleneck chain, from the user's most likely first message** (the Home screen suggests "Find and research new accounts we can target before this quarter ends"):

```
"Find accounts"  →  launch_arv2_discovery needs a pinned ICP + a confirmed product set
                 →  the ICP pin needs open_icp_confirmation_gate  (turn N)
                 →  which the skill orders after the product-set gate  (turn N-1)
                 →  which comes after the user picks an ICP  (turn N-2, "your view first")
                 →  which the skill orders after §2's six questions, one per turn, each recorded  (turns 1..6)
                 →  and the plan may only be written after all of the above.
Expected: 8 to 10 turns of interview and gates before the first account is even searched for,
and zero proposals, plays, or numbers along the way, because nothing in the strings asks for any.
```

---

## 1. What the agent is today, exactly

| Layer | What the model actually holds | Size / bound |
|---|---|---|
| L1 identity | prompt v10 (≈95 lines) **plus the generated capability map** (every pinned resource with sha, every disclosed skill with summary and path, available and unavailable tools, the "explicitly unavailable" block, workspace policy) | ≈23.7 KB resolved; L1 budget 40,000 bytes |
| L2 workspace/product | brand card, confirmed product card | 12,000 |
| L3 project | `ProjectConversationCard@2`, the `brand_knowledge_index` card (path, status, one-line summary per document), the project's pinned ICP | 48,000 |
| L4 memory | **empty**: `CLUE_MEMORY_ENABLED=false`; the profile still says `scoped-advisory-v1` | 16,000 |
| L5 focus | current focus refs | 8,000 |
| L6 conversation | thread history, **evicted oldest-first under a byte budget with no marker** | 96,000 |
| L7 turn | the message and attached account/contact refs | 32,000 |
| Mounted read-only | `brand/knowledge/{company,product,proof,audience,design}`, `brand/index.json`; `project/status.md`, `project/decisions.md`, `project/artifacts/index.json`, `project/index.json` | per version |
| Writable | `scratch/` (persists across the thread), `project/` (any markdown = versioned document), `work/`, `outputs/` | 20 MiB, 400 files |
| Skills disclosed | stage0-interview v33 (229 lines), icp-authoring v2 (38), persona-authoring v2 (77), plan-authoring v2 (42), **fifteen `manual-*` chapters v4 (≈3,100 lines; manual-tools alone is 1,210)** | load on demand |
| Governed tools | 15: `launch_arv2_account_research`, `launch_arv2_discovery`, `launch_arv2_person_research`, `open_icp_confirmation_gate@2`, `open_product_set_selection_gate`, `open_directive_confirmation_gate` (dead chain), `draft_account_research_directive` (dead chain), `read_project_accounts`, `read_account_research@2`, `read_claims`, `read_discovery_run@2`, `read_artifact`, `read_arv2_account_research_run`, `get_research_view` (flag-off), `inspect_statement_history`, `record_interview_answer`, `submit_ingestion` (granted but always `IncompatibleRecipe` on this surface), `propose_field`, `propose_source`, `open_design_leg@4` | |
| Framework tools | `ls, read_file, write_file, edit_file, glob, grep, write_todos, finalize_turn` | |
| Withheld on this surface | `delegate_specialist` and all three delegation roles; any web/fetch tool; shell; network | enforced |
| Turn caps | 100 model rounds, 204 supersteps, 1,800 s wall clock, 8,192 output tokens per call, 3 governed refusals per turn (parallel calls each count), 2 finalize repairs | enforced |
| Model | `x-ai/grok-4.6`, temperature 0.1; **its reasoning is invisible in the UI on this route** (gateway adapter drops third-party reasoning fields, note 2026-09-12) | |

Two structural facts that shape everything below: **(a)** the only prose that reaches the human is `finalize_turn.user_message`; ordinary assistant text is discarded; **(b)** the human answers in a brand-new turn, so every turn is a closed episode that must end in one of four statuses, and `awaiting_input` "when you need a human answer or confirmation" is the natural close for an agent that may not initiate.

---

## 2. The string ledger: every instruction that produces "ask, don't act"

Quotes are verbatim from the live catalog. Effect is stated as observed or as the literal reading a low-temperature model gives it.

### 2A. The interview script (why it asks, and why it asks the same thing)

| # | Source | String (verbatim) | Effect |
|---|---|---|---|
| A1 | prompt v10 ¶5 | "Ask the questions any ABM program needs answered first, **one at a time**. When the conversation reaches the profile, give your own view first and ask for theirs." | The prompt's only Stage-0 instruction is to ask. "Give your own view" is scoped to the profile, not to the program. |
| A2 | stage0-interview v33 §2 | "Every ABM program stands on a few answers, and you get them **before you talk about profiles**. Ask one question at a time, **in this order**, and skip a question only when the files or the user already answered it." | A fixed six-item script with an ordering rule. Skipping requires the answer to already exist; the agent cannot skip because a better move exists. |
| A3 | v33 §2 items 1–6 | "1. The outcome ... 2. **The last three closed-won deals** ... 3. The list math ... 4. Channels already tried ... 5. Follow-up ownership ... 6. Failure at day ninety." | The complete question repertoire. Six questions, always these six, always this order. "Last three closed-won deals" is item 2, so it is the second thing every project hears. |
| A4 | v33 §2 closing | "Record every answer as you receive it (section 6). Do not batch the questions into a form" | One question per turn, then a recording call, then finalize. Six turns minimum before the profile step. |
| A5 | v33 §6 | "Route every substantive turn before you finish it ... one statement per material fact ... **Copy the span. Do not describe it.** `quote` is the human's own words, copied character for character" | Each turn carries a mandatory extraction task with an exact-substring constraint and a refusal loop. The turn's center of gravity is capture, not counsel. |
| A6 | manual-documents-decisions v4, route keys | "`outcome` · `closed_won_pattern` · `list_math` · `channels_tried` · `follow_up_owner` · `day_ninety` · `product_focus` · `icp_scope` · `discovery_target` · `persona_seats` · `preference.<topic>` · `other`" | The recording vocabulary **is** the six questions. The system's notion of a "material fact" is defined by the script; anything the user says outside it is `other`. |
| A7 | v33 §3 | "When the conversation reaches the profile, whether after the questions above or earlier because the user asked, lead with your own recommendation." | The one place the agent is told to lead is gated on "reaching the profile", which by §2 is after the questions. |
| A8 | v20 §2 (the previous version, for contrast) | "Ask from gaps, never from a questionnaire ... Ask one compact question when possible. A question is material only if its answer can change [a listed platform state]" | The interrogation posture predates v22. v22 to v33 replaced "gap-driven" with "scripted", which fixed vagueness and introduced monotony. |

### 2B. The planning prohibitions (why it never plans)

| # | Source | String | Effect |
|---|---|---|---|
| B1 | plan-authoring v2 | "Write it once, **not before**, the founding questions from the Stage-0 skill are answered, the ICP is confirmed and pinned ... and the product set is confirmed. **Never write a plan on the first turn of a project**, and never one the human has not discussed with you." | Planning is forbidden until after six questions and two gates. A "provisional plan" does not exist as a concept. |
| B2 | icp-authoring v2 | "Do not write a profile before the founding questions are answered, and never one the human did not ask for." | Same gate on the ICP draft. |
| B3 | persona-authoring v2 | "Write the personas only when the human asks for them, on or after the turn the ICP was confirmed." | Personas are never volunteered. |
| B4 | v33 §10 | "You cannot ... **start anything the human has not asked for on the current turn.** You may write project documents under `project/` through the three document skills; confirmation stays the human's." | Stated as a *cannot*, in the same list as truly enforced cannots. The model reads it as a hard rule. |
| B5 | manual-gates-authority v4 | "do not write a profile, or a plan, before the human has discussed one with you" (listed under "Prompt rules that nothing enforces") | Repeated a third time. |
| B6 | manual-turn v4 | "A launch, a queue acknowledgement, a provider wait, or a normal model stop is never completed research" | Correct, but paired with nothing that says what *is* a good completed turn for a strategist. |

### 2C. The initiative prohibitions (why it waits)

| # | Source | String | Effect |
|---|---|---|---|
| C1 | manual-gates-authority v4 | "launch only the accounts or people the human's **current** message names · never widen the set · never launch from an earlier message · **never start anything the human has not asked for on this turn**" (each "asked of you") | Four nevers about spend, correct in intent, but the fourth is broader than spend and the model generalizes it. |
| C2 | v33 §7 | "Launch only when the human's **current** message names the accounts ... Never widen the set, never launch from an earlier message, and never launch before both gates are answered." | Correct spend discipline; it also means a plan the agent proposed last turn cannot be executed this turn without the user re-stating it. |
| C3 | prompt v10 authority ¶ | "You cannot confirm the project's product set or ICP, confirm a research directive, declare evidence sufficient, promote a claim, approve a proposal, or cross a budget/checkpoint gate." | Seven cannots, zero cans. (File 06, principle 1: the Opus-5 style default stance opens with what the agent *does*.) |
| C4 | capability map (generated) | "Explicitly unavailable runtime capabilities: framework task/subagent: unavailable ... delegate_specialist: unavailable on this surface ... execute/shell/process: unavailable ... arbitrary network access: unavailable ... human confirmation, override, budget, and checkpoint authority: unavailable" | A block of unavailability rendered into L1 on every turn. Accurate, and it sets the tone of the whole identity layer. |
| C5 | manual-gates-authority v4 | "Twelve tools are human only on every model surface, permanently" | Correct. Listed before anything the agent may do. |
| C6 | manual-turn v4 | "You cannot see cost, tokens, latency, logs, or host paths ... Never claim or estimate spend, duration or system health" | The agent cannot even put a rough cost on a proposal, which is half of what a plan is. |

### 2D. The turn contract (why a question is the cheapest honest ending)

| # | Source | String | Effect |
|---|---|---|---|
| D1 | prompt v10 final ¶ | "Use `awaiting_input` when a useful human answer or confirmation is needed, `blocked` when an external gate prevents progress, and `completed` only when the requested turn outcome is durably complete." | For a turn where the agent may not initiate and may not plan, "a useful human answer is needed" is always true, so `awaiting_input` with a question is always a valid close. |
| D2 | manual-turn v4 | "`awaiting_input` ... must say what you are waiting for: a next action, an open gate ref, or a `user_message`" | `next_actions` is defined as **what you are waiting for**, not what you will do. |
| D3 | manual-turn v4 | "You must call a tool every round; you cannot think out loud for a round and stop" | Combined with 3 refusals per turn and grok's long reasoning, the safest short turn is: read a file, ask, record, finalize. |
| D4 | v33 §6 | "Route every material statement before you finalize; nothing checks this for you on this surface." | Every turn ends with a capture chore; the user's answer is the raw material, so the agent's incentive is to elicit more answers. |

### 2E. The knowledge it can plan with (why its proposals would be thin even if it made them)

| Knowledge class | Present? | Where | Approx. size |
|---|---|---|---|
| The brand (company overview, product catalog + per-product files, customer reviews, 2–3 ICP proposals, persona documents) | yes | `brand/knowledge/` | tens of KB, cited by path |
| The project (status, decisions, plan, its documents, artifact index) | yes | `project/` | small |
| The platform (tools, refusals, fields, claims, gates, screens, errors, limits, glossary) | yes, exhaustively | 15 manual chapters | ≈3,100 lines |
| **What good ABM looks like** (tier economics, program shapes, play library, benchmarks, failure modes, agency intake patterns, measurement) | **no** | nowhere | **≈12 lines**: the six questions and the one-sentence qualification floor in v33 §2 |
| Copy craft / voice | two sentences | prompt v10 | "no em dashes, and no specific fact that does not trace..." |
| Campaign ideation / signal→play mapping | **no** | nowhere | 0 |
| Exemplars (good emails, letters, plans, ICPs from real programs) | **no** | nowhere | 0 |

The ratio is the finding: the agent is a near-expert on *how to operate Clue* and knows nothing about *ABM*. The 02/03/04 research briefs in this folder (5,300 lines, 280+ sources) are on disk in the repo and mounted nowhere.

### 2F. The tool surface, classified by what it can produce in-turn

| Class | Tools | Human precondition | Produces in-turn |
|---|---|---|---|
| Spend launches | 3 (`launch_arv2_*`) | pinned ICP + confirmed product set + current-turn ask | a queued run, never a result |
| Gates | 2 live (`product_set`, `icp_confirmation@2`) + 1 dead (`directive`) | none to open; the answer is a new turn | a card |
| Reads | 6 (accounts, research@2, claims, discovery@2, artifact, run) | none | rows (paged, 12 KiB) |
| Record / propose | `record_interview_answer`, `propose_field`, `propose_source`, `inspect_statement_history` | none | receipts |
| Hand-off | `open_design_leg@4` | none | the thread leaves the agent |
| Files | `write_file`/`edit_file` under `project/` | **skill-gated** (B1–B3) | a versioned document |
| Dead / mis-granted | `draft_account_research_directive`, `open_directive_confirmation_gate`, `get_research_view`, `submit_ingestion` | | refusals (F1 below: `submit_ingestion` costs a repair round whenever the model notices the captured input) |

Only two things can produce visible value inside a turn without a human precondition: a **read** (which yields facts about existing accounts) and a **document write** (which the skills forbid until the interview is over). Everything else is a card, a receipt, or a queue. There is no tool that estimates list size, previews discovery, scans existing accounts for signals, prices a program, or drafts a play. The agent has nothing to propose *with*.

### 2G. What the user is nudged to type versus what the agent can do on turn one

Home suggestions (fixture, `project-workspace.fixture.ts`): **"Find and research new accounts we can target before this quarter ends based on conversions"**, "Highlight critical data points and what they reveal about user behavior", "Outline actionable recommendations based on the report's findings for strategic planning." The first is a launch request that needs two gates the agent has not opened; the second and third describe analytical work the agent has no tools or knowledge for. Every suggested opener leads to the interview.

### 2H. Live evidence (what has actually been observed)

- **The only recorded live walk (lane 1, 2026-09-14, v57/v33/recipe 28)** tested plumbing: mounts, scratch persistence, paged reads and spills, `read_claims`, a bogus `read_artifact`, plan edits with revision checks, an ICP variant draft plus gate, a personas document pin. 7 pass, 1 fail. **No item tested strategy, proposal quality, question selection, or an open-ended user.** Findings relevant here: **F1** the model detours into `submit_ingestion@1` whenever it notices the captured onboarding input in context, fails `IncompatibleRecipe` every time, and burns a repair round per turn; **F2** after the plan pin moved by role, the agent still edited `project/plan.md` because the skill says it is "the usual place."
- **A plan-draft turn (`7ffabc38`) died at the 300 s wall clock before writing anything**: "grok-4.6 reading its skills and reasoning for about four minutes, one stretch of it 169 seconds" (v57 pin comment). The caps were raised to 1,800 s / 100 rounds as a result. The cost of a 3,100-line manual disclosed beside a 229-line skill is that the model reads.
- **Turn latencies in the walk: 55 to 295 s** for read-only or single-document turns. A six-question interview at that pace is 10 to 20 minutes of the user's time before anything is proposed.
- **The founder's own observation** (this request): the agent asks, does not act, and repeats the closed-won question. Consistent with A1–A7 exactly.
- **There is no transcript corpus of open-ended sessions**, and grok's reasoning is invisible in the UI, so nobody has seen *why* it chose a question over a proposal on any given turn. Langfuse tracing landed 2026-09-15 (`head-of-abm.turn` traces with tool observations); it is the instrument this audit lacked.

---

## 3. The adoption ledger: what the refinements program put in, and what came out

Honest accounting, because the six-question script is my own text (file `10-draft-skills/abm-craft`, section "Ask like a professional"), transplanted by Aryan into v22 §2 and carried to v33.

| From this folder | Adopted as | Effect in practice |
|---|---|---|
| prompt-v5 delta Block 1 (senior practitioner, diagnose before prescribing, one concrete proposal over an open question, preference restating) | prompt v10 ¶2, nearly verbatim | Present but outweighed: one paragraph of "propose" against ~20 strings of "ask, record, wait." |
| prompt-v5 delta Block 2 (em dash ban, no untraced fact) | prompt v10 ¶3 | Adopted. |
| abm-craft: the question canon | v33 §2, **as an ordered script** | The canon was a *repertoire* ("questions that earn their place early ... prefer confirming a concrete guess"); it became the only script. |
| abm-craft: qualification floor | v33 §2, one sentence | Adopted. |
| abm-craft: posture, diagnostics, program numbers, dynamic lists, measurement, learning loop | **not adopted** | The worldview that makes questions situational is absent. |
| campaign-ideation (signal→play law, three divergent angles, play library) | **not adopted** | Nothing proposes plays. |
| copy-voice (48 bans, per-artifact craft, two-pass) | scheduled "next slice"; lint ruled out (founder ruling 4, 2026-09-10) | Only the two prompt lines exist. |
| knowledge packs (abm-canon, agency-playbook) + exemplar library | **not built**; corpus program is backlog "until the onboarding rebuild ships" (master plan §5) | The agent has no ABM knowledge to draw on. |
| eval plan (E1–E13, pass^k) | ruled out: "No mechanical eval gates or lint anywhere; the prompt and skills carry the behaviour" | No measure of question quality or proposal quality exists. |

Net: the *interview* half of the drafts shipped without the *worldview* and *proposal* halves, and the platform layers underneath it (turn contract, authority list, document-skill gates) all lean the same way. The observed behavior is the expected product of those inputs.

---

## 4. Root causes, ranked by how much behavior they explain

1. **Script literalism.** A2–A4: "one at a time, in this order, skip only when already answered." A low-temperature model given an ordered list and a skip rule executes the list. Nothing licenses judgment about *which* question matters for *this* client, nothing licenses two questions, and nothing licenses a proposal in place of a question.
2. **Planning gated behind the interview and the gates.** B1–B5 make the plan, the profile, and the personas contingent on completed extraction. There is no notion of a provisional plan, a hypothesis brief, or a draft the user reacts to. The agent literally may not do the thing the founder wants first.
3. **No proposal substrate.** 2E + 2F: no ABM knowledge, no play library, no exemplars, no estimation or preview tools, no cost visibility. Even a model inclined to propose has nothing to propose from except the brand files.
4. **The turn contract's gravity.** D1–D4: every turn ends; the human answers in a new turn; `next_actions` means "what I am waiting for"; every turn carries a capture chore whose inputs are the user's answers. A question is the cheapest honest close and also feeds the next capture.
5. **Authority framing dominates identity.** C3–C5: the resolved L1 is mostly what the agent cannot do. The "senior practitioner" paragraph is one of nine paragraphs, and the capability map that follows it is a wall of unavailability.
6. **Success is defined as receipts.** The manual's own summary of a good turn is a routed statement, an opened gate, a queued job, and no fabrication. There is no stated standard for "the client left this turn with a better plan than they arrived with."
7. **Latency and reading burden.** 2H: 15 disclosed chapters, a model that reads them, 55 to 295 s turns. A long interview is expensive for the user in wall-clock, which magnifies the perception of an agent that "only asks."

---

## 5. The spectrums

Each axis is a behavior dimension; the marker shows where v57 sits and where the end goal sits. These are the dimensions we will design skills and success measures against.

| Axis | Left pole | Right pole | v57 today | Target | What moves it |
|---|---|---|---|---|---|
| **S1 Interrogate ↔ Propose** | asks, records, waits | leads with a draft the user edits | far left (one "your view first" moment, gated) | right of center: every turn carries a proposal; questions ride on proposals | propose-then-ask rule; provisional documents; the knowledge to propose from |
| **S2 Wait ↔ Initiate** | acts only on current-turn asks | states what it will do next and does the zero-spend parts | far left ("never start anything the human has not asked for") | center-right: initiates anything that spends nothing; asks for spend | reframe `next_actions`; split the "never start" rule into spend vs no-spend |
| **S3 Platform-literate ↔ Domain-expert** | knows Clue's tools and refusals | knows ABM: economics, plays, benchmarks, failure modes | far left (3,100 : 12 lines) | balanced, with the manual made cheaper to consult | mount an ABM library; skill families; operating card |
| **S4 Single script ↔ Situational repertoire** | six questions in order | dozens of question classes selected by state and client | far left | right: repertoire with selection rules and a no-repeat memory | question taxonomy skill + scratch-notebook discipline |
| **S5 Receipts ↔ Outcomes** | statements routed, gates opened, jobs queued | plan quality, decisions made, actions taken, campaign results | far left | right, measured | the success redefinition in §6; Langfuse session review |
| **S6 Hard-gated ↔ Soft-resonant** | prohibitions stated as cannots | judgment with reasons; only spend and confirmation stay hard | left in wording (nine "never/cannot" strings that are only "asked of you") | right: enforced rules stated as such; everything else as craft | rewrite the authority text; keep the human gates untouched |

The founder's phrase "soft but resonant" is axis S6 applied to S1–S4: keep the human gates on spend and confirmation exactly where they are, and convert every other prohibition into a stated judgment the agent may override with a reason.

---

## 6. Redefining success

### 6.1 What "success" means to the system today (implicit, from the strings and the walk)

A turn is good when it: ends `completed` or `awaiting_input` with a `user_message`; routed every substantive statement with exact quotes; opened the right gate with the ref in `open_gate_refs`; launched only what the current message named; stated no fact without a file or a read behind it; and did not fabricate. All true, all necessary, all about *safety and bookkeeping*. Not one of them measures whether the client is closer to a working ABM program.

### 6.2 The proposed definition: proximity to the end goal

The end goal of a Head of ABM conversation is that the client has **a credible, evidence-backed program they agree with, running, sooner than they could have built it themselves**. Success is distance closed toward that per unit of the client's time. The measures, each with where it can be read today:

| # | Measure | Definition | Readable from |
|---|---|---|---|
| M1 | **Turns to first credible plan** | turns until a plan document exists that names outcome, ICP, list math, tiers, plays, owners, day-90 | `project/` document rows; Langfuse session |
| M2 | **Proposal density** | proposals (a draft, a play, a number, a recommendation the user can accept or edit) per turn | user_message classification (judge over traces) |
| M3 | **Question repertoire entropy** | distinct question classes used per session; repeats of a class within a session | trace classification; scratch notebook |
| M4 | **Action ratio** | turns ending in a durable artifact, launch, or gate vs turns ending in a bare question | turn events + document/launch rows |
| M5 | **Unprompted progress accepted** | things the agent did without being asked (zero-spend) that the user kept | document versions not reverted; decisions recorded as `preference.*` |
| M6 | **Decision velocity** | human decisions recorded per turn, and turns between a proposal and its acceptance | `decisions.md` rows, gate answers |
| M7 | **Plan survival** | share of the agent's plan text the human keeps after editing | document version diffs |
| M8 | **Client wall-clock to first discovery / first research / first artifact** | minutes from thread start | turn timestamps, run rows |
| M9 | **Downstream yield** | candidates approved per discovery; researched accounts per project; artifacts opened in the editor | ARV2 rows, artifact index |
| M10 | **Trust floor (unchanged, hard)** | fabrications = 0; unauthorized spend = 0; em dashes = 0; gates never bypassed | judge + lint over traces; ledger |

Targets are for the next audit to set from a baseline; the baseline needs the 20-session corpus in §8. The only ones worth fixing now as bars: M10 at zero, and M1 at **one turn** for a brand whose onboarding has run (the files exist; a provisional plan is writable from them).

### 6.3 Why this changes what the skills say

Under 6.1, "ask one good question and record the answer" is a perfect turn. Under 6.2, it is a turn that closed no distance unless the answer unlocked a proposal. That single change of standard is what makes "propose, then ask" the default and "ask, then propose later" the exception.

---

## 7. What we could possibly do: the capability map, with proximity per unit of effort

Ordered by expected movement on the spectrums per day of work. Each is a lever on strings or substrate, not a rewrite of the platform.

| # | Lever | What changes | Moves | Effort |
|---|---|---|---|---|
| L1 | **Invert the opening.** First turn on a project: read the files, then deliver a *briefing*: "here is the program I would run for you" (recommended ICP, list-math estimate from the ICP's gates, tier split, three plays keyed to the brand's evidence, what day-90 looks like, the three facts that would change this) and end with the single question whose answer changes the plan most. | v33 §2 rewritten from "ask in order" to "propose, then ask"; plan-authoring "not before" becomes "provisional from turn one, labelled draft, revised as answers arrive" | S1, S2, S5 | 1 day of skill text; 0 code |
| L2 | **A question repertoire, not a script.** A taxonomy of ~10 classes (outcome, evidence-of-fit, list math, buying committee, channels and history, budget and capacity, politics and blockers, timing and triggers, measurement, taste and voice) with 4–6 questions each, selection rules by project state, and a rule to never reuse a class in a session unless the answer moved. | new skill `question-craft`; scratch notebook records asked classes | S4 | 1 day |
| L3 | **Mount the ABM library.** Distill files 02/03/04 into `library/abm/` (canon, tier economics, play library, agency intake patterns, measurement, failure modes, exemplars), mounted read-only like `brand/`, indexed like `brand/index.json`, cited by path like everything else. | new mount + index card; the skills point at it | S3 | 2–3 days incl. distillation; the acquisition program (file 08) grows it |
| L4 | **Skill families for the Head of ABM**, on Aryan's design pattern: metadata discovery, load on demand, each family with when-to-use/avoid, required evidence, decisions owned, counterexamples, and a small evaluation set. Candidate families: strategy-briefing, question-craft, icp-and-list-math, tiering-and-economics, play-design (per channel: direct mail, LinkedIn, dinners, gifting, ads, podcast/content), committee-and-personas, sequencing-and-cadence, measurement-and-reporting, copy-voice, client-preference-learning, objection-and-pushback, program-review. His own caveat applies and should be quoted in the plan: "Skill count is not a quality metric." | 12–20 families over time; four first | S3, S4, S1 | ongoing; first four in a week |
| L5 | **Zero-spend proposal tools.** `estimate_list_size` (AI Ark company-search count against the ICP gates, ~0.1 credit/result or a count endpoint), `scan_project_signals` (a read over existing accounts' P1 claims to suggest plays), `preview_discovery` (top-N candidates without approval), `estimate_program_cost` (from measured per-account costs). Each effect-free or near-free, each gives the agent numbers to propose with. | 3–4 governed reads | S1, S2 | 3–5 days backend |
| L6 | **Reframe the turn ending.** `next_actions` becomes "what I will do next unless you say otherwise", and the skill asks for it on every turn. Zero-spend next actions may be taken on the following turn without re-asking. | skill + prompt text; no contract change | S2 | 0.5 day |
| L7 | **Batch the consent.** One "start the program" confirmation card that carries ICP + product set + discovery target + research effort, instead of three separate gate turns. | a composite gate (backend) | S2, M8 | 2–3 days |
| L8 | **Rewrite the authority text as craft.** Keep the enforced cannots (twelve human-only tools, spend preconditions, no web) stated as enforced. Convert the "asked of you" nevers into judgment with reasons ("start no *spend* without a current-turn ask; anything that spends nothing you may start and report"). Open the identity section with what the agent does. | prompt v11 + manual-gates-authority v5 | S6, S2 | 0.5 day |
| L9 | **Widen the recording vocabulary and lighten the chore.** Route keys for the new question classes and for proposals accepted/rejected (`proposal.accepted`, `proposal.rejected`); recording as a side effect of a proposal turn, not the turn's purpose. | manual chapter + skill | S5 | 0.5 day |
| L10 | **An operating card.** A one-page always-on summary of the manual (the 20 facts that bite: budgets, what reaches the human, the read map, the pin rules) so a routine turn opens zero chapters; chapters stay for the rare case. Cuts the four-minute reading turns. | new short skill pinned; manual unchanged | latency | 0.5 day |
| L11 | **Ungrant the dead tools** (`submit_ingestion`, the directive pair, `get_research_view`) so no repair rounds are spent on them. | profile v58 | latency, F1 | 0.5 day |
| L12 | **Observe, then judge.** Use the Langfuse traces to pull 20 real sessions, classify every turn on S1–S5 and M1–M10, and read them with the founder weekly. This is the eval the ruling allows: no gate, a review. | a script over traces + a weekly hour | S5 | 1 day + ongoing |
| L13 | **Preference learning that survives.** With memory parked, `preference.*` decisions in `decisions.md` are the store; add a skill rule to re-read them before every proposal and to name which preference shaped it. | skill text | S5 | 0.5 day |
| L14 | **Later: an "ABM leg."** The design leg shows the pattern for a durable hand-off; a campaign leg (plan → plays → artifacts → sequence) could be the same shape once L1–L5 exist. | design later | S1, S2 | later |

The first five (L1, L2, L6, L8, L11) are all text and one profile bump, and together they change the observed behavior on the first turn. L3, L4 and L5 are what make the proposals *good* rather than merely present.

---

## 8. What this audit could not see

- **No open-ended session transcripts exist.** The lane-1 walk was controller-driven with specific asks. The founder's report is the only open-ended evidence. Langfuse (2026-09-15) makes a 20-session corpus a one-day pull; that corpus is the baseline for §6.
- **Grok's reasoning is invisible in the UI on this route** (gateway adapter defect, note 2026-09-12), so "why a question and not a proposal" has never been read from the model's own trace.
- **My draft skills never ran live.** Their interview section shipped; their proposal sections did not. This audit does not claim the drafts would have behaved better unmodified; it claims the specific strings that were adopted produce the specific behavior observed.
- **The walk tested plumbing, not judgment.** Every PASS in it is a plumbing pass. There is no quality signal for questions, plans, or plays anywhere in the system yet.

---

## Appendix A — String ledger index

| Id | File | Section | Quote (short) | Effect class |
|---|---|---|---|---|
| A1 | prompts/head-of-abm/v10 | ¶5 | "Ask the questions ... one at a time" | interview |
| A2 | skills/stage0-interview/v33 | §2 | "Ask one question at a time, in this order, and skip ... only when ... already answered" | interview, ordering |
| A3 | v33 | §2 1–6 | the six questions | repertoire = 6 |
| A4 | v33 | §2 end | "Record every answer as you receive it ... Do not batch" | one per turn |
| A5 | v33 | §6 | "Copy the span. Do not describe it." | capture chore |
| A6 | manual-documents-decisions/v4 | route keys | outcome … day_ninety | vocabulary = script |
| A7 | v33 | §3 | "lead with your own recommendation" (only at the profile) | the one propose moment |
| B1 | skills/plan-authoring/v2 | body | "Write it once, not before ... Never write a plan on the first turn" | planning prohibited |
| B2 | skills/icp-authoring/v2 | body | "Do not write a profile before the founding questions are answered" | prohibited |
| B3 | skills/persona-authoring/v2 | body | "only when the human asks for them" | prohibited |
| B4 | v33 | §10 | "You cannot ... start anything the human has not asked for on the current turn" | stated as cannot |
| B5 | manual-gates-authority/v4 | prompt rules | "do not write a profile, or a plan, before the human has discussed one" | prohibited (asked of you) |
| C1 | manual-gates-authority/v4 | spend | "never start anything the human has not asked for on this turn" | initiative |
| C2 | v33 | §7 | "Launch only when the human's current message names the accounts" | spend discipline |
| C3 | prompt v10 | authority ¶ | seven cannots | identity |
| C4 | capability map (generated) | unavailable block | six "unavailable" lines | identity |
| C5 | manual-gates-authority/v4 | never | "Twelve tools are human only" | identity |
| C6 | manual-turn/v4 | cannot see | "Never claim or estimate spend, duration" | no cost in proposals |
| D1 | prompt v10 | final ¶ | `awaiting_input` "when a useful human answer ... is needed" | turn close |
| D2 | manual-turn/v4 | terminals | "must say what you are waiting for" | next_actions = waiting |
| D3 | manual-turn/v4 | rounds | "You must call a tool every round" | short-turn pressure |
| D4 | v33 | §6 | "Route every material statement before you finalize" | capture chore |
| E1 | profile v57 | skills | 15 manual chapters ≈3,100 lines; ABM ≈12 lines | knowledge ratio |
| F1 | lane-1 walk 2026-09-14 | finding F1 | `submit_ingestion` detour, always `IncompatibleRecipe` | wasted rounds |
| F2 | same | finding F2 | plan edited at the "usual place", not the pinned role | path literalism |
| G1 | project-workspace.fixture.ts | suggestions | "Find and research new accounts ..." | user nudged to ask for a launch |
| H1 | profile v57 pin comment | | plan-draft turn died at 300 s reading skills | latency |

## Appendix B — Expected turn path today for the top Home suggestion

"Find and research new accounts we can target before this quarter ends"

1. Agent reads `project/status.md`, `decisions.md`, overview, ICP proposals (§1). No pinned ICP. Cannot launch (§7b). Asks question 1 (outcome). Records nothing (nothing material yet) or routes `unmapped`. `awaiting_input`.
2. User answers. Agent records `outcome`. Asks question 2 (last three closed-won). `awaiting_input`.
3. Records `closed_won_pattern`. Asks question 3 (list math). Note: it asks the user for list math it could estimate from the ICP's gates if it had a count tool.
4. Records `list_math`. Asks question 4 (channels tried).
5. Records `channels_tried`. Asks question 5 (follow-up ownership).
6. Records `follow_up_owner`. Asks question 6 (day ninety).
7. Records `day_ninety`. Now "reaches the profile": proposes an ICP from the files, asks for the user's view. `awaiting_input`.
8. User picks. Opens the product-set gate. `awaiting_input`.
9. User answers the gate (a new turn). Opens the ICP confirmation gate. `awaiting_input`.
10. User approves. ICP pinned. Agent may now write the plan (B1) and may launch discovery **only if the user asks again on this turn** (C2). Typically it asks whether to start discovery. `awaiting_input`.
11. User says yes. `launch_arv2_discovery`. "The discovery is running." `awaiting_input`.

Eleven turns, at 1 to 5 minutes each, with zero proposals until turn 7 and zero plays or numbers at any point. Under L1 + L6 + L8 alone, the same request becomes: turn 1 a briefing with a draft plan and one question; turn 2 the batched confirmation; turn 3 discovery running with the plan revised.
