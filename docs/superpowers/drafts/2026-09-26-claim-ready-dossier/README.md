# Claim-ready account dossier — isolated trial

> Historical trial instructions and results. These files are not the platform's mounted
> skills. Current account/person formation uses the selected `claim-ready-*-dossier/v3`
> catalog skills and shared production tools; see the research lane README. Statements
> below that production integration is pending describe the original trial checkpoint.

**Fresh-research extension (26 September):** the live account trial now uses JSON
sections/findings through `save_dossier_section`, rather than asking the agent to
edit record lines. The saved-data format described below remains preserved for
earlier comparisons. `scripts/live_account_dossier.py::prepare_format` adapts this
skill's format section while keeping its substantive rules; it snapshots the exact
resulting skill and prompt addition in each prepared trial folder. The live agent
does its own acquisition, source review and final dossier formation. Exa still
receives a research assignment, not claim-storage instructions.

The canonical live output is `dossier.json`; readable Markdown and legacy
sectioned records are derived from that JSON without a second model.
The authoring tool checks shape, unique finding IDs and retained source paths;
final validation checks related IDs. These checks do not establish semantic quality.
Production prompts and dossier storage are unchanged.

## Person saved-dossier test

`scripts/trial_person_dossier.py` prepares a saved-person replay using the same
section tools, JSON contract, public-statement rules, review tags and worked examples.
`PERSON.md` supplies person-specific formation instructions and a section guide;
the prepared skill replaces the account-only biography exclusion. Exact generated
instructions are snapshotted under each trial's `inputs/.deepagent/skills/`.
Original source segments are reassembled with continuity checks, not summarized.
The configured `arv2_person` model performs formation with acquisition disabled.

The shared importer is now named `import_research_dossier`; the historical account
name remains an alias. A person scope writes `contact.research_finding` to the
contact bound to its persisted job. It cannot be retargeted to the account. The
isolated adapter matches the supplied LinkedIn identity to one existing person job
in a fresh database clone, admits the saved sources, then imports the frozen JSON.
No production jobs are launched or modified.

The trial retains public person findings with weak identity-binding metadata and
`outreach_safe=false`; the coarse public-personal use label is a retention default,
not a per-finding sensitivity judgment or permission to use findings in outreach.
Semantic quality and finer classification remain separate from exact JSON storage.
This experiment neither purchases new research nor proves the original researcher's
conversation context was preserved. Production person dossier adoption is pending.

Completed saved-person trial: nick-01 produced 79 findings across eight sections,
all imported as contact claims in isolated run-09. Re-import reused all IDs and
independent export comparisons passed. Grok 4.6 cost $3.249254 (51 calls); no research
acquisition. Public voice and outside-work material survived, but source-reading,
subject selection, repeated summaries and some bundled conflicts remain imperfect.
Review: `.artifacts/person-dossier-replay-20260926/nick-01/REVIEW.md`.

## Programmatic JSON import

The live/replay adapter now imports `dossier.json` directly through
`clue_api.arv2.dossier_import.import_account_dossier`; Markdown is not the input.
The existing line-format importer remains for earlier trial artifacts only.

| Authored JSON | Stored account claim |
| --- | --- |
| Each finding object | One `account.research_finding` claim |
| Finding text/object, topic, attribution, time, qualifications | Preserved values |
| `observation` / `reported_statement` | Observation / attributed-statement metadata |
| Optional `agent_interpretation` | Separate property, never folded into factual text |
| All five review statuses | Retained, including duplicate, wrong entity and uncertainty |
| `source_paths` | Authorized sources with IDs, canonical paths, URLs, kinds and locators |
| Duplicate/conflict finding IDs | Related stored claim IDs; original IDs retained too |
| Section and original finding object | Dossier origin metadata with document/entry hashes |

The caller supplies an immutable JSON snapshot, its expected hash, an import ID,
and the run's exact context/evidence grant. The service uses the existing proposal
writer and claim store; it does not call a model, acquire sources, classify claim
topics into other catalog fields, merge similar findings or synthesize page copy.

It rejects ambiguous JSON object keys rather than accepting the last value. Record
errors have JSON locations; valid independent findings can still be stored. Each
write has a database savepoint and readback comparison. Failed dependencies remain
explicit errors. Missing/cyclic references are reported without changing the
agent's judgment. The receipt reports `complete`, counts, outcomes, errors and
readback checks. The caller commits the outer transaction before publishing it.

Retries of the same job/import reuse durable claim receipts. Once claims exist,
that import ID cannot silently switch to a different document. Corrections and
semantic deduplication across different imports remain separate work. Partial
receipts are not full completion. Original JSON remains retained by the caller.

The reusable seam is available in the platform package and used by the isolated
trial adapter. It is **not yet selected by production fleet jobs**. No changes to
production specialist ownership, person research, reconciliation or display accompany it.

