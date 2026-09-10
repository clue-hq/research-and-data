# ARV2 R4 — Exa Websets vs `/search` discovery experiment (2026-09-10)

**Why.** Before writing the R4 substance document, the founder asked for a like-for-like test:
the v3 proof of concept's ICP (`.context/arv2-clue-sample-v3/BRIEF.md`, Series A-only US vertical
SMB SaaS, hiring GTM, intent) discovered by the v3 `/search` queries and by Exa Websets, discovery
only (no Websets enrichment — AI Ark owns enrichment), graded by Fable. The key turned out to be
Websets-entitled (the 2026-08 M06A 401 was a plan gate at the time).

**Where.** `.context/arv2-websets-experiment/` — `README.md`, standalone scripts
(`run_search_baseline.py`, `run_websets.py`, `summarise.py`, `exa_common.py`), `raw/`, `ledger.json`,
`summary.md`, **`evaluation.md`** (the grading, per company).

**Result, one line each.**
- `/search` (3 v3 queries, $0.021, 6 s): 4 companies, 2 strict passes (Lassie, Probook); queries 2–3
  return job boards and advice, exactly as the proof of concept found.
- Webset W3 (3 verifiable criteria, count 25, ~5 min, 250 credits ≈ $1.12 Pro): 25 companies, **14
  strict passes**, 4 unclear, 7 fails — 2 from my loose criterion wording (admitted Series B), **5
  Websets errors** (a pre-seed called Series A, Bengaluru called US, a 2024 round dated 2026, an
  unattributed round labelled A, one entity conflation).
- Webset W5 (all 5 gates as criteria): 1 company in ~8 min after 334 analyzed; hiring 3.7% and
  intent 2.7% success rates starve it.
- Cost per strict-qualified company: search ≈ $0.011 (≈ $0.035 with the hand verification the v3
  agent did); Websets ≈ $0.093 at Pro incl. our $0.007/company stage probe. Plan fee on top (Core
  $49/mo, Pro $449/mo). The API exposes no credit counter.

**Decision material for the R4 substance doc.** Websets as the candidate source (three criteria
written as "most recent round is …", over-discover), our own qualifier probe grades stage/hiring/
geography with references, human approves; `/search` kept for the domain lock; a thin client next
to `exa_client.py`, never the old M06A pipeline (Phase 6 inventory: DROP). Plan tier is a
procurement ruling.

## Hybrid PoC (same day, founder-requested before the plan)

`.context/arv2-websets-experiment/hybrid/` — one webset (3 criteria, "most recent round" wording,
35 asked) → **15 found of 333 analyzed** (Exa hit its search limit), 150 credits, 7 min; then our
probe graded all 15 in ~100 s for $0.105. Websets' stage verdict was wrong 6/15 even with the right
wording (pre-seed/seed ×5, Series B ×1); the probe caught every one. Full passes: Boostly, and
Probook once its real URL is used — **Websets returned `probook.com` instead of `probook.ai`**, so
R4 must verify the company URL before dedupe and reads. Free ATS boards covered 4/15; a regex
careers-page fallback produced false positives (marketing copy, a GTM tag-manager id) and was
replaced by unclear + reference. Stage rules that now hold: announcements decide the date, majority
vote within it (title ×3), profile pages only as a fallback. Evaluation:
`hybrid/hybrid_evaluation.md`.

## Exa Answer as the verifier + the settled approach (2026-09-10, later the same day)

- `answer/`: 18 companies × 4 gates through `POST /answer` (system prompt + `outputSchema`, the
  gate's rule/test verbatim as the question): **24/26 agreement** with hand-checked truth, $0.005 and
  ~2.3 s per call, quote found verbatim on the cited page 69/72. Error kinds: date arithmetic
  (Superorder), same-name company on another domain (INFI→infinIT), absence read as fail. The same
  72 through `/search` + schema: $0.007, 3.7 s, misread "Series A or extension" on 9/18 → Answer is
  the verifier; search keeps the domain lock. The Exa account hit its credit limit once (topped up).
- **Approach settled in discussion and written as rev 5 of the substance document**
  (`docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md`): Websets long list from the
  ICP's wording → Answer verifies every gate with quote/URL/date + three code guards (quote on page,
  right domain, date arithmetic) → strict pass then relaxed pass (auto when short, and on request)
  → Overall fit / Fit score on the existing accounts table, no frontend change → approval = "Add to
  project". Rulings: unapproved ≠ rejected (remembered per project); paid plan in place; no per-run
  cap in R4 (scheduling is a separate discussion); aggregators count for hiring/intent; the
  target-accounts tab's reading deferred; the Head-of-ABM profile bump (R4 vs O7) still open.
