# Discovery-first person research trial

Status: two isolated live trials completed on 24 September 2026; founder quality review remains.
The [saved run and comparison](../../../../.artifacts/person-discovery-trial-20260924/nick-02/COMPARISON.md)
record discovery gains, source-review omissions and incomplete media follow-through. This is not
production acceptance or evidence of a general quality improvement rate.
This experiment is separate from the parent task's saved-response continuation. The shared
runner retains its original adapter by default; the focused follow-up adds an optional adapter
injection seam. Active person profiles, fleet workers, claim writing and page synthesis are unchanged.

## What is being tested

Can the configured person Deep Agent choose complementary ordinary searches, read and consolidate
their results, write a well-informed comprehensive Exa assignment, then use source review and
adaptive follow-ups to produce a richer person investigation?

The agent chooses queries, source reads, sequencing and stopping. There is no hardcoded eleven-call
pipeline, person-specific discovery hint or requirement to fill every category. The intended first
deep call still carries the complete person charter; narrower follow-ups expand meaningful leads.
Ordinary preliminary searches and `additional_queries` inside the deep request are distinct.

## Input quality and exact instructions

Preparation copies only files declared in the original pre-person-research snapshot's manifest,
verifying their bytes and the pinned ICP, persona and seller document references. It preserves:

- The account-authored person brief, selected identity and source references.
- The Head-of-ABM mission, seller documents, pinned project definitions and account findings.
- Complete retained account source fields with paged navigation.
- The complete detailed person charter and unchanged Exa system prompt.

No previous person Exa output, PoC final person report, evaluation comparison, model scratch or
subsequent continuation results are added. Use the original request-preview snapshot as `--context`,
not a completed continuation directory. These are retained inputs, not a newly exported application
snapshot. Sparse personas and dated/incorrect retained interpretations remain explicit limitations.

The only instruction changes are in this trial's copies:

1. The skill's short optional-preparation paragraph is replaced with the exact
   [discovery instructions](discovery-instructions.md).
2. The person-agent prompt points to this preliminary discovery procedure.
3. The isolated task explains the available research tools and output; it does not add a lesson
   on Deep Agents' built-in filesystem tools.

The agent still receives the full source-review/follow-up guidance from the existing person skill.
The prepared `person-system.actual.md`, `opening-message.md` and `instructions/` contain the exact
final texts, not a summary. `manifest.json` records input, prompt and selected runner digests.
Conflicting old preparation wording causes preparation to fail visibly if the base text changes.

## Runtime and evidence

`scripts/trial_person_discovery.py` reuses `scripts/continue_person_research.py` for the real
`create_deep_agent`, configured `ARV2_PERSON_AGENT_MODEL`, production Exa/media clients, provider
ledger, raw response storage, request reuse, local callbacks and Langfuse tracing. There is no
parallel provider implementation. Trace names remain those of the shared continuation runner;
the manifest, actual prompts and distinct output directory identify this experiment.

Tools cover ordinary Exa searches, page reads, Exa deep research and supported public media
resolution/transcription. Independent acquisitions can overlap, with three provider slots.
The existing runtime backstops remain 200 graph steps and 2,400 seconds; these are operational
limits, not a quality threshold or 200 model turns. No paid enrichment or application writes.

Original results remain intact, including source text, highlights, entities and extra links.
Repeated URLs may be consolidated in the agent's notes but original records are not deleted.
The researcher writes `/scratch/pre-deep-review.md` before its initial deep request so we can
inspect which evidence informed its assignment. This is prompt guidance, not a completion gate.

Preparation is offline. The explicit `run` command invokes paid configured OpenRouter/Exa and,
when selected by the agent, media providers, with configured tracing. It refuses to restart an
already-dispatched output directory. New experiments use new output directories.

```sh
.venv/bin/python scripts/trial_person_discovery.py prepare \
  --context .artifacts/person-exa-comparison-20260924/nick-01 \
  --output .artifacts/person-discovery-trial-20260924/nick-01
```

After reviewing the prepared input and instruction package, the live command is:

```sh
.venv/bin/python scripts/trial_person_discovery.py run \
  --output .artifacts/person-discovery-trial-20260924/nick-01
```

