# Zafran advisory flow — one-person live test

September 23, 2026. **Attempt finished; end-to-end narrative acceptance failed.**

The founder requested Zafran only, with exactly one person-research job, using the latest
verification-deferred implementation. This used internal quality profile v4, resource revision six,
on commit `251ad3e82`. The shared launch default remains v2. No application code was changed during
this run. No target research, contacts or target claims were seeded.

## Review the output

- [Actual research-page readout](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/ZAFRAN-RESEARCH.md): empty narrative sections followed by the complete retained findings. This is the real projection, not an independently rewritten dossier.
- [Complete Exa account report](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/EXA-ACCOUNT-REPORT.txt), unchanged: 13,860 characters.
- [Complete Exa person report](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/EXA-PERSON-REPORT-1.txt), unchanged: 11,506 characters.
- [All claims and evidence](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/CLAIM-EVIDENCE-APPENDIX.md).
- [Visibility proof](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/visibility-proof.json), [metrics](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/metrics.json), [raw snapshots](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/snapshots/evidence.json).

## Result

| Measure | Observed result |
| --- | --- |
| Account | Zafran Security, zafran.io |
| Person research jobs | Exactly one: Vari Kaur |
| Account/person job status | Both needs_review, runtime_error |
| Final generation | needs_review, revision 101 reconciled |
| Stored findings | 99: 83 account, 16 person |
| Recorded assessments | 59 supported, 40 qualified; these are source/model assessments |
| Findings visible in projection | All 99 IDs; none restricted or missing |
| Narrative specialist calls | Zero |
| Published narrative pages | Zero of three: overview, insights, contact |
| Contact enrichment | Work email and phone stored |
| Retained sources | 148 web snapshots, 28 provider records, two research reports, eight acquisition gaps |
| Stored media items/transcripts | Zero / zero |
| Artifact integrity | All 1,623 retained artifacts passed SHA256 and byte-size checks |

The deterministic findings section currently repeats the complete account-context findings on
all three page views. This proves visibility, not narrative quality or relevance filtering. The
ordinary factual claim reader returns 59 rows; the advisory research-page projection includes all
99. A zero-page publication count does not mean no findings are readable.

## What failed and why

1. **Finding-write operation keys kill specialist turns.** Durable operation parameters prove that
   a specialist reused `zafran-security-claims` for six different topics, and a continuation used
   the account job ID for seven. Other batches reused a delegation key or the person job ID.
   `submit_proposal` rejects changed content under an existing key. Parallel failures exceed the
   generic governed-tool repair budget, raising out of the specialist and failing its parent.
   This occurred in both account and person research. It is an idempotency/tool-interface defect,
   not a relationship-proof or evidence-quality refusal. Failed batch parameters are retained in
   [the operation audit](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/finding-operation-collisions.json).
2. **Continuation scheduling performs excessive repeat claims.** Fifteen fleet task rows accumulated
   15,877 claim attempts; one continuation row reached 6,469. These are queue attempts, not
   6,469 provider calls. Generation revisions share the same work ID and contend for execution.
   Re-offering without adequate delay/coalescing adds churn. More slots do not speed sequential
   parent/specialist work, and the person job was not initially offered until the account settled.
3. **Person recovery required an operator queue repair.** A suspended person job had a done fleet
   item. At 04:17:38 UTC the same job was re-offered through `DbWorkQueue.enqueue` with
   `reopen_terminal=True`; the saved checkpoint and original allowance were retained. No new person
   job, allowance reset or fresh provider research launch was created. Its later failure was the
   finding-key collision. Network/trace failures occurred around the interruption; the complete
   causal chain of the fleet inconsistency has not been established.
4. **The account hit a separate runtime ceiling.** Its shared allowance reached 30 minutes, while
   dispatch counters were 152/200 account calls and 61/200 person calls. Raising the model-call
   count alone does not remove this limit. The final reconciliation recorded exhaustion and
   settled revision 101 as needs_review. No limit was reset.
