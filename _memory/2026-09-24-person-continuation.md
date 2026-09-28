# Isolated person source continuation — 2026-09-24

- Founder authorized implementing and running the saved-response continuation. New script
  `scripts/continue_person_research.py` uses the configured person Deep Agent, current draft
  skill/charter, unchanged prior delegation/context and the latest supplied response. No PoC
  final answer or comparison notes are mounted. Production catalog selection remains unchanged.
- Operations: Exa search, contents, focused deep follow-up; shared public-media resolver and
  configured native Gemini transcription. Full provider rows (including entities/extras), raw
  responses, requests, source paths, provider ledger and model/Langfuse traces are retained.
- Complete result pages and inherited account sources share an index; original inputs are
  read-only to the agent, with scratch notes allowed. Exact repeated requests reuse receipts;
  unknown outcomes are not automatically repurchased. No application DB/fleet/claim/page writes.
- Founder asked about Exa multimedia. Official API documents extras.links/imageLinks, not a
  separate multimedia flag. Added optional extras forwarding to shared search/contents client;
  defaults unchanged. Continuation requests 10 page links and 3 image links per result. This
  exposes candidate links; native media reading remains a separate operation.
- Offline checks: 36 focused tests pass (retention, pagination, isolation, request reuse,
  uncertain outcomes, media dispatch, Exa request contracts). Ruff clean. Initial test fixture
  omitted ProviderCaller.now; corrected before live execution. No provider calls yet.
- First prepared directory predates extras; preserve as preparation-only. Latest prepared
  attempt is under `.artifacts/person-exa-comparison-20260924/`; exact trial handle and live
  outcome will be appended after dispatch. Existing trials remain immutable.

- Final prepared attempt: `nick-continuation-03` (01/02 preparation-only). Initial dispatch was
  rejected by automatic approval review before execution: exact multi-provider transmission of
  retained seller/ICP/persona/account context needed explicit approval. Asked the founder for
  that approval; no workaround, provider call or model execution occurred. Live run pending.

## Live completion and review

- Founder explicitly approved the exact payload/provider set; the same prepared `-03` attempt
  completed in 437.83s, 29 configured person-model calls. New metered spend $1.75365760:
  $1.665156 model + $0.08850160 providers. No initial deep request repurchased; the agent chose
  10 searches, 10 page reads and 3 media operations. One recording was transcribed successfully.
- Preserved unchanged generated findings, linked reading copy, complete provider source fields,
  transcript, actual prompts/queries, raw records, cost ledger, events, trace linkage and detailed
  COMPARISON.md under `nick-continuation-03`. Live runner snapshotted from checkpoint 8ebe763bf.
- Meaningful recovery of missed personal-project evidence and long-form voice; unsupported
  same-name attribution corrected. Remaining gaps: neglected project/career-transition lead,
  inconsistent interpretation of crawl-time metadata, inferred alias/age language, imperfect
  quote literalness and inefficient priority on low-value third-party claims. Not full PoC parity.
- 94 file reads had no identical argument tuple; first follow-up at 74.641s. Model intervals
  total ~370.9s; final drafting ~115.4s. Input growth/read granularity are latency concerns.
- Confirmed all 20 actual Exa requests carry requested extras (10 links, 3 images). Returned
  link/image metadata is retained; no separate public multimedia flag was verified.
- Langfuse installed/flushed and trace IDs retained. Callback logged model-name parsing warning;
  gateway/local receipts have exact model/cost. Cloud completeness not independently inspected.
- Corrected media candidate serialization after live inspection (Pydantic candidates were
  readable strings, now structured fields). Six focused harness tests pass after this change;
  earlier full affected set was 36 passing tests. Live artifacts deliberately remain unchanged.
- Closing: no application DB/fleet/enrichment/claim/page writes or production prompt activation.
  Research-quality review remains with founder. No automatic rerun or runtime promotion.
