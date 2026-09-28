# Focused account narrative reconciliation

Implemented locally on 2026-09-28. This changes the continuation for account research profiles
that own their narratives (recipe revision 20 onward). It does not change research acquisition,
dossier authorship, claim import, or contact narrative ownership. Earlier profiles retain their
researcher continuation.

## Trigger and ownership

A complete account or person dossier import records `(job_id, dossier_version, artifact_key)`
in the import transaction. After the initial account job settles, reconciliation waits until each
currently nominated person has either committed an import or reached a terminal outcome. Person
narrative publication and final agent reporting are not prerequisites. A failed person remains a
visible partial result; its absence does not prevent using the other committed findings.

The latest account generation in the same workspace/project/account/context is eligible. The
fleet work ID is stable across those generations, so the existing lease mechanism serializes
editorial work. The worker checks the lease before preparing a packet and before publishing.
Suspension, privacy stop, and replacement by a newer run prevent publication.

## Deterministic preparation

`quality_reconciliation.prepare` compares the current scoped claim IDs, quality revisions,
conclusions and supersession references with the previous completed snapshot. The first pass
starts from account-page dependencies and considers the available person findings. Later passes
consider new, corrected, withdrawn or removed claims. Status-only signals can settle without a
model call.

Candidate sections come from registered section recipes and generic topic/section hints. Existing
sections that cite changed evidence are always candidates. Unknown metadata falls back to all
owned account sections, rather than silently discarding a finding. This routing is conservative;
its editorial precision and packet size still need measurement with real saved research.

The packet contains changed findings, related account findings, existing candidate sections,
linked duplicate/conflict/supersession findings, person delegation briefs and pinned seller,
product, ICP and persona documents. It preserves finding wording, evidence spans, URLs and
qualifications. It omits the duplicated import-audit copy of each finding. Claims receive exact
request-local C aliases, with a separate retained alias-to-claim mapping. The current packet is the primary working set; no wholesale source-inventory or dossier reread is required.

The exact system instruction and approved editorial guidance are saved with the packet. Retries
reuse those instructions and aliases, even if files subsequently change.

## Editorial call and publication

The original account researcher continues through the shared Deep Agents runtime and LangGraph
checkpointer. The runtime reads the settled account graph state through `aget_state`, seeds a new
tracked reconciliation execution using `aupdate_state`, and carries native private compaction state
through `Command(update=...)`. It preserves messages, the framework summary, working notes and
readable spill files. The original finalized execution remains unchanged. Redelivery resumes the
new checkpoint rather than appending history twice. Missing or unsettled history and mismatched
workspace/project/profile fail explicitly instead of silently starting fresh research.

The model ID comes from the original account execution's model-call journal, including publication
provenance. Reasoning effort still uses the account role's current configuration; historical effort
is not independently pinned by this change. The separate display-model leaf is no longer used by
the production reconciliation driver. Its helper remains available to historical replay scripts.

The phase mounts the compact packet, exact editorial instructions and generated JSON Schema under
`/work/reconciliation/`. The researcher writes `/outputs/reconciliation.json` and calls
`finalize_turn`. Filesystem reads/writes and native planning remain available; acquisition, claim
writes, nominations and direct page publication are excluded from the governed tool surface.
The output contains complete replacement sections or an empty updates list. Person claims remain
person-owned and are cited directly; seller relevance remains narrative inference.

The same typed nested narrative models generate the schema and validate the submission. Field-path
errors return through the native tool loop, allowing up to ten finalization repairs. This is
schema validation with agent repair, not a claim of provider-constrained decoding. Rejected
submissions do not publish partial updates or restart research.

The response is retained before publication. Validation rejects unknown aliases, unavailable
citations, duplicate/unrequested sections, unsupported contact references and uncited non-gap
sentences. The shared page writer retains existing attribution, policy and evidence checks.
Publication additionally compares the cited claim revisions and current section identities with
the prepared snapshot. It will not overwrite an independently edited section or publish an edit
based on changed evidence. Erased/expired packet access is checked again after generation.

Only affected account sections are stored. Contact pages, claims and dossiers are not rewritten.
Page freshness now depends on each section's actual cited claims and contact relationships,
alongside its context, recipe and policy. Unrelated account narrative writes do not stale contact
pages; actual evidence changes still do.

## Recovery and bookkeeping

`arv2_narrative_reconciliation` retains packet, response, input versions, section versions and
prepared/generated/completed/failed state. Publication and marking the captured revision processed
commit together. A newer revision does not invalidate successfully processed older inputs; the
newer inputs remain pending. Prepared/generated work is offered before a newer snapshot, avoiding
abandonment of a paid response when concurrent findings arrive.

Transient connection/serialization/deadlock errors requeue the checkpoint. A retained response
can be published without calling the model again. Exhausted agent repairs or incompatible evidence changes
are surfaced as failed editorial work and needs-review state; they do not automatically buy the
same call repeatedly. A no-op does not certify missing original account pages or stale citations.
Original job finalizations stay immutable. Shared execution events record the editorial lifecycle.

External requests cannot be guaranteed exactly once: a crash after provider completion but before
retaining its response can require another call. A saved response is reused on publication retry.

## Timing and observability

The shared agent runtime records model calls, governed tool activity, provider cost/tokens and
Langfuse observations. An outer reconciliation span carries job, generation, execution and input revision.
The small work receipt points to the durable packet/response and reports section count and timings.
Logs separate preparation, generation-and-save, and publication. `target_missed` records elapsed
work exceeding 60 seconds; it is a performance measurement, not a new pipeline timeout. Existing
provider transport timeouts/retry policy remain in force.

## Rollout and validation

Apply migration `f3eb43c7808f` before starting workers with this code. Existing historical runs are
not rewritten or restarted. Older completed imports have no readiness marker until replayed through
finish_dossier; their terminal job outcome remains a readiness fallback.

Offline tests cover batching, independent contact completion, scoped snapshots, stable fleet leases,
publication retry, late inputs, no-op settlement, corrected evidence, erasure, ownership, citations,
provider cost/trace wiring and native revision-24 account/person narrative regressions. Tests use a
separate throwaway database. The migration passes up/down/up and has a single head.

A paid saved-data replay remains necessary to establish editorial quality, actual packet size,
provider cost and the under-60-second target. No paid calls or live fleet workers were started for
this implementation. The prior person final-report validation defect is a separate issue.

### Native continuation verification (2026-09-28)

Twenty focused tests pass, including continuation against both LangGraph InMemorySaver and
AsyncPostgresSaver in a dedicated throwaway database. They cover native summary restoration,
working-note access, malformed submission feedback and correction, no-op and actual publication,
original checkpoint preservation and replay without further model calls. The broader research and
runtime regression suite has 69 passing tests and two Stage-0 failures reproduced against the
unchanged HEAD runtime. Native checkpoint hydration emits nested Pydantic serialization warnings;
those did not prevent successful continuation. Paid model acceptance remains pending.