Storage-only verification: saved replay run-02's 122 findings imported exactly into
isolated run-08, then all 122 receipts replayed without new claims. External network
access was blocked; no model/research costs. Independent comparison and receipts:
`.artifacts/account-claims-trial-20260925/run-08/IMPORT-REVIEW.md`.

Fresh trial evidence: `.artifacts/account-discovery-trial-20260926/zafran-claim-ready-03/REVIEW.md`.
It completed 80 findings and an exact 80-claim isolated import/re-import, but
source omissions, granularity and interpretation problems remain. No promotion.

**Selection-guidance revision (26 September, after fresh trial 03):** updated the
shared skill, saved-data system prompt and fresh-run system addition. The revision
distinguishes source assertions from inferred consequences and research questions;
requires canonical findings instead of repeated fit summaries; clarifies independent
events/speakers, comparable conflicts and checked relationship targets; and prevents
format feedback from being treated as evidence for changing an assessment. It adds
bidirectional source/entry review for omissions and unsupported additions. All
examples remain generic. Historical trial snapshots are unchanged. This revision
has not had a paid quality evaluation and does not change production or validators.

**Saved-source JSON replay:** `live_account_dossier.prepare_replay` prepares a new
directory from a completed fresh trial. It copies original evidence, the prior
draft dossier and seller/context references, excluding old working notes, model
history and reviewer answers. It uses the revised formation skill with the same
JSON section tools. The preview runner recognizes `replay_saved_research`, removes
the acquisition tool and its allowed operations, and uses a saved-evidence task
instead of fresh-research instructions. Only model calls are paid. The finished
dossier can use the existing isolated importer with a fresh run number. This
tests revised selection on the same acquired material, not fresh discovery or
preservation of the original researcher's conversation context.

Completed replay: `.artifacts/account-dossier-replay-20260926/REVIEW.md`. Initial
execution reached the 200-step graph limit; one saved-context continuation finalized
95 findings. All imported exactly into isolated run-06 and replayed without duplicate
writes. Total model cost was $3.935124, no new research acquisitions. Specific source
omissions improved, but bundled findings, repeated fit summaries, speculative factual
text and research gaps stored as supported observations remain. No semantic acceptance
or production promotion. The founder increased subsequent claim-ready trials to 700
graph steps; other runtime limits remain unchanged.

Worked-example replay run-02 completed with the same source/draft/context inputs;
only the skill and system prompt changed among initial inputs. Expanded examples
cover researcher reasoning/coverage gaps and public-statement preservation,
independent speakers and interview attribution. It produced 122 findings, stored
exactly in isolated run-07; repeat import reused all IDs. Gap and fit bundles moved
to notes, and calendar events were separated, but speaker bundling and title/scope
judgments remain faulty. Cost $5.264324 across 72 model calls, no acquisition, no
continuation under the 700-step limit. Full review:
`.artifacts/account-dossier-replay-20260926/run-02/REVIEW.md`. No production promotion.

The researcher authors the claim-ready findings while forming the dossier. Code
imports those records without a second model selecting, splitting or paraphrasing
them. This is a trial, not a promoted production format.

The reusable instructions contain no target-specific names, tool discoveries or
expected answers. The task gets the account and seller context from the manifest.
The isolated harness retains its existing development fixture; that is test input,
not agent procedure. Earlier direct claim-writing trials remain unchanged.

## Exact instructions and representation

- `SYSTEM.md`: researcher's responsibility and consequence of omission/distortion;
  claim-ready output, source coverage, statement fidelity and scope.
- `SKILL.md`: generic granularity, public-statement rules, section-wise handling,
  advisory statuses, stable finding references, source review and exact record shape.
- `TASK.md`: manifest-bound execution assignment without account-specific examples.

Canonical output is Markdown headings with one JSON finding per physical line.
JSON is used only to delimit content/metadata reliably: quotations, punctuation and
embedded newline escapes are preserved, rather than parsed heuristically from prose.
Each finding may contain several sentences, a structured passage or one coherent
workflow. The section remains a Markdown heading. A readable Markdown view is
rendered from these records, with all fields and available source URLs, using no LLM.
It is not a separately authored summary or another source of truth.

Fields reuse the prior trial contract: topic, observation/reported_statement,
finding, sources, attribution, time context, qualifications, advisory review and
optional agent interpretation. Added F-identifiers connect duplicates/conflicts.
Importer-owned metadata retains finding ID, section, file digest and entry digest.
Forward references are ordered before insertion. One-way links avoid cycles.

The parser checks syntax and actual references only. It neither verifies meaning
nor creates a new semantic or presentation gate. Validation feedback lets the
agent repair its file before freezing. Standalone import retains valid independent
entries and returns explicit errors for malformed/dependent entries. It never
silently drops an invalid line or fixes a factual assertion itself.

## Reviewed implementation surfaces

