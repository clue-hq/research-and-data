# Website runs — defect register (2026-10-06)

Work queue for website quality, built from the three website runs of 2026-10-05/06 on the trenton
lane. Every item was checked against the run's own records (final report, self-review evidence,
saved conversation in `checkpoint_writes`, preview screenshots at 1440/768/375). We work through it
one item at a time; update the **Status** line as items close.

## The runs

| Run | Workspace / account | Design run | Session (checkpoint thread) | Outcome |
|---|---|---|---|---|
| 1 | Conduit AI / Dana.AI | `run_406fe808b26f5c1ca0cfe709bfae9f65` | `dsess_63bb6a6bbc0953769baffa2120b649e4` | completed_with_warnings, 29 steps, 1 preview round |
| 2 | Garner Health / Syracuse City School District | `run_53540c7d0758579fa0d712c9104de81c` | `dsess_b5f568ded78d5224abafd1d836c670f0` | completed_with_warnings, 34 model calls, 4 rounds, $7.71 |
| 3 | Garner Health / Syracuse City School District (context clearing on) | `run_d71298e8df7c54c79631623b9f460ce4` | `dsess_0ad05176137b545cb1452bde7d7d680a` | completed_with_warnings, 38 model calls, 3 rounds, $4.14 |

Run files: `subsystems/clue-design/.deepagent-workspace/sessions/<session>/turns/<run>/` (`final.json`,
`iter_*/preview_*.png`, `trace.jsonl`, `logs/run.jsonl`). Plans: `…/sessions/<session>/workspace/plan.md`.

## A. Problems on the finished pages

### A1. Strategy notes written as visitor copy — Run 1 — OPEN
- On the page: "That is the write-back surface this page is about." and a column "This conversation:
  Overlap, split, or referral … decide whether coexistence, a geographic split, or a referral into
  hotels is the useful next step."
- Cause: Head of ABM's angle ("overlap, coexistence, a geographic split, or a referral motion") sat in
  the brief's "For the page" half (see D1); the copy rules stopped disclaimer sentences but not
  strategy/meta language; self-review did not catch it.
- Status: open.

### A2. Proof copy reads like source notes — Run 1 — OPEN
- "Mayra, Global Head of Customer Experience, is named on that story." / "Conduit lists The Flex as a
  hospitality operator using the platform…". The plan said The Flex line would be rewritten; it shipped.
- Status: open.

### A3. Section index labels repeat — Run 1 — OPEN
- "[01] OVERLAP", "[01] PRODUCT", "[02] AGENTS", "[02] PROOF": composed sections restart the source
  sections' numbering.
- Status: open.

### A4. Empty product band on mobile — Run 1 — OPEN
- At 375px the Inbox stage shows only the aurora gradient; the product UI is cropped out. The agent
  noticed ("at 375 the Inbox stage is the source aurora crop") and shipped it as a warning.
- Status: open.

### A5. Large empty gaps between sections on desktop — Run 1 — OPEN
- After the "two sides of the desk" band and after the proof band (iteration 1 preview, 1440).
- Status: open.

### A6. Hero headline widow — Run 2 — OPEN
- "Keep this network. See claims quality." breaks with "quality." alone; the cloned hero slot cannot
  restore the source `<br>`. Run 3 avoided it only by choosing a different headline.
- Status: open.

### A7. Composed sections left-aligned against centered source sections — Run 2 — OPEN
- Agent flagged it and did not fix it.
- Status: open.

### A8. Type does not match the brand — all runs — OPEN
- Every run ends `typography_references: mismatch` and "coverage incomplete": composed sections use a
  different fallback stack, sizes such as 36px vs the source's 32/48px, and font synthesis (Run 3).
- This is roadmap item A5 (page-wide type theme).
- Status: open.

### A9. No account logo — Runs 2 and 3 — OPEN (partly external)
- `fetch_logo` failed: `syracusecityschools.com` / `www.` / `scsd.us` do not resolve (checked
  2026-10-06 with the system resolver; other sites resolve). Research read the site earlier, so likely
  an outage on their side. The logo ladder has no fallback once the official site is unreachable; the
  agent correctly left the slot empty.
- Status: open.

### A10. Softened caveat in visitor copy — Run 3 — OPEN (minor)
- "…incentive design is confirmed during review." derives from the brief note that HRA/HSA incentive
  design is not cleared. Same pattern as A1, milder.
- Status: open.

## B. The agent's own checking

### B1. Self-review never completes — all runs — OPEN
- `review_evidence.status = incomplete`, `quality_verdict = not_computed` in all three. Each finished
  with unseen parts of its final render (`review.unseen_pixels`): Run 1 tablet tiles; Run 2 tablet and
  mobile tiles; Run 3 tiles at all three widths after its last render.
- Status: open.

