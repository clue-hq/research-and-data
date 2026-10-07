# 1:1 account page copy — design spec (2026-10-07)

**Status:** draft for founder review.
**Branch:** `website-quality/week1` (trenton lane).
**Inputs:** skill text `2026-10-07-account-page-copy-skill-draft.md` (approved in chat
2026-10-07), worked example `2026-10-06-syracuse-copy-trial.md` (approved), defect register
`docs/superpowers/plans/2026-10-06-website-run-defects.md`.

## 1. Why

The three website runs of 2026-10-05/06 produced accurate pages that read like research reports:
- several of the account's own figures in one band;
- seven or eight sections;
- strategy notes and caveats leaking onto the page (A1, A2, A10);
- proof that did not match the page's claim (Nightingale's results came with plan changes, set
  under "no plan-design change");
- cloned seller sections replaced with composed ones.

The guidance behind them is spread across eight skills and references (about 14,000 words) that
overlap and sometimes pull against each other. One example: `web-decision-material` says a
shortage of slots is no reason to cut substance, while the founder's rule is reuse first.

The hand-written Syracuse trial shows the target: about 300 words, five sections, every section a
cloned Garner section with its words edited, one figure from the account's own documents, and
proof found on the seller's own site. The founder approved its copy and its preview on Garner's
real design.

## 2. Founder rulings this spec carries

