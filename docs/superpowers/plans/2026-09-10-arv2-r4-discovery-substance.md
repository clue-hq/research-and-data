# ARV2 R4 — verified account discovery, the plan of action (2026-09-10, rev 5)

**Status: the approach is settled in discussion (founder, 2026-09-10) and recorded here; every ruling in §9 is taken except 6′, which the founder decides with the target-accounts tab. The R4
implementation plan (tasks, files, tests) is written from this document next, then implemented by
subagent-driven development. Nothing in this document is code yet.**

Rev 5 replaces rev 4's probe (hand-written regexes per gate) with the verifier the proofs of
concept settled on, and records every ruling taken in the discussion. Evidence for each claim
below is in `.context/arv2-websets-experiment/` (`evaluation.md`, `hybrid/hybrid_evaluation.md`,
`comparison-shashank-vs-hybrid.md`, `answer/answer_evaluation.md`) and summarised in
`_memory/2026-09-10-arv2-r4-websets-experiment.md`.

## 0. What R4 delivers

A cohort of accounts is **discovered** from the project's pinned ICP, every candidate is
**verified** gate by gate with a quote and a source, the human **approves** on the accounts table,
the approved accounts are **researched** by the existing R2/R3 lane and **displayed** on the
existing screens. The master plan's exit gate, a 20-account cohort end to end, is measured on the
Clue ICP (ruling 1).

## 1. The principle: the ICP document is the program

Every confirmed ICP carries `hard_gates[] {key, rule, test}` and `exclusions[]`, written in plain
language by the onboarding agent and confirmed by a human. R4 never encodes a gate in code. The
finder is built from the ICP's wording; the verifier asks each gate's own `rule` and `test` as a
question. A new ICP changes the questions and nothing else. Pattern code keeps one role only:
reading structured provider payloads (JSON), never prose.

What the proofs of concept showed, and why the design is this shape:

- Exa `/search` prose queries return content *about* the ICP, not members of it (six companies from
  thirty pages; two of three queries returned job boards and advice). Exa **Websets** in company
  mode returns companies (fifteen, no noise) — but its criteria verdicts were wrong six times in
  fifteen even with the criterion written correctly, and it returned the wrong website for Probook.
- A hand-written probe (regexes for "Series A", GTM titles, "outbound") mis-graded Avoca, needed
  tiebreakers that meant nothing, and would need rewriting for every new gate. Dropped.
- Exa **Answer** with a system prompt and a JSON `outputSchema`, asked the gate's own test text,
  agreed with hand-checked truth 24 of 26 times, at $0.005 and ~2 s per question, with a verbatim
  quote found on the cited page 69 times in 72. The same questions through `/search` with the same
  prompt and schema cost more, ran slower, and misread "Series A or Series A extension" on nine
  companies. Answer is the verifier.

## 2. Step one — the long list (Exa Websets)

- **Input**: the project's pinned confirmed ICP (`project_icp_pin`, via
  `arv2/icp_confirmation.current_project_icp_pin`); no pin → refuse `project_icp_not_pinned`.
- **One webset**, `entity.type = company`, `query` = a plain sentence compiled from the ICP's body
  (what the company sells, to whom, at what stage), `count` = the strict-pass ask (§4), and **at
  most three criteria**, each a hard gate a public page can answer, worded as the ICP means it
  (the stage criterion says "most recent round is …"; "announced a … within N months" admitted two
  Series B companies). Hiring and intent are never webset criteria (success rates 3.7% and 2.7%
  starved the search to one company); they are verified in §3.
- **`recall: true`** on the search, so the run records Exa's estimate of the pool size before
  spending; `found` versus `analyzed` versus the ask is recorded on the run either way.
- **Exclusion before spend**: local dedupe by verified domain against the workspace's accounts,
  always; the Websets `exclude` import of existing account websites once Exa confirms the per-plan
  cap (ruling, rev 5).
- **Async**: create, poll to `idle` with a stale guard (a 30-minute wall), raw saved, credits
  estimated at 10 per all-green result and recorded on the ledger. **No money stop** (ruling 3,
  rev 2): costs are recorded, never a gate. The paid plan is in place (ruling, rev 5).
- **`/search` stays** for the domain lock when a human names a company, and as a later recall
  angle (signal-first announcement and job-post queries) if the pool proves short in practice.

