# Deepgram harder-recording comparison

Executed 2026-09-25 as an isolated follow-up to the standalone transcription trial.
Results: `.artifacts/deepgram-hard-cases-20260925/BENCHMARK.md`.

## Cases and controls

1. Full Lex Fridman / Demis Hassabis interview, episode 299, approximately 2h17m.
   [Publisher episode and MP3 link](https://lexfridman.com/demis-hassabis/).
2. AMI ES2008a, approximately 17m23s, four-person design-team meeting, mixed close microphones.
3. The same meeting's Array1-01 room microphone. This isolates the acquisition condition
   while retaining the same reference conversation; it is not a second independent meeting.

[AMI corpus](https://groups.inf.ed.ac.uk/ami/corpus/) provides synchronized microphone
recordings and manual annotations under CC BY 4.0. Attribution: AMI Meeting Corpus,
University of Edinburgh / AMI Consortium. This is a meeting proxy for panel turn-taking,
not a conference-panel recording. The manual word intervals contain 28.93 seconds with
multiple speakers active. Accent-specific performance was not isolated, and room noise
was not assigned a measured SNR.

All three calls used the standalone script's unchanged Nova-3, diarize_model=v2, English,
utterances, punctuation, filler-word settings, smart_format=false, no keyterm hints and
public media URL delivery. Exact request settings, raw responses, original audio checksums,
provider metadata, ledgers and trace references are retained per run. No production changes.

## Reference-backed evaluation

`scripts/evaluate_deepgram_ami.py` reads the **manual** AMI 1.6.2 word XML files and the saved
Deepgram `words.json`. It sends nothing to Deepgram. Install its dependency separately:

```sh
uv venv .artifacts/deepgram-hard-cases-20260925/eval-env
uv pip install --python .artifacts/deepgram-hard-cases-20260925/eval-env/bin/python meeteval==0.4.3

.artifacts/deepgram-hard-cases-20260925/eval-env/bin/python scripts/evaluate_deepgram_ami.py \
  --reference .artifacts/deepgram-hard-cases-20260925/reference \
  --meeting ES2008a --run .artifacts/deepgram-hard-cases-20260925/meeting-close
```

Repeat the evaluation command for `meeting-room`; it performs no network or paid calls.
Reference ZIP provenance and selected XML checksums are saved with the artifacts.

The main measure is [MeetEval's concatenated minimum-permutation WER](https://github.com/fgnt/meeteval).
It finds the best one-to-one correspondence between reference and predicted speaker streams,
then counts substitutions, insertions and deletions. Additional/missing speakers are included.
Consequently cpWER measures **wording and speaker attribution together**, not pure recognition
accuracy or diarization error rate. It must not be converted into a blanket accuracy claim.

Normalization lowercases, removes punctuation, and normalizes curly apostrophes. Fillers,
contractions and numeral representations remain as supplied; no spelling corrections or
LLM transformations. Two reference words lack timestamps: they remain in cpWER and are
excluded from timing diagnostics. Non-lexical vocal-event tags are not counted as words.

The additional timing diagnostic compares starts/ends of exact matching sequences of at
least three words within matched speaker streams. This covers only correctly matched
portions and may match repetitive language imperfectly. Its median/p90 offsets are not
an all-word timestamp accuracy guarantee or a listening audit.

## Observed result

| Case | Returned words | Speaker clusters | cpWER |
|---|---:|---:|---:|
| Long interview | 25,403 | 2 | Not scored: no human reference used |
| Meeting, close microphones | 2,261 | 5 for 4 reference speakers | 27.45% |
| Meeting, room microphone | 1,601 | 4 for 4 reference speakers | 43.96% |

Every returned word had timing and a speaker label, and all three input checksums matched.
Those structural successes did not guarantee content preservation. In the 13:00–13:30
meeting window, the human reference has 73 normalized words, the close recording's output
has 65 provider words, and the room recording's output has none. The latter metric comparison
uses different normalization counts for this illustrative window, so it is not a WER score.
Paired original-audio review clips are saved for this and two other windows.

On exactly matched sequences, median start offsets were approximately 70ms in both meeting
conditions. However, the room response omitted substantially more material. Good timestamps
for returned words cannot detect or compensate for speech that was never transcribed.

The long interview completed without an apparent late cutoff, but it has not received a
ground-truth accuracy or speaker-continuity audit. The two meeting recordings cover one
public scenario only; they do not establish population-level performance or unseen-data quality.
No provider setting was tuned against the reference transcript during these calls.
