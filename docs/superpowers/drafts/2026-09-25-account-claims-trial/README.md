# Account dossier to claims — review draft 1

Status: proposed shape and exact instruction drafts, 25 September 2026. Not a
registered skill/profile, implemented tool contract, or executed experiment.

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

## Mapping to the existing code — verified, not yet changed

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
prerequisites for the eventual experiment, not changes made by this draft.

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
assumed to be agent workspace paths. No manifest has been generated by this draft.

Next review is of this shape and instruction text. Only afterwards prepare the
compatible isolated tools/context, verify them offline, and show the resolved
inputs before a model run. Preserve configured tracing and durable write receipts.
