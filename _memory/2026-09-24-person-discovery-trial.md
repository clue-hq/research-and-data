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

## Focused follow-up closing audit

- Authorized `nick-03` completed in 573.65 seconds with 27 model calls, 15 ordinary searches
  (eight before the deep call), one deep call, four page reads and three media attempts. Recorded
  model/provider cost $1.931550. No full media transcript obtained; acquisition implementation unchanged.
- Agent received first ten source overviews inline and read both continuation pages completely
  by recorded line ranges. A recommendation present only in fresh profile highlights reached
  the agent and report. Personal follow-ups produced richer source-linked findings. Raw provider
  results varied: the specific earlier omitted project was now in the dossier without supporting
  returned fields, was investigated, and remained explicitly uncertain rather than being dropped.
- Saved unchanged report, original records, exact query/system, full source compilation, activity,
  measurements and comparison in `.artifacts/person-discovery-trial-20260924/nick-03`. Same original
  input snapshot as previous trial; source/context hashes intact and all 41 original index entries
  retained. Runner snapshots match dispatched hashes. Report matches finish-tool submission.
- Remaining weaknesses: useful recording candidates left unfollowed; historical changes and
  rounded metadata still called conflicts; inherited alias wording; an outside-window row; minor
  quote normalization and imprecise tool-process description. Source overview is selective reading,
  not proof of full evidence consumption. No production promotion or general quality guarantee.
- Local traces and costs retained; Langfuse configured/flushed, known model-name parsing warning
  persists; cloud completeness unverified. Offline checks remain the 13 passing focused tests and
  scoped Ruff from preparation. No additional paid runs or unrelated changes. Founder review next.

## Focused media fixes (subsequently authorized)

- Founder authorized recording extraction, actionable candidate handoff and follow-through
  instructions. Shared resolver now reads explicit Twitter/Open Graph media metadata, excludes
  analytics/non-HTTP frames, deduplicates YouTube forms and preserves typed genuine choices with
  extraction provenance. No source verification or transcript-completeness gate added.
- Opt-in trial adapter returns candidates and next actions inline; continuation records failed
  transcription distinctly, preserving existing provider raw/ledger paths and avoiding blind
  retries of uncertain paid outcomes. New trial preparations use fresh-fields-v2 and the exact
  media-follow-through guide. No active profile, application/fleet or unrelated edits.
- 42 distinct focused offline tests passed. Initial Ruff long-string findings were fixed;
  final scoped Ruff and diff checks passed. Exact old HTML replays establish extraction for
  all three examples (downstream responses synthetic, explicitly labelled).
- Direct live probe at `.artifacts/person-media-followthrough-20260924/run-01` recovered and
  transcribed the podcast via configured native Gemini: 130.25s, $0.02012750, no unpriced rows.
  Original response, transcript, raw recording, ledger, trace linkage and runner snapshots saved.
  YouTube reached a separate existing public-access check and could not continue; the other
  podcast retains real audio/video choices. No Exa/AI Ark/research-agent calls in this probe.
- The probe audit documents that transcription lacks speaker labels/timestamps and has not
  been fully checked against audio; no claim of complete coverage. Local traces retained and
  Langfuse configured/flushed; cloud completeness unverified. A full agent behavior replay with
  the new guidance remains untested. Earlier completed research artifacts are unchanged.
