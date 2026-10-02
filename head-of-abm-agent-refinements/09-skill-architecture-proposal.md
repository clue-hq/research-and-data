# 09 — Skill architecture proposal: making the Head of ABM the smartest agent in the category

**Date:** 2026-08-31 · **Status:** proposal, awaiting founder + Aryan ratification · **Inputs:** files 01–08 in this folder (11,800+ lines of audited platform state and live-verified research).

---

## 0. The one-paragraph thesis

The Head of ABM today is a well-governed empty suit: prompt v4 is 57 lines of authority rules and its two live skills are platform *procedure* (file 01). Everything the founder wants — "what good ABM looks like," creative campaign ideas, agency-grade client conversation, copy that never smells like AI — is missing not because the harness can't hold it, but because nobody has ever put domain knowledge into the catalog. The catalog is already the right container (versioned, sha-pinned, progressively disclosed — exactly the pattern Anthropic's skills feature uses, per file 06). So the program is: **harvest the practitioner canon (files 02/03/04 already are the seed corpus), distill it into three new skills + two knowledge packs + one exemplar library, patch the prompt with a small identity layer, bind the voice constitution to every role that writes words, and gate it all with a two-track eval harness.** No new machinery; new *content* in existing slots.

## 1. Design stance (the rules this proposal obeys)

Grounded in file 06's ten principles and the platform's own constraints:

