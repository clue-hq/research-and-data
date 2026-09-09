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