## 3. Step two — the verifier (Exa Answer), every candidate, every gate

For each candidate, first **verify the company's website**: the domain Websets returned must be
the one the candidate's own funding announcement or LinkedIn page names; if not, the announcement's
domain wins and the mismatch is recorded (Websets gave `probook.com` for `probook.ai`). Then
**dedupe** by that domain against the workspace (`disposition = duplicate_of_existing`, no spend).

Then one `POST /answer` per hard gate (and per page-answerable exclusion), with:

- `query` = "Company: <name> (website <url>). Test to verify: <gate.rule>. How it is tested:
  <gate.test>. Decide pass, fail or unclear for THIS company today, citing the freshest relevant
  source." — the ICP's words, verbatim;
- `systemPrompt` (one paragraph, the same for every call): today's date; use only what the sources
  say; the most recent dated announcement of an event is the authority on the current state, older
  announcements are history; profile pages (LinkedIn, Crunchbase, CB Insights, Tracxn) rank below
  the company's own pages and dated news; never confuse the company with a same-name company on a
  different website; pass only when a source states the fact, fail only when a source contradicts
  the test, otherwise unclear; the quote must be copied verbatim;
- `outputSchema` = `{verdict: pass|fail|unclear, reasoning, evidence_quote, evidence_url,
  evidence_date}`; `text: true` so citations carry page text; `model: exa`.

**Three guards in code**, one per error kind the proof of concept produced, and nothing else:

1. **Quote on the page.** `evidence_quote` must appear verbatim (whitespace and typographic
   punctuation normalised) in the text of a citation Exa returned; otherwise the verdict is
   `unclear`.
2. **Right company.** The cited URL's domain must be the company's verified domain, or a news or
   job-board page whose text names the company; a posting from a same-name company on another
   domain (INFI → infinIT) becomes `unclear`.
3. **Arithmetic is code's.** When a gate names a window, `evidence_date` is checked against it in
   code (Superorder's 2023 round was called "within 24 months" by the model).

And one instruction made explicit in the prompt and enforced in code: **no source found is
`unclear`, never `fail`** (DentalHQ, Superorder hiring). **Aggregator job sites count** as hiring
and intent evidence when the posting names the company and the role (ruling 5, rev 5).

Every verdict is stored on the candidate row as `{gate_key, verdict, reasoning, evidence_quote,
evidence_url, evidence_date, guard}` with the raw Answer response saved and the call on the
ledger. Cost measured: ≈ $0.02 per company for four gates.

**Fit** (rulings 4 and 5, rev 2, and (a), rev 4): `passes / gates` with an unclear gate counted as
half a pass; the accounts list's own bands (`CLUE_ARV2_FIT_HIGH_THRESHOLD` 0.70,
`CLUE_ARV2_FIT_MEDIUM_THRESHOLD` 0.40). A full match reads **High 100**; three passes and one
unclear **High 88**; half **Medium 50**; one of four **Low 25**. The Overall fit vocabulary stays
exactly High / Medium / Low; an unclear account is a Medium by score.

## 4. The number the human asked for — strict pass, then relaxed pass

The human's number means **approved accounts**. Websets keeps only the companies that pass all
its criteria; the rest are discarded and cannot be listed after the fact.

1. **Strict pass**: the §2 webset with the full criteria, `count` = the ask (ruling 4, rev 2: 35
   for a target of 20 while precision is being measured).
2. **Relaxed pass**, when the strict pass falls short: a second search on the same webset with a
   relaxed criteria set (for example without the stage criterion), `exclude` = the strict pass's
   results, `count` = the shortfall. Every company it returns is verified on **all** gates in §3
   exactly like a strict one, so it lands as Medium or Low fit with an honest score — partial
   matches are shown with an honestly weaker signal, never hidden (ruling 4, rev 2).
   **Both triggers are supported** (ruling, rev 5): automatically when the strict pass is short, and
   on request by the human for a run that already finished.
3. **Exhausted pool**: when strict and relaxed passes together still fall short, the run records
   `asked`, `found_strict`, `found_relaxed`, `analyzed` and Exa's recall estimate, and says so; the
   human decides whether to widen the ICP. A short list is information, never padded.

## 5. Step three — what the human sees and does (no frontend change)