5. **Media acquisition still fails before useful ingestion.** A Vimeo result description contained
   binary-looking text and a NUL character; PostgreSQL JSONB rejected it. Other media calls returned
   provider refusals, invalid arguments or an exact-episode requirement. No transcript was retained.
   The provider ledger's `ok` transport/result outcomes do not certify successful media ingestion.
6. **Navigation and subject capability errors remain expensive.** Repeated evidence-index reads
   enlarged model inputs to 177,664 tokens. Agents attempted person-only operations on the account
   and company-only operations on the person. These returned scoped tool errors. No relationship
   verification contract refusal was observed; the new findings that reached storage were accepted.

## What worked

- Autonomous AI Ark SMART discovery selected Vari as the single champion, using the source-reported
  Head of Growth Marketing role, ABM responsibilities and the ABM hiring reporting line.
- Fresh Exa account and person reports, provider profiles, hiring sources and contact enrichment
  were acquired without target-fixture seeding.
- Qualified observations survived storage and appear in the page projection. All finding IDs were
  reconciled against displayed paragraph claim IDs, including email and phone claims.
- Source artifacts and durable model/provider/operation receipts remain available for diagnosis.

## Execution, inputs and tracing

Run `e6f9ee90-452c-56aa-8209-7b507e608dff`; account job
`e1f5c297-cc01-5d0d-b2d0-db0e4151665d`; person job
`904bbca3-b8db-514b-bb12-3962f125eeb3`; generation
`7de92140-f60c-5982-82dc-e6d1dc666648`.

Isolated database `clue_zafran_advisory_one_person_20260923` on local port 59274, private blob and
agent-workspace roots. Ten worker processes with concurrency three each. Launch at 03:53 UTC;
final reconciliation at 04:24 UTC. All workers stopped with exit code zero. All fifteen queue items
are done; no further research is running. A full database dump and final fleet snapshot are retained.

The authored ICP/persona bytes and sourced seller brief match the preceding quality-flow attempt.
The import explicitly pairs ICP/persona lineage and supplies the retained product-evidence document;
it does not copy Zafran research. These input repairs predate this attempt and remain disclosed in
[the manifest](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/manifest.json).

There are 209 completed model receipts totaling **USD 11.654210**, plus 36 provider result receipts
with **USD 0.142000 and 8.1 AI Ark credits**. These are recorded receipts, not invoice reconciliation.
Interrupted dispatch attempts and provider transport outcomes must not be equated with completed
research or fabricated charges.

Langfuse export experienced DNS/timeouts. The final metadata download recovered 4,157 observations;
**199/209** completed model receipts joined by exact trace ID and observation ID. Ten were not found
in that export. Every model receipt carries trace identifiers; local logs/artifacts remain retained.
This is partial cloud trace coverage, not a fully certified cloud trace. Private model deliberation
is not reproduced in the report. See [trace join](/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1/.artifacts/arv4-zafran-advisory-one-person-20260923/trace-model-join.json).

## Comparison and next correction

The preceding strict quality run saved 129 raw claims for an account plus five people and published
four contact pages, several with withheld/gap-only content. This attempt uses one person, plain
findings and an advisory page projection, so raw claim counts and the historical 67-field overlap
score are not directly comparable. This is not a formal PoC accuracy or quality acceptance.

The specific improvement demonstrated here is loss prevention at presentation: every stored finding
is visible. Useful seller-specific narrative quality remains unproven because narrative execution
was never reached. Acquisition and visibility cannot substitute for that result.

The immediate fixes are to give finding writes safe code-owned idempotency (and recoverable collision
handling), stop rapid continuation re-offers, repair suspended-job recovery, and make source navigation
and capability menus fit the actual subject. Media decoding needs a separate focused repair. These
fixes should reuse the retained originals for offline/regression validation before another paid run.
They must not reintroduce relationship proof requirements or hide uncertain findings.