| Surface | This trial |
| --- | --- |
| Existing `scripts/trial_account_claims.py` | Reuse source/context preparation, isolated DB, frozen prompts, model construction, native Deep Agents, read/write scope, ten repair rounds, local traces and Langfuse. `prepare --dossier-mode` switches this experiment's instructions/tools. Previous default behavior remains. |
| `scripts/account_dossier_trial.py` | New generic record parser, dependency resolution, readable rendering, mechanical import and stored-value comparison. No provider calls. |
| Trial `Writer.write` | Accept optional dossier-origin metadata and reuse the shared proposal writer. Existing direct-write payload/hash is unchanged when metadata is absent. |
| Shared `quality_claims.submit_proposal` | Reused unchanged: source lineage, claim identity, assessments and audit remain in the existing substrate. |
| Production `quality_dossier.save_dossier` | Inspected; continues saving the existing free-form dossier and evidence manifest. No production format or persistence change. |
| Production account prompt/charter/profile/catalog | No promotion. After trial review, these would teach formation and expose the importer in the integrated flow. Concurrent edits from other tasks are untouched. |
| Production claim-specialist delegation and fleet lifecycle | No change. Replacing that owner requires a later integrated change, not this isolated test. |
| Person research, reconciliation, page synthesis | Outside this trial. |

The agent has no direct claim-writing tools in dossier mode. It can read retained
inputs, write/edit working files and the dossier, validate it, and freeze it.
No acquisition, task delegation, shell or publication tools are exposed.
After generation completes, the harness imports through the existing writer and
exports claims. Each entry receives a claim ID or an explicit failure receipt.

Retries of the same frozen dossier reuse stored receipts. Persisted origin metadata
supports recovery after an interrupted import without trusting a separate JSON
receipt as database truth. A changed entry is not an implicit correction; this
experiment refuses to overwrite it. Original evidence and historical claims remain.

## Verification and comparison

Offline checks cover quoting/newlines, forward links, duplicate identifiers,
unknown sources, malformed lines, cyclic links, five statuses, unchanged-content
retry and changed-content refusal. The real isolated-DB smoke rolls back all probe
writes and checks stored statement bytes and dossier metadata through the shared
writer. No semantic correctness is inferred from these tests.

The live trial reuses the previous trial's source/context bytes and configured
account model. It receives neither earlier generated claims nor reviewer answer
keys. Exact prompts, skill, harness, source hashes, model traces and usage are saved.

Review separately:

1. **Acquired research → dossier:** omissions, bundling, misattribution, statement
   fidelity, false conflicts and scope. This still requires human judgment.
2. **Dossier → stored claims:** exact finding/metadata preservation, source identity,
   section, link resolution and explicit per-entry import outcomes.

The second stage can be compared mechanically. The first remains a quality test.
A fresh saved-data execution cannot prove that a live researcher's original context
will improve its dossier, nor certify production fleet/reconciliation behavior.

## Execution

Use a new numbered run; never re-prepare or rerun a historical folder:

```sh
.venv/bin/python scripts/trial_account_claims.py prepare --run-number 3 --dossier-mode
.venv/bin/python scripts/trial_account_claims.py smoke --run-number 3
.venv/bin/python scripts/trial_account_claims.py run --run-number 3
```

The model step is paid and requires task authorization. `import-dossier` can repeat
only the deterministic import for recovery/idempotency verification. `export`
reads the stored trial rows without invoking a model. Real source data remains in
ignored isolated artifacts, not these reusable instructions.

## Trial results

Run-03 was attempted with the configured Grok 4.6 model. The provider rejected the
fourteenth model call because the configured OpenRouter key's weekly limit was
exhausted. Thirteen calls completed, but the agent had not yet written its dossier.
No generated records were imported. Nine offline tests and the rollback-only real
database smoke passed; research quality remains untested for this format.

The interrupted inputs, traces and review are preserved at
`.artifacts/account-claims-trial-20260925/run-03/`. Do not repeat the `run` command
against that started folder. After the configured key allowance is available,
prepare a new numbered trial with the same instructions and input bytes. The
current in-memory checkpoint does not survive process exit.

After the founder updated the configured key, run-04 completed with unchanged
instructions and matching input hashes. It produced 101 entries and imported all
101 claims. Stored content/metadata, source IDs and sections matched; a repeat
deterministic import reused every claim without duplication. Grok 4.6 completed
46 model calls, with $3.545966 recorded usage and about 10m41s to freeze the dossier.

Research-to-dossier quality remains mixed: useful statement preservation, but
bundling, omissions, scope leakage and role misinterpretation remain. Six validation
calls and 17 edits repaired format/reference problems; some repairs changed semantic
annotations. Mechanical import success is not grounds for production promotion.
See `.artifacts/account-claims-trial-20260925/run-04/REVIEW.md` for the independent
comparison and all output links. No production behavior was changed.