| Date | Ruling |
|---|---|
| 2026-10-06 | One primary reader per page, as a role (Ploy). |
| 2026-10-06 | Default five sections; length follows the decision, rarely over 600 words. |
| 2026-10-06 | Reuse and edit cloned sections as much as possible; writing a section from scratch is the last option. |
| 2026-10-06 | The design agent may search the seller's own site for official, published case studies about similar customers. |
| 2026-10-06 | The design agent makes a plan, sticks to it and keeps referring to it; the copy and personalisation skill guides the plan. |
| 2026-10-06 | Ploy's anti-slop rules apply strictly. |
| 2026-10-07 | The hero may state a result when attributed proof of it appears further down the page (departs from Ploy's offer-only hero). |
| deferred | The proof qualifier sentence ("their results, not a projection for you"). Not in this spec. |

## 3. What changes

### 3.1 New design skill `account-page-copy`

- `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/account-page-copy/SKILL.md`:
  the approved draft text, unchanged except one addition to §4 taken from `copy-craft.md`'s
  "Copy through slots":
  - match the original's length and line count;
  - write like the same author: the clone's own words are the seller's published language.
- `…/account-page-copy/references/worked-example-syracuse.md`: the trial's message plan and page,
  each section with its source clone, the original wording and the edit. It also lists the
  "left out" decisions and the sources for every fact. The trial doc's review notes, tool-gap
  notes and claim ids stay out (the agent does not need them).

The skill is the single entry for the message and the words of a page for one named account. It
applies only to 1:1 pages. Event, product, 1:few and 1:many pages keep their current guidance.

### 3.2 Retire and re-point the overlapping design guidance

| File | Change |
|---|---|
| `web-account-personalization/references/account-argument.md` | Deleted. Its 1:1 decision map and page shape are replaced by `account-page-copy`. |
| `web-account-personalization/SKILL.md` | The "Read account argument" line becomes "For a page for one named account, read `account-page-copy` before planning." Identity, evidence and audience-mode references stay. |
| `conversion-copywriting/SKILL.md` | A page for one named account reads `account-page-copy` instead of copy craft and the website copy brief. Other pages are unchanged. |
| `campaign-landing-page/SKILL.md` step 3 | Named-account pages use `account-page-copy` for the argument and the words. `web-decision-material` is no longer a default read for them. |
| `campaign-page-workflow/SKILL.md` step 3 | Same re-point. Step 5's table gains the reuse order from `account-page-copy` §4 (compose only when no clone can carry the point, with the reason in the plan). |
| `plan-design/SKILL.md` | For a named-account page, `plan.md` starts with the message plan from `account-page-copy` §1, above Anchors. Section records take their Words from it. Before writing each section and before finalizing, re-read the message plan. The website copy brief read applies to other pages only. |
| `review-website/SKILL.md` step 3 | The account-argument link becomes `account-page-copy`. For an account build, compare the page with the message plan and run its §6 final check. Results go in the final report. |
| `web-decision-material/SKILL.md` | Scoped down: for a 1:1 page it is used only when the message plan calls for an exhibit, and `account-page-copy` §4's reuse order wins over "write before choosing the container". |
| `knowledge_docs/knowledge/web/skill-families.md` | The Personalization row adds `account-page-copy`. |

The landing-page composition reference (`knowledge_docs/knowledge/web/landing-page.md`) is checked
during planning for contradictions with the new skill. It is changed only where it conflicts.

### 3.3 Design agent prompt (`lumen_agent/prompts_web.py`)

- `WEB_ACCOUNT_EVIDENCE`: replace "read copy-craft.md in full, and for a named account also
  account-argument.md" with: for a page for one named account, read
  `/.deepagent/skills/account-page-copy/SKILL.md` and its worked example in full before
  planning. Write its message plan at the top of `plan.md` before building, and re-read it before
  writing each section and before finalizing. Pages without a named account keep copy craft.
- `WEB_SKILL_ROUTING`: add "for a page for one named account: account-page-copy" next to the
  personalization line. Keep `web-decision-material` named for exhibits.

### 3.4 Case-study search (design agent only)

- `lumen_agent/platform_reads.py`, the `web_search` docstring the design agent sees: keep "account
  reads and seller files first". Add a second permitted use: the seller's own published case
  studies, customer stories and studies, searched with `include_domains` set to the seller's
  domain, then opened with `fetch_page` before any number or quote is used.
- The platform's `WebSearchTool.model_description` (what Head of ABM sees) is unchanged, so
  Head of ABM's manual text for the tool does not move.

### 3.5 Head of ABM

**Brief rules** (`manual-siblings` → v19, "How to write the brief for a page"):
- **For the page** holds only:
  - that this is a 1:1 page for one account;
  - the one primary reader, as a role;
  - the insight in the account's own words, with its source;
  - two or three priorities;
  - the offer and its one action;
  - proof candidates, with links;
  - at most five suggested sections.
- No list of research facts. Design reads the research itself; the brief points to it.
- Every caveat, "do not claim" item and strategy angle goes under **Notes for Design, never
  shown on the page**.
- When the account is not an ordinary buyer (for example a near-competitor, as with Dana.AI),
  raise the fit question with the human before opening the design session. This is a
  recommendation, never a block.

**Plan skill** (`plan-authoring` → v3). Add a part for projects that include pages for named
accounts. For each account it records:
- why this account;
- the one insight;
- the primary reader;
- the offer and action;
- which assets, in what order;
- whether research is done.

It stays a few lines per account inside the same plan document. The brief for that account's
page draws from these lines. The program-plan part is unchanged.

**`open_design_leg` description** (`platform/api/clue_api/design_leg_tools.py`): align the brief
sentence with the new rules. Replace "Queued is not finished: never say the design is done."
(defect D2: Head of ABM repeated it to the user) with wording that is an instruction, not a
quotable line: tell the user the design has started and takes a few minutes, and end the turn.

**Versioning**, following commit `530e8172d` (v72):
- profile `head-of-abm@v73` pinning the new skill sha256s;
- `MANUAL_VERSION = "v19"`, `PROFILE_VERSION = "v73"` in `platform/agents/clue_agents/manual/build.py`;
- regenerate the manual with `python -m clue_api.manual_build --write` and `--link`, then
  check with `--check`;
- `stage0-interview` bumped only if the manual build requires it (it did for v72);
- registry active versions in `agent_registry_wiring.py`;
- `PROJECT_CONVERSATION_AGENT_PROFILE_ID` in `chat/composer_context.py`;
- `tool_notes.yaml` if refusal codes change (none expected);
- the catalog and registry tests updated as in v72.

## 4. What does not change

- Research reads, `read_account_research@3`, the context-clearing middleware and the render and
  review tools.
- Copy guidance for pages without a named account (copy craft, website copy brief).
- The platform `web_search` tool and Head of ABM's view of it.
- Tooling defects found by the trial stay in the defect register:
  - C1, the button label baked into the hero;
  - removing or redirecting the links inside the audience strip, which this plan checks against
    `repair_cloned_section` and records if missing.

## 5. Tests

Focused tests only. The full clue-design suite (7–8 hours) is never run.

**Design runtime** (`apps/agent_runtime/tests/test_web_skill_family.py` and the prompt wiring
tests):
- `account-page-copy` is in `SKILLS`, is discoverable after materialization, and its worked
  example is delivered through the skill's own link (`read_required_skill_reference`).
- `web-account-personalization` and `review-website` both link to `account-page-copy` with the
  required sentences. This replaces the two account-argument tests.
- `account-argument.md` no longer exists, and no materialized skill or prompt links to it.
- `WEB_ACCOUNT_EVIDENCE` names `account-page-copy` and no longer names `copy-craft.md` for
  named-account pages. `WEB_SKILL_ROUTING` names `account-page-copy`.
- The design-side `web_search` docstring permits seller-domain case-study search
  (`include_domains`) and still puts account reads and seller files first.

**Platform:**
- `tests/agents/test_catalog.py`: v73 pins the new skill versions and hashes.
- `tests/api/test_agent_registry_wiring.py`: the registry and composer point at v73.
- `manual_build --check` is clean, and `test_manual_drift` passes.
- `tests/api/test_web_search_tool.py` is unchanged and still passes ("Use this last" stays).
- The `open_design_leg` description no longer contains "Queued is not finished".
- DB suites run only on `clue_trenton_test` @55160, with no live keys
  (`--ignore-glob='*_live.py'`).

## 6. Acceptance (founder-run live)

The founder runs two new page requests in new chats:
- Syracuse City School District (Garner);
- one Conduit hospitality account other than Dana.AI.

Each run passes when:
1. `plan.md` starts with the message plan (reader, insight, priorities, offer, proof, sections
   with budgets, left out) written before the first build tool.
2. The page has five sections or fewer, and under about 600 visible words, not counting the
   header and footer.
3. Every section is a cloned section unless `plan.md` records why none could carry it.
4. Every proof item is attributed and comes from the seller's files or a page on the seller's own
   domain that the run opened with `fetch_page`.
5. No caveat, strategy note, file name or line code appears on the page.
6. The final report contains the §6 final-check results.
7. Head of ABM's brief follows the new format (no fact dump; caveats in Notes).

The copy is compared with the Syracuse worked example. Cost and model calls are recorded against
Run 3 ($4.14, 38 calls).

## 7. Risks

- **Two contracts for one page.** If any skill still points account pages at the retired guides,
  the agent reads both. The tests in §5 pin the re-pointing; planning greps every link.
- **Overfitting to Garner.** The Conduit acceptance run is the held-out check. If it fails, the
  skill changes, not the example.
- **Clone-only pages hit tool gaps** (C1, strip links). The agent's fallbacks are text edits, or a
  recorded composed section. Either is acceptable for acceptance as long as it is recorded.
