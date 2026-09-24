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
