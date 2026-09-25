# Claim-ready account dossier — isolated trial

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

## Current trial result

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
