# ARV2 — Eve.dev framework decision note

**Status:** decision note for the founders, 2026-08-24. Context: a ChatGPT-agent review of
Eve.dev (Vercel's beta, Apache-2.0, TypeScript, filesystem-first durable-agent framework) asked
whether Clue's account-research deep agent should be built on it. Claims below re-verified
directly against eve.dev docs (landing, docs index, execution-model-and-durability) on 2026-08-24.

## Verdict

**Do not adopt Eve. Build ARV2 on the existing platform runtime, per the ratified runbook.**
The reviewer's own decision rule settles it: *"If Clue's backend is primarily Python and already
has LangGraph code, do not introduce a separate Node/Vercel runtime solely to adopt Eve."* Clue's
backend is Python, LangGraph/deepagents, with a live durable fleet. The review was written
without repo context; with it, every capability Eve offers is either already built here or is one
Eve explicitly does not provide.

## The mapping the reviewer couldn't see

| Eve concept (verified) | Clue equivalent (built, live-tested) |
|---|---|
| Sessions / turns / durable steps on the Workflow SDK; "completed steps never re-run; eve replays the recorded result. A step interrupted mid-execution re-runs" | `entity_research_job` + `entity_research_agent_turn` journal + `AsyncPostgresSaver` checkpoints; identical replay semantics; interrupted-step idempotency via `external_research` snapshot digests |
| Filesystem-first: markdown instructions, skills/subagents as directories | The versioned catalog (`platform/agents/catalog/**` — profile.md / prompt.md / SKILL.md, sha-pinned) |
| Parked work (approvals, OAuth, subagent completion; no compute held) | `WAITING_EXTERNAL` waits, human gates (`agent_gate`), fleet wake sources |
| Subagents: isolated context/session/sandbox, "nothing crosses implicitly" | Deepagent delegation + fleet dispatch; workers return claim references, isolated jobs |
| Sandboxes seeded from `agent/sandbox/workspace/` | `CLUE_AGENT_WORKSPACE_ROOT` isolated per-execution workspace, read-only materialized resources |
| Approvals built in | Product/ICP/discovery/launch human-authority chain |
| Evals reference | M9.6 eval harness + golden fixtures + regression gate |

**What Eve does NOT provide (confirmed absent from its docs), which Clue already has:** caching
(artifact cache, snapshot idempotency, reuse windows), tenant isolation (fail-closed
`workspace_id` everywhere), rate limiting (M2 Redis token bucket, per-provider concurrency),
audit logs (append-only journals, gate decisions, spend ledger). The reviewer assigns exactly
these to "Clue-authored wrappers" — i.e. even under Eve, we'd rebuild our substrate around it.

## Where the review is right (and already encoded in ARV2)

Own the durable data outside the framework (= the claim store); narrow Clue-authored tool
wrappers, never raw provider API surface (= the ARV2 tool surface); idempotency keys on every
provider call and DB write (= snapshot digests + append-only claims); coordinator + verifier
roles, no subagent swarm (= one agent per account + the fabrication-audit skill; with our charter
amendment that the verifier annotates, never vetoes); prove it on ~10 real accounts on accuracy /
citation coverage / latency / cost before standardizing (= the runbook exit gates, widened).

## Costs of the proposed Eve spike (why we skip it)

Building Eve's Exa/Apollo/claim-write tools duplicates ARV2 Day-1/2 in TypeScript as throwaway
code; a second runtime + credential surface; tenant research data transiting a Vercel-hosted
agent (posture regression vs fail-closed workspace scoping); beta APIs ("5.0.0-beta Workflow
protocol") under a moving framework. The measurable part of the spike — the 10-account benchmark
— is kept, pointed at ARV2 itself.

## Two Eve ideas worth adopting later (backlog, not build scope)

1. **Schedules** (cron-frontmatter recurring jobs) — the natural shape for freshness-driven
   re-research when M7-era `re_research_candidate` consumption gets an owner.
2. **Evals as a first-class directory convention** — point M9.6 machinery at ARV2's dossier
   acceptance fixtures so every steering change replays the two Insight Health accounts.
