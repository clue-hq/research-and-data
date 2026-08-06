# M8D R6 — Account research fleet and user return acceptance

**Status:** accepted 2026-08-06
**Roadmap authority:** `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md`, R6

## 1. Accepted boundary

R6 composes the R2 shared queue/lease substrate, R3 `create_agent()` runtime, R4 governed tools,
and R5 account agent into one separately launched account-research fleet. It does not introduce a
second fleet, a provider-specific controller, a new compulsory project phase, or automatic contact
research.

`AccountResearchFleetLauncher` compiles one exact, human-confirmed action into:

- the ordered account set and one account job per selected account;
- exact workspace/project/product/project-run and confirmed directive lineage;
- the exact effective per-account directive pins and human-approved tier claims;
- an exact job-to-`account_run` binding, so repeated launches for one account cannot make a
  provider factory guess or select a latest run;
- registered account fields, directional questions, field-to-source authority, no-reveal
  committee authority, policies, approval references, and budgets;
- one content-addressed account selection, account-research run, job, attempt, lease, and
  checkpoint identity; and
- compatibility `account_run` rows pinned to the same effective directives for the retained
  provider/claim services.

Compilation and fleet offer commit in one transaction. Replaying the same action and operation is
idempotent. Reusing an action reference with changed operation or authority fails and rolls back
the attempted run, account-run rows, jobs, and queue tasks. The new authorization is the R6 fleet
selection itself; no legacy `account_deep_launch` is created, and the launch works without the
outer project state machine being at `DEEP`.

## 2. Fleet behavior

The fleet controller persists a deterministic canary cohort and holds the remainder before any
worker can claim it. The versioned supervisor policy evaluates accepted finalization outcomes,
review fraction, and the account-only boundary. A healthy terminal canary releases the exact held
jobs; a blocking outcome, excessive review fraction, contact-research request, or worker failure
suspends honestly with a durable diagnosis and return snapshot.

Steering is scoped and journaled:

- pause and resume retain the same job/checkpoint identity;
- reprioritization updates both durable control and runnable queue priority;
- cancellation uses R2 accepted terminal receipts for every nonterminal job, revokes leases,
  cancels active waits and queue tasks, and cannot be resurrected by a late provider wake; and
- no steering operation widens the selected accounts, fields, sources, questions, or committee
  authority.

External wait is a suspended job state rather than success. It releases the worker slot and
database transaction. Ordinary worker exceptions park the exact job as a resumable supervised
suspension instead of losing it or falsely completing the run.

## 3. User return

The scoped projection and immutable terminal/suspended return expose:

- exhaustive queued, active, waiting, paused, and terminal account counts;
- accepted finalization outcome and receipt per account;
- run/job spend and budget;
- persisted account research-result references;
- committee-member identity references;
- durable review-item references and the run review queue; and
- the supervisor diagnosis.

The projection proves `contact_research_started=false` and rejects any contact-research request in
the account run. Finishing account research therefore returns control and results to the
Head-of-ABM; it never creates or launches contact jobs.

## 4. Production composition boundary

`build_account_research_fleet_composition()` joins the launch/read service and detached R6 work
handler to the R2-R5 runtime. Provider actions are rebuilt from each durable leased job through
`RunScopedAccountResearchProviderActions`; the R5 static job-id map is explicitly rejected by this
production composition. Each semantic-action factory receives the exact persisted `account_run`
identity for its leased job.

Concrete Exa/Sumble acquisition, materialization, claim, evidence, cost, and lineage services stay
behind the three R5 semantic action bindings. R10 owns deployment promotion and credentialed live
canaries; R6 does not enable a default-off paid provider switch or promote historical recipes.

## 5. Source-plan integration correction

The combined R5/R6 test exposed an invalid interaction between ordered source authority and the
first Exa bundle. An authorized fallback did not mean Exa should run first for that field. The
guard now treats only fields whose first effective source is Exa as primary Exa bundle members.
An Exa fallback for a structured-primary field is allowed only after a preceding non-Exa attempt
for that field. Thus qualitative fields start with Exa, while `sumble_jobs -> exa_deep` retains an
honest fallback without being mechanically forced into the initial Exa call.

## 6. Verification evidence

On the dedicated isolated Postgres database `clue_roseau_r6`:

- the focused R0-R6 pure contract/runtime battery passed **92** cases;
- the R2-R6 database battery passed **21** cases;
- the retained Exa/Sumble acquisition, snapshot, eligibility, preparation, and replay matrix
  passed **33** cases;
- the R6 migration passed downgrade to `85595185f793`, upgrade to `4ff507129dd5`, and reports one
  Alembic head;
- scoped Ruff passed;
- repository source mypy passed **556** files; and
- all **24** import-linter contracts remained green.

The database acceptance includes exact non-`DEEP` launch, changed-action rollback, canary hold and
release, failure suspension, scoped steering, external wait, cancellation/no-resurrection,
terminal result/review aggregation, immutable user return, and zero contact jobs/requests.

No credentialed or paid provider call was made for R6 acceptance. The retained real
acquisition/materialization/claim plumbing was exercised with deterministic provider-boundary
fixtures. The roadmap assigns bounded live Exa/Sumble account and contact canaries, paid-spend
evidence, and cutover to R10.

## 7. Exit decision

R6 is accepted. Every selected account job either progresses through the bounded fleet, waits, is
durably suspended, is cancelled, or reaches accepted terminal finalization. The run exposes its
account results, committee identities, spend, diagnosis, and review queue and returns control to
the user without initiating contact research.