1. **Context is a budget** (8,192 output tokens, 24 rounds, 300s turns). Domain knowledge goes into load-on-demand skills and workspace knowledge files, never into the always-on prompt. The prompt gets ~20 new lines, not 500.
2. **Skills are procedures + worldview; packs are facts.** A skill teaches *how to think*; the knowledge pack it cites carries the distilled evidence (with source URLs, mirroring the claim discipline). Packs version independently of skills, so a fresh benchmark number never forces a skill re-review.
3. **Degrees of freedom differ per surface** (file 06, principle 8). Governance stays a narrow bridge (unchanged, prompt v4's authority text survives verbatim). Strategy and ideation are open fields: the skills instruct the agent to propose, diverge, and argue, not to follow checklists.
4. **Soft guardrails, exactly as the founder ruled.** The only hard rules added anywhere in this program are: the em-dash ban + fabrication ban in copy, and the existing human gates. Everything else is stated as craft judgment the agent may override with a stated reason. Judgment annotates; it never vetoes.
5. **The agent's natural tendency is to ask and to learn.** Question-asking is upgraded from one prompt line to a named move-set (§3.1); preference capture rides the already-wired scoped-memory substrate (file 01, G5).
6. **Every distilled assertion is traceable.** The corpus pipeline (file 08) requires a byte-exact evidence span per extracted assertion, two independent domains for anything stated as consensus, and a `make corpus-check` CI gate. The agent's knowledge inherits the platform's provenance religion.

## 2. Target architecture (what exists after the program ships)

```
prompts/head-of-abm/v5/SYSTEM.md          ← v4 + ~20-line identity/routing delta   (draft in 10-draft-skills/)
profiles/head-of-abm/v39/profile.yaml     ← grants the new skills + packs

skills/
  abm-craft/v1/SKILL.md                   ← NEW: the worldview + planning + questioning + learning   (draft ready)
  campaign-ideation/v1/SKILL.md           ← NEW: signal→play ideation system                          (draft ready)
  copy-voice/v1/SKILL.md                  ← NEW: the voice constitution                               (draft ready)
  stage0-interview/v21/SKILL.md           ← small delta: the agency question canon folded in
  account-deep-steering/v9/SKILL.md       ← ARV2-vocabulary rewrite (blocked on ARV2 toolbelt landing)

context packs (read-only workspace resources, per file 01 §4):
  knowledge/abm-canon-pack.md             ← distilled from file 02 (tier economics, benchmarks, failure modes, case studies)
  knowledge/agency-playbook-pack.md       ← distilled from file 03 (ColdIQ onboarding, Fullfunnel 6A + dynamic lists, qualification floors)
  exemplars/                              ← the curated GOOD/BAD artifact library (file 07 seeds it; corpus Phase 1 grows it)

evals (extends M9.6, file 06 §4c):
  GOLD_SUITE "head_of_abm", TurnFixtures E1–E13, pass^k reporting, make eval-abm with a real exit code
```

**Voice binding is cross-role by design:** `copy-voice` is granted to head-of-abm, content_drafter, and reviewer profiles, and its core rules ride the design-leg delegation bundle so ads/mailers can't regress to slop while chat stays clean (file 01, G3). The reviewer's `artifact-review` checklist gains one line: run the voice lint (file 07 §4d ships a working linter: regex tier for the mechanical bans, judge rubric for the rest).

## 3. The three new skills (what each actually teaches)

Full drafts are in `10-draft-skills/`; this is the intent spec.

### 3.1 `abm-craft` — how a great Head of ABM thinks

The worldview skill, distilled from files 02 + 03. Its load-bearing content:

- **The qualification gate, applied to the client.** The field's convergent floor (ACV ≥ $30–50k, sales cycle > 180 days, bounded TAM, a real buying committee, a named sales counterpart) and the professional courage to say "your motion isn't ABM-shaped yet; here is the cheaper thing to do first." Great agencies disqualify loudly (Growth Engine X publishes its floors; Cosby publishes his price). The agent should too — that is what "senior" sounds like.
- **The diagnostic vocabulary.** "That's not ABM, that's targeted demand gen" (the field's consensus insult, used by Snowflake, Ramp, Hightouch, and Fullfunnel independently); Cosby's CRM test ("add 'is customer' as a filter — is that really your ICP?"); the black-box complaint Clue exists to answer ("why is this account a 92, and what actually fired").
- **Program shape by numbers, not vibes.** Tier economics (cost-per-meeting $4–8K / $1.2–2.4K / $300–800; win rates 25–40% / 12–22% / 4–8%; the 70/25/5 mix), hard account caps (10–20 per person; 10 max for a pilot), the 417-touchpoint reality for >$100k deals, expansion-first gravity (91% of programs grow existing accounts), and the honest pilot benchmark (Fullfunnel: 46 accounts, 3 people, <$1k/mo tooling, 90 days → 8.7% account-to-pipeline).
- **Fullfunnel's three dynamic lists as the agent's state vocabulary** (Cluster ICP / Future Pipeline / Active Focus, re-tiered on signal movement) instead of static tiers — this maps directly onto the platform's living-accounts freshness story.
- **Measurement with a spine.** Control groups over attribution theater; Jon Miller's own verdict on influenced pipeline ("a terrible idea"); what to report weekly to a client (coverage, engagement deltas, next actions — the testimonial evidence in file 03 shows clients buy *visibility*, not creativity).
- **The question canon + learning loop.** The ~15 discovery questions elite agencies actually ask (TAM math before copy; "what did your last three closed-won deals have in common"; channel history; who owns follow-up), the rule of one-material-question-at-a-time (already in prompt v4, now with content behind it), and explicit preference capture: when the user corrects tone, tiering taste, or channel appetite, write it to scoped memory and confirm it back in one line.

### 3.2 `campaign-ideation` — the signal→play system

Creativity with evidence discipline, distilled from files 02 + 03 + the smoke-test signal classes:

- **The core law: plays attach to signals, not to accounts.** A play proposal must name the researched P1/P2 claims it rides (champion's public tool-shopping post, 105-day unfilled ABM req, new-in-seat CEO, vacant champion seat, funding + GTM hiring wave). Signal stacking (three independent signal categories ≈ 3–5× baseline conversion, Autobound's law) is the selection rule; "a signal everyone can see is not alpha" is the differentiation rule.
- **A play library keyed by tier × persona × signal**, seeded with the best-evidenced plays from the research: executive dinners (the best per-unit economics found: $5–10K all-in, 4+ qualified meetings target), gifting/direct mail (Verkada displaced email with it in EMEA; Melissa's verified-business-address flow already spec'd), LinkedIn resequencing (profile view → connect → email took ColdIQ replies 1.8% → 4.3%), the padded-audience 1:1 ad surround, book/content plays (Coram AI's 65×), podcast-as-ABM, new-buying-center expansion plays (Scenario ABM, 81% adoption), and the channel doctrines to hold in tension (ColdIQ: tier-first multichannel; Nowoslawski: don't orchestrate LinkedIn with email at Tier-3 volume — pick by tier).
- **The ideation procedure:** always propose 3 divergent angles per account (mode collapse is eval task E8's target), each with the signal citation, the persona it lands on, effort class, and a kill criterion. The user picks; the agent records *why* (preference learning).
- **Boundaries as craft, not chains:** never propose a play on SENSITIVE-class claims; never fake scarcity or personal intimacy (relevance ≠ personalization, file 03's "I saw you have a dog" rule); respect the 417-touchpoint honesty (a play is a chapter, not the book).

### 3.3 `copy-voice` — the constitution

File 07 §4 nearly *is* the skill; the draft compresses it to skill length:

- **Non-overridable core:** no em dashes anywhere in user-facing copy, ever, including when a brand-voice sample uses them (the one place we deliberately diverge from humanizer); no fabricated facts (every specific claim in copy traces to a claim id or the user's own words); no fake personalization.
- **The banned-pattern tiers:** the mechanical tier (lintable: em dash, "I hope this finds you well", "quick question", "delve/testament/landscape" cluster, rule-of-three stuffing, bold-title-case headers, chatbot sign-offs) and the structural tier (judge-scored: uniform sentence rhythm, hedging stacks, formulaic outlook endings, moral flatness). File 07's key finding shapes the emphasis: phrase-banning alone barely moves detection (95.5% → 93.9%), so the skill leads with structural habits.
- **Positive craft per artifact:** cold email (under ~90 words, one specific evidence-anchored observation, one named ask, reading level ~grade 5–7), LinkedIn post/ad, direct-mail letter, landing hero, client chat replies. Each with the linter-validated GOOD/BAD pair from file 07 as its exemplar anchor.
- **The two-pass discipline:** draft for meaning, then rewrite against the constitution; the reviewer runs the lint + rubric; "admitting a limit" is both the human tell and the conversion tactic (StoryScope's ambivalence finding × Lavender's 35%-more-replies for unsure tone).

## 4. Evals (condensed from file 06; the release gate for all of the above)

- **Track V (deterministic, the gate):** graded off end state — gate ledger, tool trace, claim store, lint output. Hard bars: 0 authority violations, 0 injections honored, 0 em dashes in any rendered artifact.
- **Track J (judged, the trend line):** rubric judge from a different model family, anonymized, order-randomized, length-normalized; never a release gate on its own (JudgeBench: judges go near-random exactly on hard correctness).
- **Reliability, not averages:** report pass^k (k=5 default, k=8 at the gate), per τ-bench's finding that a >60% pass^1 agent can be a <25% pass^8 agent.
- **The 13 tasks** (E1–E13, specified in file 06): minimum-input Stage 0, known-product refresh, directive + effort ladder, delegation completeness, authority trap, sycophancy trap, copy loop, slate diversity, originality vs. no-skills baseline (must win ≥70% of anonymized pairings or the catalog is decorative), tool efficiency, stale evidence, prompt injection, and the $0.51 smoke test re-run as a cost-gated regression baseline.
- **Mechanics:** `GOLD_SUITE "head_of_abm"`, `TurnFixture` sibling to `GoldPack`, two new negative `FixtureKind`s, and an enforced `make eval-abm` that actually exits non-zero (today's demo target always exits 0).

## 5. Rollout sequence

| Step | What | Depends on | Effort |
|---|---|---|---|
| R1 | Corpus Phase 1 harvest (file 08 §2: 6 agents, 2 waves, one day, $45–75) | founder decisions D1–D5 below | 1 day |
| R2 | Distill packs (abm-canon, agency-playbook) + exemplar library v1 through the file-08 pipeline (founder review capped at 150 assertions/session) | R1 | 2–3 days incl. review |
| R3 | Land `copy-voice` v1 + lint in reviewer flow + design-leg bundle | none (draft ready; file 07's linter works today) | 1 day |
| R4 | Land `abm-craft` v1 + `campaign-ideation` v1 + prompt v5 + profile v39 (catalog workflow per `docs/agents/skill-and-profile-authoring.md`: new version folders, sha256, registry pin, manifest digests, qualitative fixtures) | R2 (packs cited) | 1–2 days |
| R5 | Eval suite E1–E13 + `make eval-abm` gate; baseline run recorded | R4 | 2 days |
| R6 | `stage0-interview` v21 question-canon delta | R4 | 0.5 day |
| R7 | `account-deep-steering` v9 ARV2 rewrite | **ARV2 toolbelt build landing** | 1 day, later |
| R8 | Phase 2 corpus expansion + standing freshness monitors (file 08 §2) | R5 green | ongoing, cheap |

Nothing in R1–R6 touches the ARV2 build's critical path, and nothing waits on it except R7.

## 6. Founder decision queue (consolidated from every file)

1. **D1 — Reddit posture:** ratify "human reading → first-party notes only" (file 08's legal analysis; the .json route is dead anyway).
2. **D2 — YouTube posture:** ratify default-off with podcast-RSS transcripts as the substitute (four shows, ~950 episodes, free and clean).
3. **D3 — Exa permission ask:** send the written derivative-works/DPA question to Exa (affects the research product too, not just this corpus — file 08 §1).
4. **D4 — Creator-PII ceiling:** how long raw creator content is retained vs. distilled-and-dropped (file 08 §5).
5. **D5 — Seed source list sign-off:** the 46-creator roster + Tier-1 crawl targets (file 04). The seed list *is* the agent's taste; 30 minutes of founder pruning here is worth more than any later tuning.
6. **D6 — The em-dash carve-out** is written as non-overridable even by client brand samples (file 07 §3). Confirm.
7. **D7 — CTA line:** file 07 §3.7 permits interest-based CTAs only when the ask names the specific thing behind the yes ("Open to taking a peek?" stays banned). Confirm or loosen.
8. **D8 — Buy Bev Burgess's 2025 ABM handbook** (~$50): the ITSMA five-type definitions are book-gated, the single biggest content gap in the canon (file 02, finding 1). One purchase closes it legally and completely.
9. **D9 — ColdIQ competitive response:** out of scope for this folder but too big to bury: ColdIQ has pivoted from agency to product ("Build your Revenue Engine Inside Claude Code," $99–499/mo, 40+ providers) with a thesis nearly verbatim Clue's. File 03 argues Clue's counter-position is verifiable provenance-bound evidence vs. their tool-routing. Deserves its own strategy session.
10. **D10 — ColdIQ email-gated guides:** whether to subscribe (a human, normally) to read `/guides/*` bodies (file 03 register).

## 7. Honest limits of this program

- **Skills make the agent knowledgeable, not experienced.** The learning loop (memory + eval baselines + per-client preference capture) is what compounds; expect the agent to be impressive at R4 and *trustworthy* only after E1–E13 baselines and a few real client cycles.
- **Book-gated and 504-blocked sources** (ITSMA handbook, momentumabm.com) leave named gaps; both have queued remedies (D8; retry crawl).
- **The voice constitution reduces, not eliminates, AI-detectability** (file 07's 93.9% finding). The real defense is the platform's structural advantage: copy built from verbatim researched evidence is *specific*, and specificity is the one thing slop can't fake.
- **Two summaries' numbers were budget-limited** (WebSearch caps hit in agents 02/03/04); every affected item is tagged in-file rather than silently asserted.
