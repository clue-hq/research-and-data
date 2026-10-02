# 2026-08-31 — Dry run 2 SUCCEEDED: first end-to-end campaign page on the rebuilt web lane

Outer run `run_a7475e4612875777addc19fa5f2b21ed` (succeeded), inner `run_f01d9b6a6e4942e8bc4ccb690bf22228`,
31.5 min wall, `completed_with_warnings`. Same CFO/billing-strategy-session brief as dry run 1.
Doc: "Billing strategy session landing page" in project prj_277077f2…, thread thr_fe938727….
Preceded by two failed attempts the same evening: run_62f2fee0 (crashed on the raw-lane
UnboundLocalError, fixed at `bca4f0973` together with the enclosing-section swap bug + a
tool-level regression test) and the original run_155e48c8 (Sessions drift, stopped by founder).

## What the machine did (all mechanisms proven live)

- Verbatim brief; deep role-by-role library survey with honest zeros (stats/logo/gradient).
- `assemble_cloned_sections`: 5-band keeper skeleton — nav, the CRASHED run's released raw
  hero variant frag_d44ad4a0 (the mint-first design paid off: the crash left a reusable
  released variant, and this run pinned it instead of re-deriving), navy proof, CTA, footer.
- Compositions all brief-anchored ("three finance pains in the brief's words", billing model
  tiles, 30-min session steps, customer results attributed to Atlassian/Intercom/Fox
  Sports/Figma from stripe.com/billing via live fetch_page). The "session" trigger word
  produced the strategy-session offer — NO Sessions-conference drift this time.
- Raw repair lane used TWICE live (CTA band frag_41fe88fa → frag_f11a0821; hero variant
  frag_d44ad4a0 → frag_ba162d26, a 3-deep lineage chain) — released and swapped in place,
  on the freshly fixed code path.
- Surgical compose-then-swap edits throughout; zero page wipes; ops rejections self-corrected.
- Behavioral review gate ran and passed: web_review_walked 6/6, 0 broken clones, 0 findings.
- Finalize was HONEST: disclosed the captured dead control, the 3-line hero wrap at 1440,
  and the CTA fallback (no booking URL supplied → stripe.com/contact/sales, asks founder
  for a Calendly link to swap in).

## Open findings for the next improvement queue (founder to sequence)

1. **plan.md never written — 2 consecutive runs.** Orchestrator briefs said "plan.md then
   page"; the author skipped it both times. Prompt-only compliance fails on grok-4.6.
   Candidate lever: materialize an empty plan.md TEMPLATE into every run workspace (the
   author prompt's "continue an existing plan" clause then latches onto a visible file);
   stronger: a structural nudge in assemble/compose tool results when plan.md is absent.
2. **Cross-run filesystem visibility (real, measured).** The virtual FS root is the SHARED
   `.deepagent-workspace` parent, so `ls /` lists every run; run_f01d9b6a's message log
   references 5 other run ids hundreds of times (336× run_c6f44853, 208× the crashed run…).
   Contamination channel + token sink. Fix: first-match-wins permission rules — ALLOW
   `/run_<own>/…`, DENY `/run_*/**` — in `_filesystem_permissions` (harness.py); shared
   skills/knowledge paths untouched. Small, unspecced, awaiting founder go.
3. **Live-fetch evidence ruling needed.** fetch_page of the seller's own site (stripe.com/
   billing) fed attributed facts — better than memory, outside the plan-anchor list
   (brief + library + assets). Founder to rule whether seller-site live fetches are
   legitimate evidence (my lean: yes) and the skills updated accordingly.
4. Minor QA from the render: verify the Atlassian/Intercom/Fox Sports/Figma attributions
   against the fetched page; the two disclosed residuals (dead control, hero wrap).

## Also this session (same evening)

- Dev-stack class fix `d87b6ca21`: up() always clears apps/frontend/.next (the single-route
  404 recurred twice in one day; symptom row added to DEV_STACK.md at `9c94d743f`).
- Four drift-era Sessions fragments demoted to draft pre-run (reversible; ids in
  `_memory/2026-08-30-dry-run-1-sessions-drift.md`).
- Item 4 (context) verdict: summarization+offload middleware already on ALL roles
  (170k-token trigger, keep-6, offload to /conversation_history/<thread>.md, overflow
  retry); no tune warranted without measurements; nothing committed (founder instruction).
