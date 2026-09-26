# Account/person dossier classification — next isolated trial

The founder approved strengthening classification and explicitly asked for thorough researcher
skill coverage. [SKILL.md](SKILL.md) is the proposed common supplement to both active claim-ready
account/person skills. It is not installed yet. Current launch revision19 pins v2 of both skills;
Finding/Entry lack field/category properties and finding_proposal hardcodes research_finding.
Changing instructions alone would be unsupported and misleading.

## Exact proposed system-prompt addition

> Before classifying dossier findings, read the complete dossier-field-classification supplement
> alongside your claim-ready dossier skill and the supplied workspace field/category definitions.
> Choose fields by their meaning, subject and value shape; assign categories from the actual
> evidence. Preserve original findings, public wording, attribution and uncertainty. Use a generic
> finding when a narrower field does not fit; do not force a classification or turn seller relevance
> into a target fact. Review the saved dossier against both skills and correct defects before import.

The integration must insert the real disclosed skill path; this draft does not invent a mounted
resource or tool. Reuse one supplement rather than duplicating its rules in account/person skills.

## Contract and implementation boundary to resolve next

The isolated entry contract should carry a registered field reference/version, optional matching
typed value, category IDs and a concise explanation only for ambiguous/fallback cases, alongside
the existing full finding and evidence. The schema must distinguish an absent typed value from a
source-established value. The original finding must not disappear when a scalar field is chosen.

Do not shove the existing rich finding object into a scalar field. Inspect and reuse the claim
store's typed-value/provenance seam. Establish how one logical finding retains its original text
and optional typed representation without counting it twice. Deterministic validation checks shape,
scoped keys and references; an additional LLM does not perform hidden re-extraction or semantic
reclassification. No new maturity/verification gate should block retained uncertain research.

Resolve workspace-field proposals through the existing registry authority only. The first trial
should use supplied registered definitions and record proposals separately; it must not silently
create fields globally. New schema/import behavior requires versioned resources and tests before
updating the launch default. Previously pinned resources and dossiers remain reproducible.

## Quality evaluation before integration

Use saved r18 account and person material, without new research. Include typed enrichment facts,
public statements, requirements versus installed tools, historical/current roles, healthcare-style
credential ambiguity, conflicts, source-only details and research gaps. Fictional cases supplement
but never become retained account facts. Snapshot the actual registry for the isolated context.

Show each original finding next to the selected field, typed value, categories, source attribution,
review label and any lost or strengthened meaning. Assess classification precision and retrieval
usefulness, not how few research_finding records remain. Compare narrative packet relevance using
these classifications before relying on them to generate pages. Preserve fallback findings for
review rather than omitting them. A passing schema is not semantic-quality acceptance.

Current status: the isolated account classification replay is implemented and has completed;
production schema/import wiring and activation remain outstanding. No application DB writes.

## First completed classification replay

Artifacts: `.artifacts/dossier-classification-trial-20260926/run-02/REVIEW.md`.
The founder requested a trial using the prior standalone saved research. This replay used
295 source records from account-dossier-replay-20260926/run-02, with its Clue context and a
retained r18 field catalog snapshot. It is not a new r18 account/person research run.

The trial-only entry adds `classification` with `field_key`, `field_version`, `projection`,
`categories` and optional `reason`. A specific registered field carries `projection.value`
validated through the existing claim-store schema validator. Generic research_finding uses
null version/projection because that fallback is absent from this retained catalog snapshot;
no registry version is invented. Full findings and evidence remain in the same entry.

Grok 4.6 produced 144 entries (33 specifically classified, 111 generic with categories).
Runtime 19m15s; 64 priced model generations cost $4.357908. No research-provider purchases,
claim import, fleet or publication. All 138 tool calls were confirmed in Langfuse. JSON/value
shapes and final references passed; this is not semantic acceptance.

Observed next improvements: resolve the provider-description conflict in the supplied catalog;
attach typed projections to suitable original findings rather than adding overlapping summaries;
classify assertion substance rather than its source page's broad subject; preserve ambiguous
role labels without asserting a conflict. The researcher did correct technology usage scope and
move one speculative passage into interpretation during its own review. Exact inputs, original
model output and the detailed review remain saved; no manual edits to its final findings.
