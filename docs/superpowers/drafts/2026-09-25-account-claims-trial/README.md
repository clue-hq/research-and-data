# Account dossier to claims — review draft 1

Status: isolated harness implemented, inputs prepared and offline writer checks
passed on 25 September 2026. The explicitly approved model trial completed with 53 records.
No production skill/profile or application tool contract has been promoted.
See `.artifacts/account-claims-trial-20260925/run-01/REVIEW.md` for remaining quality gaps.

Prompt revision: the system prompt now explains the agent's position between
acquisition and downstream consumption, the consequences of lost or distorted
information, and exhaustive meaningful coverage through the writing skill. The
earlier prompt remains in local commit `463de8329`. Run the agent method first;
a PoC-style extraction comparison on the same frozen inputs follows later, rather
than running both at once. See the execution receipt below for this first trial.

## Scope and ownership

One account research Deep Agent converts the retained r13 initial Zafran dossier
and its corresponding original account sources into claims in an isolated test
context. It writes directly; no claim specialist, person jobs, reconciliation,
new research, enrichment, narrative generation or publication. A fresh execution
will read saved research; this trial does not prove the benefit of retaining the
original researcher's conversation context.

The founder's current ruling governs this trial: claim content is an observation
or reported statement. Agent interpretation is optional attached context, never
a standalone factual claim. Duplicate, wrong-entity and insufficient-context
records remain stored and reviewable. No additional verification process, quote
offset requirement, field-classification gate or coverage-completion gate is proposed.

Review files:
- `SKILL.md`: exact proposed reusable writing instructions.
- `SYSTEM.md`: exact proposed isolated agent system prompt.
- `TASK.md`: exact proposed task body with manifest bindings supplied at preparation.

## Proposed record shape

The record keeps existing claim identity, account scope, run/context identity,
source lineage and audit machinery. Those are runtime-owned, not invented by the
model. `account.research_finding` remains the storage field for this trial.

The proposed agent-facing writing arguments are:

```json
{
  "topic": "Short descriptive topic",
  "claim_type": "reported_statement",
  "finding": "An attributed statement, or a coherent structured observation",
  "source_paths": ["<exact path copied from the trial evidence index>"],
  "attribution": "Named speaker, company, publisher or provider, when applicable",
  "time_context": "Relevant dates and what those dates describe; null if unknown",
  "qualifications": [],
  "review": {
    "status": "supported",
    "reason": "Brief explanation of the status",
    "duplicate_of": null,
    "expected_entity": null
  },
  "agent_interpretation": null
}
```

`finding` accepts prose or JSON, preserving meaningful process steps and detail.
`claim_type` is `observation` or `reported_statement`. An observation describes
what the inspected material establishes; a reported statement preserves who said
what without treating their statement as independently verified truth. A job
requirement is not installed practice. A company claim is attributed to the company.

`attribution`, `time_context` and `agent_interpretation` are nullable text. Dates
can remain approximate or unknown; no strict temporal validation is introduced.
`qualifications` holds useful limitations and disagreements, including those on
otherwise supported records. There is no numeric confidence threshold.

| Review status | Meaning and related information |
| --- | --- |
| `supported` | Saved material supports this observation or the fact that the attributed statement was made. Not a human approval or independent verification. |
| `duplicate` | Equivalent to another stored claim; `duplicate_of` is that real claim ID. Preserve the duplicate record and its sources. |
| `wrong_entity` | The material does not concern the trial target. `expected_entity` records a known name/domain/profile and optional already-known entity ID; otherwise null. Explain why; never guess a replacement identity. |
| `insufficient_context` | The proposed assertion remains unclear from available material. Preserve what was actually found and name the missing context; do not invent the missing assertion. |

Primary status precedence for overlapping issues: wrong entity, then insufficient
context, then duplicate, otherwise supported. Put additional concerns in
qualifications/reason. This is writing guidance, not a semantic rules engine.
Contradictory attributed statements can both be supported as statements; record
the conflict in qualifications instead of silently choosing a winner.

`agent_interpretation` explains possible significance or a hypothesis. It cannot
introduce an unsupported premise into the factual finding, acquire its own claim
ID, or be reused downstream as sourced evidence. Pure fit judgments with no
underlying observation belong in review notes, not manufactured claim records.

For a wrong-entity record, the outer account ID means "retained in this account's
investigation", not "asserted true about this account". Its status must travel
with the content in every trial export. Do not create or move data to another
entity during this single-account exercise.

## Mapping to the existing code — production unchanged

| Existing surface | Reuse and required difference |
| --- | --- |
| `quality_findings.py`, `record_research_finding@3` | Already accepts topic, JSON finding, readable source paths and notes; calculates canonical content identity within a job. Extend the same writer in an isolated version/profile to accept the proposed metadata. Do not fork claim persistence. |
| `quality_claims.py`, `FindingProposal` / `submit_proposal` | Already stores value JSON, source support, subject/context, provenance and assessment history. Map observation to `observation`, reported statement to existing `attributed_statement`; do not expose `inference` in this trial. |
| `claim.value_json` | Store topic, finding and the proposed metadata together; no separate claims database and no new claim table are needed for the experiment. Runtime-owned identity stays in existing columns. |
| `claim_quality_current` and assessment history | Keep distinct from the new detailed review status. Proposed mapping: supported -> supported (qualified if limitations); duplicate -> qualified; wrong_entity -> invalid; insufficient_context -> unresolved. These are the agent's recorded assessments, not an additional judge. |
| `quality_tools.py`, correction operations | Existing correction/withdrawal/conflict tools preserve history. They do not currently expose this new review vocabulary. Before execution, make the isolated writer's changed-record handling explicit; a changed payload alone creates another record, not a correction. |
| `quality_views.py` / ordinary quality readers | Read JSON and audit state, but do not implement this proposed review contract. An isolated review exporter must include all four statuses and supersession history while respecting scope and source erasure. Do not use an ordinary supported-only reader to evaluate coverage. |

