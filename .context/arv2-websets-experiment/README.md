# Exa Websets vs Exa `/search` for account discovery — experiment (2026-09-10)

**Question.** For the same ICP input the v3 proof of concept used
(`.context/arv2-clue-sample-v3/BRIEF.md`, founder ruling 1: Series A / A-extension raised within
~24 months, US B2B vertical SaaS/AI selling into a fragmented SMB vertical, actively hiring GTM,
showing buying-intent signals), does Exa Websets discover a better cohort than the three `/search`
queries in `.context/arv2-clue-sample-v3/step1_discovery.py`, and at what true cost?

**Scope.** Discovery only. No Websets enrichments (enrichment is AI Ark's job). No person searches.

**Arms.**

| Arm | Mechanism | Input | Spend |
|---|---|---|---|
| S | `/search`, the v3 script's three queries verbatim, `type=auto`, 10 results, text 3000 chars, published after 2025-06-01 | same as v3 | $0.007 × 3 |
| W5 | Webset, `entity.type=company`, `count=25`, the ICP as the query, **five** criteria = the ICP's four hard gates + the vertical | same ICP | ≤ 250 credits |
| W3 | Webset, same query, `count=25`, **three** criteria = only the gates verifiable from public pages (US HQ, Series A ≤ 24 months, sells to a fragmented SMB vertical); hiring and intent left to our own probe, which is R4's design | same ICP | ≤ 250 credits |

**Setup.**

```
set -a; source .env; set +a           # CLUE_EXA_API_KEY
uv run python .context/arv2-websets-experiment/run_search_baseline.py
uv run python .context/arv2-websets-experiment/run_websets.py            # creates W5 and W3, polls to idle
uv run python .context/arv2-websets-experiment/summarise.py              # tables for the evaluation
```

Raw responses land in `raw/`, one file per call; `ledger.json` records every call with its
cost (Exa `costDollars.total` for search; credits for websets = 10 × all-green results, priced at
the plan's per-credit rate).

**Evaluation** is `evaluation.md`, written by the reviewer (Fable) after grading every distinct
company from each arm against the ICP's hard gates with the same evidence standard the proof of
concept used (an announcement for stage, the ATS board for hiring, the company's own site for
geography and vertical).
