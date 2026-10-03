# 2026-10-03 — Follow-up PR: the artifact-derivation model (and other follow-ups)

Not part of `perf/research-slowness-fixes` (spec
`docs/superpowers/specs/2026-10-03-research-slowness-fixes-design.md`). That PR only makes the
derivation writes one statement. This note is the brief for the PR after it. Needs its own spec and
founder sign-off, because it changes what privacy erasure deletes.

## The problem

`ResearchArtifacts.persist_body` (`platform/api/clue_api/quality_research_artifacts.py`) saves every
research artifact — each tool result, parameter set, plan, validated plan, budget and manifest
record, and dossier save — and records one `artifact_derivation` edge from **every** evidence
source of the account (plus context documents, context pins and quality-support artifacts) to that
artifact.

Measured in production, workspace `ws_0503532073454a10ab541c3fa9bf3e81`, one day (two account
jobs, ten person jobs): **1,169,646 rows, 759 MB**, 6,090 derived artifacts, up to **1,835 parents
for one artifact**. Rows grow as (artifacts per job) × (sources per account), so cost per job grows
as research deepens, and the table grows with every account researched.

## Why it is also a precision problem

Erasure follows these edges. The trigger `erase_derived_artifacts`
(`alembic/versions/aaae5d2e1fa4_scoped_research_evidence_grants_and_.py`) marks every child of a
privacy-erased artifact privacy-erased, and the trigger fires again for each child, so it cascades.
Because every output names every source of its account as a parent, **erasing one source — say one
person's LinkedIn page under a DSAR — erases every research output of that account**: dossier
drafts, tool results, published pages. Safe (it never under-erases), but far broader than the
request.

## Options

**A. Evidence-set anchor, versioned by manifest revision (recommended first step).** Each
(workspace, run, account) already has `arv2_evidence_manifest` with a strictly increasing
`revision`, and each `arv2_evidence_source` row carries the revision it was published at. Instead
of N edges, an output records one row: (artifact, manifest, revision seen). Erasing a source at
revision r erases outputs of that manifest whose recorded revision is ≥ r — exactly today's set
("every source the account had when the output was saved"). Rows become O(outputs + sources)
instead of O(outputs × sources): about 6,000 + 650 instead of 1.17M for this day. **Same erasure
semantics as today, much cheaper.** Context documents, context pins and quality-support artifacts
keep explicit edges (a handful each).

**B. Precise parents.** Record only the sources an output actually used: a dossier section's cited
`source_id`s, a tool result's own fetched source, a page's cited claims' sources. Erasing one source
then erases only what used it. Needs a definition of "used" for plans and model-hop artifacts, which
see the whole context. More precise, more work, and a product decision about what over-erasure is
acceptable.

**C. Keep the edges, prune old ones.** Not recommended: it does not fix precision, and pruning edges
an erasure relies on is unsafe.

Recommendation: **A now, B later if precision matters to customers.**

**Founder ruling 2026-10-03: option A approved** for the follow-up PR (same erasure semantics,
revision-anchored link per output). B stays a later, separate decision.

## What the follow-up spec must cover

- Migration: the anchor table, the new trigger branch (erasing a source erases outputs anchored to
  its manifest at revision ≥ the source's revision), and a backfill or a cut-over rule for existing
  edges (existing rows can stay; new writes use the anchor).
- Equivalence tests: for a fixture with sources added over time and outputs saved between them,
  erasing each source erases exactly the same outputs under the old edges and under the anchor.
- DSAR end-to-end test on a real throwaway database.
- Reclaiming the existing 759 MB (delete edges that the anchor now represents), only after the
  equivalence tests pass.

## Other follow-ups from 2026-10-03 (owners to be set)

1. **Recording unread search results** — ~89% of recorded sources were never read; record lazily.
2. **More, smaller worker processes** — decide from the slowness PR's part-0 numbers and process CPU.
3. **Per-job database connection limit** — only if part 0 shows tools waiting on `_db_lock`.
4. **Committee nomination on an unverified identity** (McKee: Cindy Lyons) and **mis-pointed
   citations** (two findings cite a different evidence file than the one holding the value).
5. **Scheduled maintenance window for VM deploys** (founder, 2026-10-03): deploys restart the
   workers and interrupt running research, so VM deploys should run in an announced window rather
   than on every merge to `main`. Today `deploy-images` deploys the VM automatically after Railway;
   the follow-up decides the window, how running jobs are drained first, and whether CI holds the
   VM step until the window.