Important current limitation: `record_research_finding@3` defaults the outer claim
kind to observation and constructs a supported assessment with qualifications.
Simply placing `wrong_entity` inside its JSON does not change that assessment.
The proposed skill must not be run against the unchanged v3 tool pretending these
semantics are implemented. An isolated compatible tool/profile and exporter are
prerequisites now implemented by the isolated harness described below.

The existing `Quality` vocabulary has no duplicate status/link. Store the detailed
review object in value JSON, validate duplicate references within the isolated
account/context, and do not overload `superseded_by` to mean duplicate. Supersession
continues to mean an explicit correction. Exact retries reuse their receipt;
distinct source occurrences may produce retained duplicate records. Do not create
duplicates just to demonstrate the status or rewrite identical findings repeatedly.

Work with related findings by referencing existing IDs or recording complementary
detail. The current writer does not merge source sets into an existing claim
automatically. Source-order normalization is not semantic deduplication.

## Coverage and review

Maintain one working coverage map: dossier section/passage or source path/location,
distinct finding, destination claim IDs, and outcome. Also record source material
reviewed, not yet read, unavailable, or containing no additional findings. Mark
interpretation-only passages as review notes. Ignore page navigation, cookie text,
and repeated boilerplate; record that treatment at source level rather than
manufacturing claims for it. Do not equate every sentence with a claim.

The writer revisits this map and reads back its saved records before finalizing.
The map reveals agent omissions but is not independent proof of completeness.
Human review compares it against the actual dossier and source inventory, including
material the agent failed to inventory. Evaluation examples are reviewer-only and
must not be injected into the agent's task as expected discoveries.

Future presentation direction: supported records in the ordinary narrative;
flagged records retained under an expandable section with explicit attribution
and status. Duplicate records reference their canonical counterpart. Wrong-entity
records describe the misattribution, not an account fact. No frontend or synthesis
changes are included now; the trial review shows every status openly.

## Retained inputs and preparation boundary

Input root: `.artifacts/arv4-clue-zafran-20260925-r13/`.
- Primary report: `account-dossiers/account-dossier-v1.md` and its manifest.
- Corresponding original evidence: source inventory plus `account-raw/manifest.json`
  and its acquisition bodies; include referenced retained media/transcript material.
- Context: original Head-of-ABM brief and pinned seller/ICP/persona references,
  only to explain relevance, never as evidence for target facts.

Preparation must reconcile the dossier manifest with account acquisitions at the
initial save; resolve original bodies behind wrapper/index records and inventory
any unavailable originals. Do not silently substitute later person-job evidence,
dossier v2 or Zafran-03/PoC findings. Repeated wrapper/provider records are not
independent sources. Record exact exported bytes/digests and the inclusion boundary.

Use a separate test database/context and preserve the original r13 database/blobs.
Bind readable workspace paths in a trial manifest; the host paths above are not
assumed to be agent workspace paths. The prepared manifest records every admitted
source and input digest.

## Isolated execution receipt

- Harness: `scripts/trial_account_claims.py` (`prepare`, `smoke`, `run`, `export`).
- Output: `.artifacts/account-claims-trial-20260925/run-01/`.
- Physical database: `clue_account_claims_trial_20260925_01`, cloned from the r13
  development database. Copied artifact bytes; original database/blobs remain unchanged.
- Inputs: the initial dossier's 351 source records plus its explicitly labelled
  report record. Readable evidence paths, context, skill and tool contracts are
  frozen in `workspace/`; input/prompt hashes are in `manifest.json`.
- The clone preserves historical scope IDs; a distinct trial ID, actor marker and
  write namespace isolate new claims. Reads/exports expose only this trial's claims.
- The writer reuses `submit_proposal`, source grants, provenance and quality history.
  All four review statuses remain visible. Identical retries are idempotent;
  duplicate references must point to a canonical claim already written in this trial.
- This first harness has **no correction operation**. A changed payload creates a
  separate record; the agent must report unresolved corrections honestly.
- Native Deep Agents uses a virtual filesystem and `/work` compaction archive root.
  Model tools allow input reads and work/output writes, but no shell execution,
  provider research, person jobs, specialist delegation or publication.
- Real-database smoke checks exercised all four statuses, attributed-statement
  mapping, duplicate references, exact retries and invalid source references.
  Probe writes were rolled back and the trial started with zero new claims.
- Uses the configured account model, shared model gateway, Langfuse and local
  per-turn/tool traces. The user explicitly approved this payload and model run.
- This is a fresh agent execution with saved research. It does **not** exercise the
  production C5/fleet/reconciliation lifecycle or preserve the original research
  conversation. Native checkpoints are in memory; interrupted model execution is
  not automatically resumable, though completed claim writes are durable.
- `harness.executed.py` preserves the actual runner before subsequent formatting.
  The manifest's harness digest refers to preparation; execution provenance uses
  the preserved runner snapshot. Prompt and input hashes are checked before dispatch.

Review the written findings and omissions before any production integration or
additional paid iteration. A successful tool run does not establish exhaustive
coverage or factual correctness.
