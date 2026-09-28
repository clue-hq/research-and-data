# Researcher-authored JSON dossiers — platform integration

> Historical revision-16 integration record. Current local revision 24 is documented in
> [the research lane README](../../../platform/api/clue_api/arv2/README.md): researcher-owned
> narrative, targeted finding updates, concise review, post-import revisions and reciprocal
> conflict imports. Do not use the older steps below as the selected runtime instructions.

## Outcome and ownership

New v4 launches pin quality recipe revision 16. Both account and person Deep Agents own
research acquisition, source review, formation of the structured dossier, and its critical
review/correction. Code imports each reviewed entry through the existing claim-store writer.
There is no claim-extraction model or `research_claims` delegation in these new parent profiles.
The existing narrative specialist remains available after import. Older launches retain their
original resource pins and behavior.

This ports the account JSON trials and saved-person replay closely. Their Entry model, parser,
finding-to-claim mapping, statuses, related-ID handling, and importer are reused. Section
replacement is now shared between the trial script and production tools. Formation instructions
preserve the trial's detailed section guides and fictional wrong/right examples; person guidance
retains public biography, outside-work material and voice. Nothing depends on a benchmark target
or expected discoveries.

## Authoring and storage contract

1. Read the pinned acquisition skills and the complete `claim-ready-account-dossier/v1` or
   `claim-ready-person-dossier/v1` skill. Investigate through the existing tools. Exa still
   researches evidence; the platform researcher authors the final structured output.
2. Call `save_dossier_section(section, findings)` incrementally. Each call replaces the complete
   named section while preserving others. Stable F-identifiers must be unique across sections;
   forward conflict/duplicate links can resolve in later sections. Re-read before revision.
3. Read `/research/dossier/latest.json`. Its `document` is the canonical
   `{"sections":[{"section":"…","findings":[…]}]}` object. The surrounding manifest carries
   subject/context ownership, version, state, artifact keys and any import receipt.
4. Critically review original sources → findings for omissions and findings → originals for
   unsupported additions, against all skill rules. Correct actual entries. Keep coverage and
   unanswered questions in working notes; interpretation is an optional attached field.
5. `validate_dossier` checks representation and references only. `finish_dossier` freezes the
   reviewed document and invokes the shared deterministic importer. It does not end the turn.
6. Inspect outcomes, supply the returned claim IDs to narrative synthesis and the typed final
   report, and finalize. Completion checks a successful import and inclusion of all imported
   IDs; it does not certify semantic completeness or impose employment/fit/corroboration gates.

The authoring fields are `id`, `topic`, `claim_type`, `finding`, `source_paths`, `attribution`,
`time_context`, `qualifications`, `review`, and optional `agent_interpretation`. Claim types are
observation and reported statement. Review labels are supported, duplicate, wrong entity,
insufficient context and potential conflict. Related F-identifiers resolve into claim IDs.
The section and exact authored entry are retained with import identity/hash/location; source
URLs and provenance remain attached. Account findings use `account.research_finding`; person
findings use `contact.research_finding`, bound to the job's contact. Code does not choose a more
specific field-catalog key, rewrite meaning, merge distinct findings, or certify outreach use.

## Durability, recovery and authority

The three tools run through the existing C5 tool registry, recipe, role permissions, operation
journal and allowance accounting. Source reads and references use the existing evidence grants.
Snapshots and canonical JSON artifacts use ResearchArtifacts and existing artifact references;
source/context derivations preserve erasure behavior. No migration or alternate database.

A job-scoped transaction advisory lock serializes section saves/import against other dossier
writes. It does not upgrade the shared job locks used by source readers. A failed save leaves
the previous complete draft intact. Every changed draft is retained, independently of later
narrative/finalization failure.

`finish_dossier` identifies an import by job and document hash. Per-entry savepoints preserve
independent successful writes. A partial import records `import_pending` and freezes that
snapshot; retry resumes the same import and reuses stored claim IDs. Complete imports remain
frozen too. A model must not alter classifications simply to bypass structural validation.

On later continuations, the researcher reads the saved dossier/receipt and reuses imported
IDs. Contact findings remain contact claims. This change does not redesign reconciliation,
post-import correction, person dispatch timing, display rules or historical claim cleanup.
Those remain separate work. It introduces no paid call, model switch, worker launch, runtime
limit change or new environment flag.

## Review pointers

- Platform tools/state: `platform/api/clue_api/arv2/quality_json_dossier.py`.
- Shared section/entry parser: `platform/api/clue_api/arv2/dossier_json.py`.
- Shared importer: `platform/api/clue_api/arv2/dossier_import.py`.
- Runtime and role wiring: `platform/api/clue_api/quality_research_wiring.py`.
- Exact prompts: research-quality/prompts/quality-account-research/v16 and
  quality-person-research/v16-person under `platform/agents/catalog/`.
- Formation skills: research-quality/skills/claim-ready-{account,person}-dossier/v1.
- Acquisition skill updates: account-dossier/v6, person-dossier/v2, governed-evidence/v4.
- Immutable launch manifest and recipe: research-quality/launch-v4-r16.json, recipe-v16.json.

## Verification

Offline tests exercise schema preservation, profile/tool pins, source/reference errors,
incremental forward links, restart reads, exact account/contact writes, frozen replay, partial
write recovery, complete-ID handoff, and real scripted Deep Agent/C5 finalization/cold replay.
Launch/worker/continuation and nomination regression checks are run against a dedicated test
Postgres database, with outbound provider access blocked. No live quality acceptance is claimed.

The prior person replay still showed judgment limitations (source-reading omissions, occasional
scope leakage and over-bundling). Porting its instructions and reliable import does not establish
that these have disappeared. The next paid acceptance should inspect both the JSON findings and
original evidence, then the exact stored records, separately from narrative quality.

Local verification result: 45 focused offline tests and 27 isolated Postgres checks passed
across the affected suites. These include real scripted account/person runtime finalization,
new-launch worker continuation, prior pinned runtimes, nominations, and source-erasure propagation
to the canonical JSON and state artifacts. Ruff and targeted mypy passed. Historical launch
manifests r2–r16 and the new recipe/profile resources validate. No paid provider run was launched.