Founder rulings 2 (rev 2), rev 3 and rev 4: the accounts table is the approval surface for now;
**nothing in the frontend changes**, not the lifted screens, not a slot, not a marker; parity with
the dummy frontend (`clue-frontend/live-backend-v1`, live at `localhost:3000`) is the reference.
Frontend suggestions live in `2026-09-10-arv2-frontend-polish-backlog.md` for a separate session.

When a discovery run finishes, every verified candidate that is not a duplicate becomes an
`account_entity` (`status = candidate`, verified domain as the strong key, workspace-scoped) with:

- one `account.scoring.fit` claim (project-relative; the run's `run_lineage` row, kind
  `discovery`, attributes it to the project) → the table's **Overall fit** badge and **Fit score**;
- the ordinary `core.revenue_band` / `core.employee_count` claims from the Websets firmographics
  when present (source `exa_websets`);
- the per-gate verdicts with quotes and URLs on the candidate row, handed to the researcher as
  "already established" at launch; not displayed in R4.

Research status reads "Not started". Every discovered account is shown, Low fit included. The
human filters and sorts with the existing panel, ticks rows, and uses the existing **"Add to
project"** bulk action — that write is the approval (`project_account`, `added_via =
'discovered'`); R4 stamps the candidate row `decision = approved`, `decided_by`, `decided_at`.

**Unapproved is not rejected** (ruling 1, rev 5): a candidate left unapproved keeps no "rejected"
label anywhere; it is recorded as not chosen that time, and later runs for the same project do not
re-surface it. Whether the future target-accounts tab reads candidate rows or a pending membership
is the founder's later design decision (ruling 6, rev 5); R4 writes nothing to the project until
approval.

## 6. Step four — launch and run

The approved accounts launch through the existing `launch_arv2_account_research` with
`account_entity_ids` = the cohort, from the project chat (v44 grants it) or the CLI. No research
button. **No per-run concurrency cap in R4** (ruling 3, rev 5): O6's per-process worker slots
stand; how workers are shared across job kinds is a scheduling discussion of its own, taken up
separately in a follow-up. The AI Ark spacing rule becoming a shared limiter rides with that
discussion.

**The discovery run itself** is a fleet job of its own kind, `arv2_discovery`, driven by a handler
next to the account research handler, because it takes minutes, spends money and must survive a
worker restart. Rows, one migration (hash id, reversible, ARV2 tables only; the old `discovery_*`
tables stay on Phase 6's DROP list):

- `arv2_discovery_run` — `workspace_id`, `project_id`, `brand_id`, the ICP pins
  (`icp_artifact_key`, `icp_artifact_sha256`, `icp_key`, `icp_version`), `requested_by_user_id`,
  `target_count`, `strict_count`, `relaxed_enabled`, `status` (seam-1 vocabulary), `webset_id`,
  `asked` / `found_strict` / `found_relaxed` / `analyzed` / `recall_estimate`, `receipt_json`,
  timestamps.
- `arv2_discovery_candidate` — `run_id`, `pass` (`strict` / `relaxed`), `domain` (verified,
  unique per run), `websets_url`, `name`, `provider_snapshot_json`, `verdicts_json`,
  `fit`, `disposition` (`pass` / `partial` / `unclear` / `duplicate_of_existing`), `decision`
  (`approved` / null) with `decided_by_user_id`, `decided_at`, `account_entity_id`.

Every provider response is saved raw before parsing, every call is on the provider ledger with its
cost, and the pre-spend estimate is raised before the wire as a recorded fact (Appendix A laws
1–2; never a gate).

## 7. Starting a discovery from the product

Today a discovery can be started from a script. Starting it from the project chat needs one new
Head-of-ABM tool, `launch_arv2_discovery@1` (project pin, the ICP pin resolved from the project,
`target_count`, `relaxed_enabled`), which is a **profile bump**: a new immutable profile version
(v45 = v44 plus the tool), the recipe allowlist entry, the authority-map row, and one short passage
in the interview skill that the founder reviews in chat before it is written — the same mechanics
O6 used for the research launches. **The bump lands in R4** (founder ruling 2026-09-10, §9 item
4′): profile v45, recipe allowlist, authority map and the skill passage are R4 tasks, and the exit
gate is walked from the project chat. No gate tool is needed while the accounts table is the
approval surface.

## 8. Acceptance (the exit gate, measured)

On the semarang stack, the Clue ICP: one discovery run with `target_count = 20`, strict then
relaxed, every candidate verified, the human approves on the accounts table, the launch fans out,
the cohort is researched and displayed. Recorded under `.context/arv2-r4-acceptance/`: asked /
found / analyzed / recall estimate; verdict precision on a hand-graded sample; the three guards'
hit counts; whether Probook and Zafran are surfaced; cost per approved account (recorded, not
capped); time to idle; the relaxed pass's contribution.

## 9. Rulings ledger

| # | Ruling | Taken |
|---|---|---|
| 1 | Clue ICP is the exit-gate target | 2026-09-10 |
| 2 | Accounts table is the approval surface; chat gate later, after the founder designs the in-project target-accounts tab beside Gallery | 2026-09-10 |
| 3 | No spend caps of any kind; ledger and pre-spend estimate only | 2026-09-10 |
| 4 | Ask 35 for a target of 20 while precision is measured; partial matches are medium-fit, shown with an honestly weaker signal | 2026-09-10 |
| 5 | Unclear candidates are shown; no approval UI before a preview | 2026-09-10 |
| — | **No frontend change in R4**; parity with the dummy frontend; suggestions to the polish backlog | 2026-09-10 (rev 3) |
| — | Overall fit and Fit score only; no custom variables, no notes column | 2026-09-10 (rev 4) |
| (a) | Overall fit vocabulary stays High / Medium / Low; unclear = Medium by score | 2026-09-10 |
| — | Hybrid PoC before the plan: run and evaluated; Websets finds, Answer verifies, the regex probe is dropped | 2026-09-10 |
| — | Relaxed pass: automatic when the strict pass is short **and** on request | 2026-09-10 |
| 1′ | Unapproved accounts are remembered per project and not re-surfaced; never labelled rejected; local dedupe always, Websets exclusion import once Exa confirms the cap | 2026-09-10 |
| 2′ | Paid plan in place; proceed with Websets | 2026-09-10 |
| 3′ | No per-run concurrency cap in R4; worker scheduling across job kinds is a separate follow-up discussion | 2026-09-10 |
| 4′ | The Head-of-ABM profile bump for `launch_arv2_discovery@1` lands **in R4** (profile v45, recipe, authority map, skill passage), not at O7 | 2026-09-10 |
| 5′ | Aggregator job sites count as hiring and intent evidence | 2026-09-10 |
| 6′ | What the target-accounts tab reads (candidates vs pending membership): founder decides later | deferred |
| 7′ | **A fit is global to the account.** A seller's ICPs vary little between projects, so a fit and band decided once (by discovery or a later scorer) is the account's fit everywhere: the accounts table and the account detail show the account's most recently scored fit whichever project scored it, membership or not. Supersedes the FI-2 §7 read rule (primary project's score only) on those two surfaces; per-project attribution stays on the detail's project sections. | 2026-09-11 |
| 8′ | **A discovered account belongs to the project that launched the discovery, by default** — pass, partial and unclear alike, from the moment it is verified, recorded as `added_via = 'discovered'` in the same transaction as its account row and claims. Adding the same account to any *other* project stays an explicit human action ("Add to project"). **Supersedes 6′**: the target-accounts tab reads the project's members; `not_chosen_before` no longer arises within one project (workspace dedupe by domain catches re-found accounts first). No backfill for the run before this ruling (the founder added those by hand). | 2026-09-11 |
| 9′ | **Accounts carry a mark-type logo, shown on the accounts list, the account detail and the contact profile.** Supersedes D0 ruling S2 ("no logo pipeline"). Measured PoC over the first Insight Health run (34 companies): Exa Websets' ``logoUrl`` is LinkedIn's company mark for 22/34, every one correct; site-hosted images were wrong about half the time (banners, photos). Rule: a LinkedIn mark is stored as ``core.logo_url`` and streamed by the platform's logo route; every other company gets Brandfetch's **Logo API** URL for its domain at display time (embed-only CDN, public client id, never fetched or stored) — **the Logo API only, never the Brand API**; ``type/icon`` (the mark), ``fallback/lettermark``. **The mark only** — never a wordmark, never a banner. | 2026-09-11 |
| 10′ | **The creator is the owner by default.** A discovered account's creator and owner are the human who launched the discovery; a richer ownership mechanism comes later. | 2026-09-11 |