### B2. No comparison against the real site — all runs — OPEN
- `clone_review.comparison = unavailable` because the source was captured at 1920px and the page is
  rendered at 1440px (`reference_viewport_mismatch`). Clone fidelity is never compared. Roadmap A6
  (capture) territory.
- Status: open.

### B3. Run 1 rendered once and fixed nothing after review — OPEN
- Built → one `render_web_preview` (step 18) → views, typography reads, `review_cloned_page` →
  finalize (step 28) with no further edits. A1–A5 shipped as a result. Runs 2 and 3 rendered 4 and 3 times.
- Status: open.

## C. Tool defects

### C1. Button relabel fails on Webflow buttons — Runs 2 and 3 — OPEN
- `repair_cloned_section` with `cta_label_replacements_json {"Request a demo": "Request the analysis"}`
  on `frag_95041c54da629d99` → `repair.label_unmatched` ("every old label must match an anchor's
  visible text"). Garner's markup puts the visible label in a `<div>` inside a `<button>` with an empty
  overlay `<a aria-label=…>`; the tool only matches an anchor's own text. The agent's guess was right.
  It recovered via `text_edits_json`, losing a step in both runs.
- Status: open (tool fix).

### C2. Repeated section inspections — all runs — NOTED (not caused by clearing)
- Runs 2 and 3 both re-inspected the same four sections at step 12, identical with and without
  context clearing (plan at step 9, first build at step 10 in both). Looks like the normal workflow
  (exact node paths needed before edits). Run 3 also inspected `frag_9a8550d2f42f1196` three times.
- Status: noted; revisit only if it grows.

### C3. Recurring minor warnings — all runs — OPEN (minor)
- `w-full` class collision on campaign header/footer; brand kits lack a shadow definition
  (`LUMW0305`, default used); Run 3: hero video playback "not proven beyond static frames".
- Status: open, low priority.

## D. Brief and handoff (Head of ABM)

### D1. Caveats and strategy in the brief's page half — Runs 1 and 2 — OPEN
- The two-part brief works, but "For the page" still carried items like "Vendor case study, not
  independent causal proof" and (Run 1) the strategy angle that leaked as A1.
- Status: open (manual-siblings / brief rule, plus the design agent's check for meta language).

### D2. "Queued is not finished" said to the user — OPEN (Claude's bug)
- Head of ABM repeated this line from the `open_design_leg@5` description into chat
  (`platform/api/clue_api/design_leg_tools.py`, manual v18). Promised fix not yet made.
- Status: open.

### D3. Run 1 angle — FOUNDER DECISION
- Head of ABM framed Dana.AI as a peer vendor (overlap / coexistence / referral) because research
  shows it sells hotel software. Whether to pitch a near-competitor this way is a product call.
- Status: awaiting founder.

## E. Platform

### E1. Preview images and fonts missing in the app — OPEN (awaiting founder choice)
- The editor preview is a sandboxed `srcdoc` iframe (opaque origin). Chromium 152 Local Network Access
  blocks it from loading any local address (`127.0.0.1:8019` asset store, even `localhost:3029`);
  public CDNs load. Proven in the in-app browser: only `allow-same-origin` loads them.
- Options: (1, recommended) serve the preview from the separate page origin (port 8040) so it has its
  own real origin; (2) add `allow-same-origin` (unsafe: agent HTML would run as the app); (3) inline
  assets into the preview HTML (heavy).
- Status: open.

### E2. A new page request in a thread with an open design session continues the old page — OPEN
- The message goes to the open leg; on 2026-10-06 21:30 the exit judge failed
  (`design_leg.exit_judge_failed` → fail-safe continue) and the run resumed the previous session's
  whole conversation (`turn.checkpoint_continue`). The founder had to stop it and start a new chat.
- Status: open (UX; ties to the known exit-judge timeout).

### E3. OpenRouter key intermittently rejected — OPEN (external)
- `401 User not found` at 19:56 UTC (2026-10-05) and ~21:30 UTC, accepted again in between; turns
  failed with "API key rejected".
- Status: open, outside the code.

### E4. Logged out / stuck on "Preparing sign-in…" — FIXED
- Merged into this branch via PR #106 and #100.

## F. Cost

### F1. Context growth drove cost — FIXED
- Run 2: $7.71, calls up to 318k tokens; grok-4.6 per-call cost appears to roughly double above
  ~200k prompt tokens (inferred from usage). Context clearing (plan
  `2026-10-06-web-agent-context-clearing.md`) brought Run 3 to $4.14 with a 222k peak.

### F2. Research-read bugs (overview crash, cut-off contact pages, blank titles) — FIXED
- Commit `3e866e244`, before these runs.

## Suggested order

1. A1 + D1 + B1 together (strategy notes leaking, plus a self-review that never finishes).
2. A8 (type theme, roadmap A5).
3. B2 (capture viewport / comparison, roadmap A6).
4. E1 (preview loading in the app).
5. Quick wins any time: C1 (relabel tool), D2 ("Queued is not finished").
