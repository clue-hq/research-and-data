# Discovery-first person trial — side conversation, 2026-09-24

- Founder explicitly requested a trial script after comparing PoC preliminary multi-angle
  searches with the newer single-deep-call experiments. This is separate from the parent task's
  already-developed saved-response continuation. No subagents or parent-thread mutation.
- Added `scripts/trial_person_discovery.py` and trial instructions/review guide under
  `docs/superpowers/previews/2026-09-24-person-discovery-trial/`. Reuses existing continuation
  runtime/providers/evidence/tracing without modifying it; only prepares distinct initial inputs.
- Agent selects ordinary search angles, reads/consolidates findings, writes a pre-deep research
  note, authors the full charter assignment, then adaptively follows sources. No fixed eleven-call
  loop, benchmark discovery hints, new production gates or active profile changes.
- Input preparation verifies declared original files and pinned documents; copies original
  brief/context/account sources, excludes later outputs/baselines, preserves full charter and Exa
  system, replaces conflicting optional-preparation wording in trial copies only. Runtime digests
  make later shared-runner changes visible. Existing trace names retained and documented.
- Live provider/model calls have not been authorized/executed in this side task. Scope is script,
  offline validation and a reviewable prepared package before deciding to launch.
- Closing verification: 10 focused offline tests passed (four new input-boundary tests plus six
  shared continuation tests); scoped Ruff checks passed after fixing long string literals.
  Prepared `.artifacts/person-discovery-trial-20260924/nick-01` offline: 79 original files copied,
  82 total agent-input files including trial instructions/capabilities; all declared hashes verified.
  No trace directory or provider calls. No evaluation-answer hints added. Exact prompts and
  unchanged charter/Exa system are preserved in the prepared package for founder review.
- Input caveat remains explicit: the retained brief has sparse persona context and interpretations
  of profile metadata that require reconsideration. Trial instructions address attribution/date
  interpretation and do not treat a profile slug as proof of an alias. Original evidence retained.
- Next action: review prepared inputs/instructions, then separately authorize a paid Nick trial.
  Inspect source reads, chosen searches, first deep assignment, follow-ups and resulting report;
  compare with prior outputs held outside the agent's inputs. Offline checks do not establish quality.

## Authorized live run and closing audit

- Founder subsequently instructed this side conversation to proceed with the run. First attempt
  `nick-01` failed with sandbox DNS/APIConnectionError before any research acquisition. Retained it.
  Prepared `nick-02` with identical input/instruction/prompt/runner hashes and obtained network
  escalation for the authorized provider calls. No production edits or fleet/database writes.
- `nick-02` completed in 540.84 seconds: 28 model calls, eight preliminary ordinary searches,
  one deep call, then three further searches, two page reads and two media resolutions. No
  transcription occurred. Recorded cost $1.691946 including model and provider results.
- Saved unchanged generated findings, exact query/dossier, full provider source fields, activity,
  metrics, runner snapshot and comparison under `.artifacts/person-discovery-trial-20260924/nick-02`.
  The investigation recovered the earlier benchmark's important personal/career findings without
  supplied answers, but missed fresh profile highlights and stopped before resolving a usable
  media candidate. Date/alias interpretation remains imperfect. Detailed evidence lives in the audit.
- Original source bodies/context retained; dynamic source index expanded without losing any of
  the 41 original entries. Local tracing/ledger complete for this trial; Langfuse configured and
  flushed, with the shared model-name callback warning still present; cloud completeness unverified.
- No further live run or production changes made. Next discussion: fresh source-field review,
  media follow-through and inherited context wording. A single run does not establish general quality.

## Focused source-review follow-up

- Founder explicitly requested trying the focused fresh-field changes and rerunning. Added opt-in
  trial instructions and `scripts/person_trial_source_review.py`: verbatim highlight overviews,
  field capture comparisons, original source paths, ten-row paging. No benchmark hints added.
- Shared continuation runner has only an optional acquisition-factory argument; original adapter
  remains its default. Trial script selects the new adapter from its prepared manifest. No media,
  production profile, seller brief, charter or Exa system changes in this experiment.
- Prepared `nick-03` from the same original snapshot. Original context hashes, charter and Exa
  system match `nick-02`. Saved-response visibility check stayed outside agent inputs.
- 13 focused tests passed; initial new test fixture accidentally triggered the existing thin-
  dossier retry, fixed by supplying a realistic-sized metered fake dossier. Scoped Ruff passed.
  Live comparison still pending at this checkpoint.
