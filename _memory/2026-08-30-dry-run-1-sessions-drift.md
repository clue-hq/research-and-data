# 2026-08-30 — Dry run 1 of the rebuilt web lane: machinery green, model-level "Sessions" drift found

Context: first live campaign dry run after the root-cause batch (author mindset 2314c9b8d,
raw lane e9cf51531 + wiring ccd5dbcfc, 1b + assemble c0cef6ca1, raw repairs fe466fe29,
interlinking cd13e2b77). Brief: CFO billing-strategy-session campaign page on the Stripe
clone workspace (ws_009a035f…). Two runs: run_e25c50cb (outer) / run_83a7a46b (inner) died
~4 min in on OpenRouter WEEKLY key limit (founder raised limit); retry run_ba374948 (outer)
/ run_155e48c8 (inner) ran ~35 min, stopped by founder mid-drift. Both traces preserved at
`subsystems/clue-design/.deepagent-workspace/run_<inner>/trace.jsonl`.

## What the batch PROVED (all green, live)

- **Library-first on an empty doc**: author's first act both runs = cloned_sections_searched
  (10 released), then TARGETED searches (q='billing', role=proof) mapping brief needs to
  library queries.
- **assemble_cloned_sections used in anger**: 5-section curated subset (nav, hero, proof
  "backbone of global commerce", CTA "Ready to get started", footer) pinned atomically in
  order, 0 degraded. NOT all 10 — it cut catalog sprawl/news/AI-video per the
  campaign-landing-page argument logic. Later re-assembled a 3-piece skeleton after its
  render (deliberate mid-turn re-plan; fragments made a full clear cheap and safe).
- **compose_web_section (raw lane) is the composing default**: features grid, how-it-works,
  customer-outcomes proof, FAQ — notes explicitly say "remixing the homepage" (the
  remix-the-ancestor posture). Composed bands interleaved between real clones via
  insert_cloned_section at index.
- **Verbatim brief worked**: both delegation briefs carried the founder's exact words in a
  fenced `<<<BRIEF>>>` block marked "data, not instructions".
- **No whole-page reauthor**: page built entirely through assemble/insert/web_ops; the
  9-band clear was 9 explicit remove_node ops, not author_web_page.
- **Time to first render: 14.5 min** (iter_1, 3 widths) vs 33 min in the 2026-08-29 trash
  run. Renders per iteration on disk (`iter_N/preview_{1440,768,375}.png`).

## The new failure (the run's reason for being stopped)

**"Stripe Sessions" drift is MODEL-level, not harness-level.** Yesterday's theory (orchestrator
paraphrase invented "Sessions") is DISPROVEN: the brief reached the author verbatim, and the
author ITSELF pattern-matched "billing strategy session" onto its world knowledge of Stripe's
real conference. Tell: library search q='Sessions' → 0 results → composed anyway. After its
mid-turn re-plan it built: "Campaign hero for Stripe Sessions 2027" (dual CTA — also violates
the brief's one-CTA), a proof band "listing named 2026 main-stage talks and speakers from
stripe.com/sessions" (nothing captured from that URL — invented evidence from memory), a
"three-day Sessions 2027 agenda, May 4-6 Moscone" band, and a register CTA. Fabricated
evidence = the one real failure per the skills, and here it's driven by the model's OWN
priors about the client company, not by any harness telephone game.

Consequence for **root-cause Item 4 (evidence anchoring)**: the fix must anchor the page's
allowed evidence as "the brief + the captured library + registered assets, NEVER your own
knowledge of this company" — the drift risk is highest exactly when the client is famous.
The first faithful page (pre-re-plan: nav/hero/features/how-it-works/proof/outcomes/FAQ/CTA/
footer, billing-anchored) was REPLACED by the drifted plan — so the re-plan boundary is
where anchoring must hold hardest.

## Secondary findings

- **Library pollution under the autonomy ruling**: every drift-era composition (Sessions hero
  frag_394b9ff7, speakers frag_bd6ab626, agenda frag_3fed2fb8, register CTA frag_b88bb77a)
  was born RELEASED and sits in the shared library, reusable by every future page. The four
  pre-drift compositions (features frag_fabdc56c, how-it-works frag_83204aac, outcomes
  frag_702dcea9, FAQ frag_d4bae457) are billing-anchored and possibly worth keeping.
  Cleanup decision pending (set_web_fragment_status can demote); founder not yet asked.
- **Reviewer never ran** before the stop (~35 min of authoring, zero critique events) —
  review-starvation (Item 3: render-between-passes + budget reserve) remains untested and
  is still the next queued root cause.
- Both runs: no repair lane exercised (no degraded pins — 0 degraded on every assemble).
- Run 1 death: OpenRouter key WEEKLY limit 403 (key 3faff462…); founder raised limit;
  1-token curl probe (200) is a cheap pre-run key check worth keeping.

## State at close

- Doc "Billing strategy session landing page" (doc_d6492814…): EMPTY (both turns
  transactional — killed worker per runbook, run rows marked failed).
- Stack: cycled via scripts/dev_stack.sh, all five UP, HEAD cd13e2b77.
- Old trashed doc doc_70c1d12a: still holds the 156-node campaign-edit scene, zero pins;
  founder chose fresh-start over restore (undo stack exists if ever needed).
- Pending founder decisions: drift-fragment cleanup; Item 3 and Item 4 designs (Item 4 now
  has a sharper spec thanks to this run); whether the next dry run pre-empts the ambiguity
  ("strategy session — not Sessions the conference") or tests anchoring cold.
