# Standalone Brand Context Agent V1 — Conduit pilot

Status: **standalone pilot delivered for human review; not integrated into Clue**. The draft required supervised corrections and is not approved for automatic governance. See [RESULTS.md](RESULTS.md).

## Open the result

**Latest revision:** [Conduit rework](http://localhost:3046/#knowledge/company-overview) — see [RESULTS_V2.md](RESULTS_V2.md). The original pilot below is preserved for comparison.

Restart the revised preview from the repository root:

```sh
.venv/bin/python experiments/brand-context-agent-v1/server.py --run conduit-rework-20260919 --port 3046
```


The review is running at **http://localhost:3045/** with Knowledge, Assets and Run & evaluation views. If the local server stops, run from the repository root:

```sh
.venv/bin/python experiments/brand-context-agent-v1/server.py --port 3045
```

The server binds to loopback only. Runtime outputs, originals, source records, revised documents and reports are in `runs/conduit-20260919/`, excluded from git but retained locally. Serve only its `public/` directory. Do not serve the run root or share private model/provider caches.

## Reproduce or inspect

The existing repository Python environment supplied httpx, beautifulsoup4, Pillow, python-dotenv, markdown-it-py, playwright and psycopg. No dependency or browser installation was performed. `requirements.txt` records the versions used. Psycopg is only needed for the optional read-only baseline utility. The core experiment does not use a database.

From this experiment directory:

```sh
../../.venv/bin/python -m unittest discover -q
../../.venv/bin/python verify.py
../../.venv/bin/python pipeline.py build
```

Research stages are explicit and cached. Re-running them may spend provider credits on missing work, so inspect the run first:

```sh
../../.venv/bin/python agent.py research --env ../../.env
../../.venv/bin/python pipeline.py acquire --env ../../.env
../../.venv/bin/python pipeline.py classify --env ../../.env
../../.venv/bin/python pipeline.py knowledge --env ../../.env
../../.venv/bin/python pipeline.py retrieval --env ../../.env
../../.venv/bin/python report.py
../../.venv/bin/python pipeline.py build
```

This pilot is Conduit-specific. `revisions.py` and `visual_review.py` record supervised adjudications of this run, not general model improvements. `ad_details.py` resolves sponsored-post authors using original advertiser evidence. Five public browser captures were supplied during this supervised evaluation; they are recorded as such, not presented as autonomous HTTP retrieval. Do not claim unattended repeatability from this one run.

## Accepted brief

Build a real, resumable research agent starting only from https://conduit.ai/. Deliver nine concise knowledge documents and one unified, searchable Assets collection covering original logos, website imagery and published LinkedIn ads. Evidence, uncertainty, useful ICP decisions and practical design guidance matter more than document volume. Stop at human review before any integration.

The approved full brief is in `/Users/shashank/.codex/attachments/57a7c0c4-c602-48ac-9937-ce2b26048613/pasted-text-1.txt`.

## Isolation

All experiment code and outputs live here. No Clue imports, database writes, environment changes, service restarts or brand-library mutations. Credentials are read by explicit path from the existing private environment file at runtime and never written here. Original assets and provider responses remain local, excluded from git. The viewer serves only a generated public review directory, never credentials, logs or raw provider responses.

## Execution plan

1. Test and implement isolated storage, evidence validation, network boundaries, caching and spend accounting.
2. Implement Exa search/retrieval and OpenRouter tool-calling; preserve the agent's decisions, tool results and resumable conversation.
3. Research identity and products first, then customer evidence, alternatives, jobs and qualification gaps; let the agent choose follow-up investigations.
4. Acquire official website assets and logos plus a bounded Adyntel harvest; verify advertiser identity independently and retain raw format/provenance.
5. Analyse asset previews, linking observed content separately from inferred usage. Synthesize evidence-linked documents after research.
6. Build the Knowledge and Assets viewer and a retrieval evaluation with representative campaign briefs.
7. Independently review consequential claims and ICP criteria; compare the existing onboarding snapshot only as a segregated baseline. Fix important findings and record remaining gaps.
8. Verify output integrity, rendered views, search/filter/detail interactions, isolation, cost accounting and every brief requirement. Deliver for human review.

## Research and spending bounds

Initial run: at most 24 Exa searches, 50 retrieved research pages, 6 Adyntel pages across explicitly recorded windows, 1 Brandfetch brand request, 50 agent/review model calls and 40 inspected asset previews. Start the ad window at the previous 90 days, ending yesterday; expand to 180 days only when useful and record it. Target 15–20 unique relevant ads, not a guaranteed inventory.

Model and Exa charges have a $10 initial conservative reservation ceiling. Model estimates use provider-published token prices before dispatch; actual usage replaces reservations when returned. Uncertain calls retain their reservation and are not automatically retried. Adyntel credits and Brandfetch request counts are tracked separately when dollar billing is unavailable. Never call an unknown total a full dollar total. Reaching a limit yields a checkpoint and a quality/coverage decision, not invented evidence or silent extra spend.

## Evaluation rubric, fixed before research

Hard failures: wrong company/product/advertiser; unsupported material factual assertion presented as established; fabricated metrics/pricing/logo; cross-workspace mutation; missing source lineage; invented ads to meet a quota.

Human review dimensions (0–4 each): identity/evidence accuracy, product understanding, ICP decision usefulness, buyer/outcome specificity, honest uncertainty, asset fidelity and usage guidance, retrieval relevance, document clarity. A score of 3 means useful with minor edits; 4 means campaign-ready subject to human approval. Scores are evaluation judgments, not factual confidence probabilities. Independent findings and unresolved exceptions accompany scores.

Required evidence: source-passage checks; fact/hypothesis/decision labels; fit versus readiness versus urgency distinctions; testable qualification and exclusions; original asset hashes; ad coverage/drop reasons; several representative retrieval cases; table rendering and viewer interaction checks; measured run cost/time/retries; baseline kept out of research context.

## Knowledge outputs

Company overview; Products & capabilities; Customer jobs & outcomes; Ideal customers; Buyer roles & priorities; Buying triggers & qualification; Alternatives & differentiation; Customer evidence; Brand & messaging.

Each document has a stable internal key, a friendly display title, concise body/tables, linked evidence, uncertainty and revision information. Facts belong to evidence records; hypotheses retain their basis without becoming facts; strategic recommendations remain unapproved. Assets link to product/use-case evidence where available. Publicly published ad claims are attributed to the advertiser, not treated as independently proven results.

## Progress ledger

- 2026-09-19: Read approved brief; verified clean feature worktree at `15c32b26`. Confirmed existing Exa, OpenRouter, Adyntel and Brandfetch credentials are configured without printing secrets. Initial experiment specification and rubric established before company research. Existing platform is untouched.
- Ruling: use the already isolated worktree and a self-contained experiment directory; no additional worktree or platform integration is needed. Experiment bookkeeping stays here to preserve the requested isolation.
- Research completed from fresh evidence after 24 model turns: 49 source records and 41 accepted candidate claims. First attempts exposed an underspecified claim tool schema; rejected submissions stayed out of the claim store. Added explicit nested schema, defensive validation and dependent-tool ordering; 22 checks then passed. Exact quotation matching does not prove entailment, so semantic review remains required.
- Ruling: allow up to 64 asset previews rather than 40 so 32 website candidates plus provider logo variants and up to 20 ad creatives can all receive guidance. The existing model-call and dollar ceilings remain unchanged; no sample is counted as classified without an inspected preview.
- LinkedIn identity independently resolved to page 96574094 using the official website link, reciprocal LinkedIn website field and company jobs filter. Harvest counts distinct creative sets, never carousel slides as separate ads.
- Ruling: the initial 15 downloaded ad previews contained 12 complete static creatives and three distinct video covers. Covers do not satisfy the full-creative target. Changed the coverage counter and regression-tested it. Continue up to the original six successful page allowance (four 90-day pages, at most two 180-day pages); allow eight total HTTP attempts because two earlier requests were rejected for the numeric rather than string page identifier. Both failed attempts remain in accounting with unknown billing. This increases possible request exposure by two, never the successful-page allowance.
- Independent review found six important issues: incomplete claim entailment, unsupported universal PMS/action gates, reversed channel readiness, trigger chronology, logo authority/preview matte, and missing evidence-drawer sources. Corrected draft criteria and lineage, preserved prior versions, quarantined all raw candidate statements from fact promotion, and produced literal source observations rather than pretending the original compound claims were verified. Human approval is still required.
- Final checkpoint: 9 documents, 63 source records, 53 originals/classifications, 16 complete static LinkedIn creatives and 3 separate video covers. Five verified founder-authored ads contributed four distinct new images. Three invented-ID classifications were rejected and re-requested with exact-ID constraints; 3 white customer-logo interpretations were corrected against original files. No logo or creative was generated.
- Verification: 32 isolated unit tests, 12 real-run integrity checks, JavaScript syntax check and local browser inspection passed. Knowledge tables, evidence drawer, source filtering, search/empty state, asset details and evaluation rendered. HTTP checks returned 200 for viewer/data/original and 404 for environment, raw spend and cache paths. Tracked Clue files stayed unchanged.
- Quality decision: useful review candidate, not approved brand governance. Initial independent scores are preserved without claiming a post-fix re-score. Candidate facts remain unapproved; semantic entailment, additional brands, production durability and latency are remaining integration gates. Final provider accounting and elapsed times are in the run report. Await human review; do not integrate or push.


## Conduit rework review checkpoint

The founder rejected the first pilot's depth. `REWORK.md` records the revised information architecture and the read-only platform/database audit. Work remains isolated; the first run and its preview are preserved. The new run is `runs/conduit-rework-20260919` and its separate preview uses port 3046.

The new document manifest separates company context, individual products, messaging, ICP/personas, proof and identity. Company/product/proof writing precedes messaging and ICP. Source passages, dependencies, original asset provenance and unresolved commercial decisions remain explicit. Human descriptions and Agent context are distinct viewer surfaces. The new reader preserves citation cells that malformed Markdown tables would otherwise silently drop.

Operational findings: Conduit's linked documentation serves `text/markdown`, which the first adapter rejected; the allowlist now supports it. Website deployment hashes can change while page text remains identical, so logo/style inspection must read the newly retrieved HTML rather than a stale source metadata URL. The original image filter omitted official website icons. Current platform knowledge already has richer per-product reports, while its asset mapper chooses description or usage_note; a richer agent-context record requires a future contract change.

Final rework checkpoint: 25 documents, seven folders, 103 source records and 56 originals. All 42 unit tests and 12 artifact integrity checks pass. Six bounded sales-use cases produced five first-pass successes and one partial logo handoff, followed by a successful focused retest. The library still required supervised editorial correction; it is not approved governance or proven autonomous multi-brand ingestion. See RESULTS_V2.md for exact limitations and accounting. Original provider receipts, review suggestions, dispositions and prior revisions remain in the ignored run directory.
