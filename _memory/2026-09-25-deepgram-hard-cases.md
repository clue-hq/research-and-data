# Deepgram harder recordings — standalone follow-up

- Founder authorized the proposed harder-recording tests. Ran three isolated Deepgram URL
  calls with the existing Nova-3/v2/English settings, no reference/keyterm seeding, same
  model builds reported. No production/fleet/database changes.
- Cases: full public 2h17m interview, plus public AMI ES2008a four-speaker meeting captured
  with close versus room microphones. The paired recordings isolate acoustics; this is not
  three independent conversations or an accent-specific benchmark.
- All three responses succeeded, matched the prepared input checksum and labelled/timed
  every returned word. Long interview: 25,403 words, 2 clusters; accuracy not reference-scored.
- Added `scripts/evaluate_deepgram_ami.py` and focused parsing/timing tests. MeetEval 0.4.3
  installed only in `.artifacts/.../eval-env`; no application dependency changes. Public
  manual annotations stay local, never supplied to Deepgram. Two untimed reference words
  retained for cpWER and omitted from timing; initial parser KeyError corrected accordingly.
- 2,543 normalized reference words. Close recording: 2,261 provider words, 5 clusters,
  cpWER 27.4479% (698 errors). Room: 1,601 words, 4 clusters, cpWER 43.9638% (1,118 errors).
  cpWER combines wording and speaker assignment; do not describe this as pure WER/DER.
- Matched-sequence timing median about 70ms, p90 about 150ms. This excludes unmatched words;
  it cannot establish whole-recording alignment accuracy. Room output omitted full passages.
- All raw/results/provenance/reference scores and paired review clips preserved under
  `.artifacts/deepgram-hard-cases-20260925/`; summary in BENCHMARK.md. Tracked method/results
  documentation: `docs/experiments/deepgram-hard-cases.md`.
- Three focused evaluator tests and three MeetEval sanity cases passed; scoped Ruff passed.
  No paid retries in this round. Dollar costs remain unknown, not presumed zero from credits.
- Practical finding: successful JSON with all labels/timestamps is insufficient quality
  evidence. Long clean audio coverage is promising; harder conversational audio loses words
  and fragments speakers. Compare another provider on the same recordings before choosing
  a fallback, and perform listening review before verified named-speaker quotations.
