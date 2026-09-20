# Reproducibility, quality and rollout gates

The goal of a later implementation is comparable usefulness from an automated Exa-led run, not a textual match to the Conduit reference. This handoff itself is accepted by artifact coverage and fidelity; production readiness requires the separate live evidence below. No live evaluation has been run for the proposed prompts.

## Freeze before paying for another run

Record company identity, selected product scope, prompt/schema versions, provider efforts/models, allowed sources, task budgets, retry policy, source window and output destination. Save exact request material securely, redacting credentials only, so it can be replayed. A reference snapshot or expected answer must never enter the held-out candidate's input context.

Keep localhost:3046 and its files unchanged. Use a new evaluation run ID/directory for every candidate. Compare these three conditions from the same selected scope: existing platform baseline; proposed Exa-led pipeline with Python formatting; supervised Conduit reference for rubric calibration only. Baseline runs are real cost; avoid multiplying runs until one canary establishes schema/identity correctness.

## Representative evaluation companies

Use Conduit plus at least three independently selected companies: a sparse-public-information single-product brand, a multiple-product enterprise vendor, and a business with a different buying model (for example services or regulated software). Prior Clue/AWS/Google workspaces can supply candidates, but do not treat preloaded answers as new research. Evaluate bounded selected portfolios honestly; “all companies” is an architectural target, not proof from four samples.

## Hard failures

- Wrong company, product, buyer entity or advertiser attribution.
- Invented price, threshold, numeric result, certification, partnership, quote or source.
- Projected outcome presented as achieved; bundle price presented as a standalone price; one product assigned another's result without support.
- Unsupported exclusion or missing-data automatic rejection; unapproved policy presented as confirmed ICP.
- Citation stripped or attached to the wrong assertion; meaningful text changed by the parser.
- Tenant/project leak, overwritten owner edit, duplicate publication, hidden partial research, uncontrolled retry or budget overrun.
- Codex/manual factual editing or hand-picked answer passages required to make the candidate pass. Such a run is marked supervised and cannot establish automation success.

## Rubric: human and operational usefulness

Score 0–4 per category: 0 absent/wrong, 1 surface-level or materially misleading, 2 useful fragments needing major repair, 3 useful with minor edits, 4 ready for the intended sales task subject to owner approval. Record reviewer and concrete evidence, not only a mean.

| Category | Required demonstration |
| --- | --- |
| Company understanding | Explain business, workflow context, customer types, commercial model and material unknowns |
| Product coverage | Every selected product has purpose, users, workflow, capabilities/limits, integration path, packaging, differentiation and scoped proof—or a named evidence gap |
| Brand/message usefulness | Observed voice has examples; message map links situation/problem/value/proof/next action; proposed copy avoids false account knowledge |
| ICP decisions | Distinguish good-fit/unknown/poor-fit scenarios, buying unit, evidence tests, readiness/timing and owner-policy choices |
| Personas/jobs | Role, remit, work, desired measure, objection, proof and next question are concrete and responsibly sourced |
| Evidence accuracy | Material claims are checked against original passages for full scope; unresolved contradictions remain visible |
| Readability/retrieval | Humans see clean titles/tables; agents retrieve the correct versioned document; creative asset usage context stays on assets |

Initial release candidate: zero hard failures; all categories at least 3 per evaluated company; no manual repair; all material assertions checked; all selected product outcomes accounted for. These are proposed acceptance thresholds requiring owner agreement, not scores already achieved. Do not conceal a failed company behind an aggregate average.

## Concrete regression cases

1. One supported buyer motion → one profile, not two mandatory filler profiles.
2. No supported buyer motion → explicit provisional/insufficient result and specific owner questions; no invented ICP.
3. Same-name unrelated companies → target locked; ambiguous identity halts attribution.
4. Two similarly named products, one coming soon → separate IDs/scopes and conflict, not merged features.
5. Detailed product task delayed/failed → dependent ICP waits or records explicit provisional scope; never silently reads a missing file.
6. FAQ answer lies beyond first text chunk → retrieve complete relevant section; no false “unpublished.”
7. Private/demo-only pricing → unknown price and quote question, no inferred zero/ACV.
8. Monthly/annual toggle or two voice meters → retain cadence/path/source; no arbitrary reconciliation.
9. Customer story title differs from operating entity; savings are expected → correct subject and projected status throughout product/ICP/messaging.
10. Unknown connector/timing → research action; positive fit remains distinct. Unsupported stack requirement cannot become a hard gate in the adapter.
11. Product changes while persona job is running → pinned old version remains reproducible; new task proposes updated output, never mixed versions.
12. Owner edits a document mid-run → preserve owner version, propose a conflict/diff; no overwrite.
13. Injection in source page → no scope/tool/approval change.
14. Formatting repair changes a negation, currency, unit or source link → reject repair.
15. Large product catalog → selected scope and continuation are explicit; no “complete” status from one bounded search.
16. No 20 eligible ads or missing transparent logo → honest shortfall; no generated substitute; documents still have no creative-usage panel.

## Measurement and rollout

Measure time-to-usable identity, company document, selected-product readiness, ICP and complete library separately. Record attempted/completed/empty/failed calls, cached versus fresh work, Exa charges, reconciliation/parser/reviewer tokens and cost, uncertain reservations, retries and human interventions. Source/ad-provider charges without receipts remain unpriced. The earlier supervised spend is not a production per-brand estimate.

After offline contract tests, run one separately authorized bounded Exa canary to confirm schema behavior. Then one fresh Conduit run without reference contamination; review gaps; revise generic prompts, not answers. Repeat on held-out companies. Only after human acceptance integrate incrementally through reviewed backend/frontend contracts. Validate refresh, isolation, protected edits, retrieval and separate asset handling before widening rollout. A prompt pack alone does not prove quality or scalability.