## What we review after a live run

- Input fidelity: which brief, original documents and source pages the agent actually read.
- Search breadth: distinct useful angles; personal and earlier-career exploration alongside work.
- Handoff: source-linked findings and concrete questions in `pre-deep-review.md`; complete charter
  specificity and meaningful leads in the exact first Exa wire request.
- Source use: whether the final report preserves useful source-only details and accurately
  distinguishes speaker, current metadata, historical dates and uncertain namesake associations.
- Adaptation: subsequent questions change with evidence; no repetitive searches or unexamined
  acquired leads presented as a thin footprint.
- Output: readable `findings.md`, inline URLs, attributable quotes, useful personal depth,
  remaining gaps and honest limitations. This report is research, not claim/page synthesis.
- Efficiency: complete tool/model event history, request purposes, provider responses and ledger,
  wall time, model usage/cost where reported and `trace-linkage.json`.

Compare against the prior initial Nick dossier, saved-response continuation and historical PoC.
Keep those comparison materials outside the agent's input root. Judge coverage and fidelity with
the founder; the historical comparison is not a controlled provider-variance experiment. Do not
call offline isolation/retention checks a proof of research quality. Do not promote this into the
production lane until the actual input, behavior and output have been reviewed.

## Focused follow-up: fresh source fields

The founder approved another trial with two changes: instructions to inspect new result fields
on previously read URLs, and a tool-result overview exposing verbatim highlights. The exact new
instructions are [fresh-source-review.md](fresh-source-review.md). Preparation selects this mode
with `--fresh-source-review`; the selected mode is recorded in the immutable prepared manifest.

`scripts/person_trial_source_review.py` extends the shared acquisition adapter. It compares field
fingerprints for captures of the same exact URL within this trial; that is capture history, not
proof of agent reading. It returns the first ten source overviews inline, with continued pages
for the rest and full source references throughout. Original provider responses and fields remain
unchanged. No project-specific hints or evaluation answers are added.

The shared runner accepts an optional acquisition factory, defaulting to its original adapter.
Only this opt-in trial uses the overview adapter. The seller/person brief, detailed charter, Exa
system, provider options, media implementation and production profiles are unchanged.

Completed live attempt: `.artifacts/person-discovery-trial-20260924/nick-03`. Offline checks: 13
tests passed. A saved-response handoff replay is retained outside the agent input root at
`.artifacts/person-discovery-trial-20260924/review-replay-v2.json`; this proves visibility of the
previously missed field, not that a model will investigate or faithfully report it.

The [focused trial comparison](../../../../.artifacts/person-discovery-trial-20260924/nick-03/COMPARISON.md)
records 573.65 seconds and $1.931550 total recorded cost. The agent reviewed all thirty source
overviews and retained the highlight-only recommendation. It expanded personal findings through
its own follow-ups. CocktailGPT appeared in the new dossier without its supporting source field;
the agent investigated and retained that uncertainty. Media follow-through and false conflict
framing remain incomplete. Live retrieval and query choices varied, so this is not an identical-
response causal A/B test. Source reports, exact prompts, provider results and traces are retained.

## Focused media follow-through fixes

New preparations with `--fresh-source-review` use `fresh-fields-v2` and include the exact
[media follow-through instructions](media-follow-through.md). Original prepared trials remain
unchanged. The adapter now exposes recording candidates, extraction origins and next actions
inline; the shared resolver recognizes explicit player/stream metadata and excludes analytics
frames. Real multiple-recording choices remain for the agent. Shared continuation results also
distinguish failed transcription from an unattempted recording.

The [focused verification report](../../../../.artifacts/person-media-followthrough-20260924/run-01/REPORT.md)
records 42 distinct passing offline tests, three saved-page replays and a live direct-tool probe.
The previously missed podcast MP3 produced a 46,997-character transcript ($0.02012750 recorded
provider cost). Oktane instead reached the existing YouTube public-access check and could not
continue. Modern Bar Cart retained its two choices. These direct checks do not establish that
the agent autonomously follows the new guidance; that replay remains a separate review step.
No active production agent profile was changed; the resolver fix is shared code used by the lane.
