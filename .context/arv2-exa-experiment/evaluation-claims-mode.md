# Exa deep-reasoning: claims mode vs report mode — the designed experiment (2026-09-08, run by API)

## What was run

Four `/search` calls with `type=deep-reasoning`, the exact R2 request bodies (system prompt = target lock +
evidence law; query = the agent's charter + probes + already-established block; 20 results; `contents.text`
10,000 chars), differing only in `outputSchema`:

- **report mode** (control, what the agent uses today): one required string property `report`.
- **claims mode**: `claims[]` of `{section, field, value, source_url, quote, claimed_by}`; the schema
  description asks for NOT FOUND items as rows too.

Each call cost $0.025 and returned 20 results. Latency: claims 27–29 s, report 48–69 s.

Files (this folder): `request-*.json` (bodies), `request-*.response.json` (raw responses),
`claims-{probook,zafran}.md` (every claims-mode row, readable), `report-*-today.md` (today's reports),
`response-*-report-mode.md` (the R2 run's reports, same request, for run-to-run noise).

## How it was measured

1. **Quote fidelity against what Exa read** — every quoted span checked verbatim (whitespace/quote-mark
   normalised, elision-aware) against the `results[].text` returned in the *same* response. This is the
   cleanest measure: it does not depend on whether a page serves to a plain fetch. For claims mode, the quote
   is checked against its own `source_url`'s text.
2. **Quote fidelity against the live page** — same check against a fresh fetch of the cited URL. Lower bound
   for both modes (LinkedIn, GlobeNewswire and Ashby JS boards do not serve), reported for completeness.
3. **Does the quote support the whole value?** — read by hand, per claims-mode row: full / partial / unrelated.
   This is the faithfulness question the claim store cares about (a value beyond its evidence span cannot be
   promoted).
4. **Facts found** — answer-key leaf values present in the output text (same grader as the recall script's
   leaf matching, substring level).
5. **Negative-space discipline** — explicit NOT FOUND markers, and section-6 tools marked NOT FOUND
   individually.
6. **Assertion count and URL-per-assertion** — how many cited assertions the output carries and whether each
   has its own URL.

## Results

| | Probook report (R2 run) | Probook report (today) | **Probook claims** | Zafran report (R2 run) | Zafran report (today) | **Zafran claims** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cited assertions / rows | 58 | 62 | **17** | 56 | 64 | **20** |
| quote verbatim in Exa's own retrieved text | 86% | 69% | **94% (16/17)** | 73% | 56% | **95% (19/20)** |
| quote verbatim on live page (lower bound) | 62% | 34% | 67% | 55% | 52% | 72% |
| distinct URLs | 23 | 21 | 9 | 21 | 24 | 12 |
| URL on every assertion | yes (inline) | yes | yes (row + grounding) | yes | yes | yes |
| NOT FOUND markers | 35 | 21 | 0 rows (10 embedded in prose values) | 29 | 21 | 0 rows (7 embedded) |
| section-6 tools individually NOT FOUND | 14/14 | 4/14 | 0 (all 14 in one row) | — | — | — |
| answer-key leaf values present | 11/22 | 10/22 | 10/22 | 18/64 | 17/64 | 12/64 |
| quote supports the whole value (hand-read) | n/a | n/a | 6 full / 7 partial / 4 unrelated | n/a | n/a | 13 full / 4 partial / 3 unrelated |

Run-to-run noise on report mode is real: the same request twice moved verbatim-in-retrieved-text by 17 points
and NOT FOUND markers by 14 (Probook). Claims mode's advantage on quote fidelity (94–95%) is outside that
band; its deficit on assertion count (3×) and on Zafran facts found is too.

## What claims mode does well

- **The quote is almost always a real span from the cited page.** 35 of 37 rows verbatim in the text Exa
  retrieved; the two misses are a LinkedIn post (login wall in Exa's own fetch) and a homepage span the
  homepage no longer carries. This is the property our structuring pass loses most often, and it is what the
  link audit measures.
- **The cited URL is always one of the 20 retrieved results** (37/37) and the grounding repeats it per row.
- **The hard sections come out right.** Zafran's Cisco item is DENIED with the Globes quote from the CEO;
  Snir Havdala's departure is CONFIRMED with the company's own words; the ARR claim is "more than tripled"
  with the absolute figure marked NOT FOUND; the LinkedIn headcount is `claimed_by: estimate`.
- **Faster and no cheaper**: same $0.025, roughly half the latency.

## Where it fails for our pipeline

1. **A row is a paragraph, not a claim.** Values pack several facts and the quote supports only one of them.
   Probook `named_customers_and_traction` lists seven customers on a quote that says "hundreds of locations";
   `internal_gtm_tools` marks fourteen tools NOT FOUND on the quote "You know your numbers cold";
   `negatives_and_corporate_events` declares layoffs, lawsuits, churn and down-rounds NOT FOUND on a quote
   from the funding announcement. Only 19 of 37 values are fully covered by their quote. To load these into
   the claim store we would still need the structuring pass to split them — which is the step the experiment
   was meant to remove.
2. **It writes facts the quote does not carry, and gets one wrong.** Zafran `leadership_and_board` gives Nick
   Fisher "VP Business Operations" and Hadas Bergman "VP HR"; the About page says Nick Fisher VP Marketing,
   Hadas Bergman VP Business Operations, Racheli Barouch-Haik VP HR & Operations (verified live). The quote
   covers only the two founders, so the audit would pass the quote and the error would ship. Report mode (R2
   run) had all nine titles right, each cited. Probook `named_customers` again folds "Cardinal/Redwood
   Services" and "TurnPoint-related operations" together without evidence.
3. **Three times fewer assertions, and the negative space collapsed.** Zero NOT FOUND rows in either account
   despite the schema asking for them; the NOT FOUND statements are sentences inside positive rows. Section-6
   per-tool and section-11 per-item claims — the ones born `outreach_safe=false` — would have to be
   re-derived. The proof-of-concept's observation holds: a multi-property schema makes the model spend its
   budget on shape rather than coverage.
4. **Fewer sources.** 9 and 12 distinct URLs against 21–24 in report mode; Zafran's answer-key coverage drops
   from 17–18 to 12.

## Verdict

Keep report mode as the deep call's output. Claims mode buys quote fidelity (94–95% verbatim vs 56–86%) at
the price of a third of the assertions, half the sources, the loss of per-item NOT FOUND, and values that
outrun their evidence — including one factual error the audit could not catch. Since the rows still need
splitting, it does not remove the structuring pass; it only starves it.

What the experiment does argue for, inside report mode:

- **Ask the report for a quote-first shape without asking for rows**: keep the single `report` string but
  instruct "one sentence per assertion, quote first, then the URL". Cheap to try (prompt only), keeps the
  budget on coverage, and gives the structuring pass cleaner input.
- **Use `deep-reasoning` claims mode for narrow probes**, not the dossier: a 3–5 row schema for one question
  (the ABM Manager's status; the Cisco item) where the quote fidelity is worth the thinness. The agent already
  has probes; this would be a second, cheaper deep tool, if wanted.
- **Do not change the R3 person tool's default** on this evidence; person dossiers are quote-heavy and
  the same collapse of assertion count would hit them harder.
