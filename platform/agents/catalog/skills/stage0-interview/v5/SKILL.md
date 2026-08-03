---
schema_version: "1"
kind: skill
name: stage0-interview
version: v5
summary: Run gap-led Stage 0 from URL or current truth, route every information species, and stop at human and deterministic gates.
roles:
  - head_of_abm
readiness_requirements:
  - stage0.project_product_confirmed
  - stage0.client_knowledge_sufficient
  - stage0.icp_confirmed
tools:
  - name: evaluate_stage0_readiness
    version: "1"
    input_schema_sha256: 5cd02f910efd421231292af6b253bb18c1c4652c01e0febe408b5278857fbf85
    output_schema_sha256: a4b0ee832c7a8fda7f62e811ab2651de2255b2d3b5020e29ce3b73b5d2f1e56b
  - name: propose_field
    version: "1"
    input_schema_sha256: 04f91da8afd3ab16b736d33d54c96b0a90dd34e4ecebacfb0db3c34a451a3aac
    output_schema_sha256: 4ca8488a8703406e64e4a8ba49bc17c5da2aa78f7f5cce104343eb77d68e3a84
  - name: propose_source
    version: "1"
    input_schema_sha256: a4590108f093a8a424a8b1c48b2cc0670527c1b7a3f608e70babdd32ae9f1f5b
    output_schema_sha256: 708d9b5075c72103232daa51c12cbb83a5fe5bdf638bfa79659193f2324a851e
  - name: record_interview_answer
    version: "1"
    input_schema_sha256: 17e741cba55facd01ada70edfdde8f4a903ef8a391b5cb17d54db06073d49a24
    output_schema_sha256: 5f0e0fe7baad009e16af713744ef7abbc390615d627a69f5f25c43eb8734e7a8
  - name: start_confirmed_project_run
    version: "1"
    input_schema_sha256: a59f57b070c500454c4255b4588ee39054e27bf692f22c88aca8c50c0ef6b7a0
    output_schema_sha256: 4b621e2cbd05d503e2433b7698d87e9d7d69956d8a94084225ca6d5b13e122f9
  - name: start_recon
    version: "1"
    input_schema_sha256: a69370b41efe2892620a0080b773dd94eddf640086911e7dbaec23b0c31f789e
    output_schema_sha256: a999f4e0508d93733369d35bb2d7f9c621ebf2f0fe8405fc7c605206b3d2eba4
  - name: submit_ingestion
    version: "1"
    input_schema_sha256: affae45f798ec731c0a2495f50f037d4bdd22debd6eb32c2b903d19422330da1
    output_schema_sha256: 8e2acc7a8819cb1eaff07dc0fa6f8a90b824572e5fb39cbf34a5380f3f1319bf
  - name: submit_onboarding_input
    version: "1"
    input_schema_sha256: 9a1f4eda9363e2a68c217e81a7a2591a081f4528cf57ca5c81a7972c3076a080
    output_schema_sha256: db82dc8abe7cbb3d2e7537ad18328eb29e78c9c1e1671c2bd5ba3b370d818ecf
  - name: synthesize_icps
    version: "1"
    input_schema_sha256: 6872dd97eacfd19f02726a49b9d3fdb6f23f81ffde23ebed8971200ed31f50b1
    output_schema_sha256: a745ce146398d43c80bc8fdd220d86ec5c1fe70972f228f312f18d1b441997f3
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Stage 0 vertical

Open this skill when the project is in Stage 0 or the user is establishing product and ICP truth.
Do not preload or apply it to unrelated stages.

## 1. Establish current truth

Read the supplied stage, product, readiness, project, and focus context before asking anything.
Separate known-current, known-stale, contradicted, missing, and merely assumed values.

- URL-only: capture the URL as onboarding input, then start one governed recon. Fast recon gives
  the conversational starting point; background recon may continue without blocking useful
  questions.
- Known product: show the current product candidate and ask the human to confirm or correct it.
- Stale product: name the stale evidence and ask for the smallest refresh needed.
- Contradiction: preserve the new exact quote and route it as a correction; do not silently rewrite
  the prior claim or memory.

## 2. Ask from gaps, never from a questionnaire

Use deterministic readiness results and current evidence to choose the next material question.
Ask one compact question when possible. A question is material only if its answer can change:

- which product the project represents;
- a motion-specific ICP boundary or exclusion;
- a readiness metric or evidence floor;
- a missing source/field proposal;
- a project-specific constraint needed to start the confirmed run.

Do not ask for facts already present and current. Do not enumerate every possible ICP dimension.
Your judgment decides what is useful to ask; it does not decide readiness.

## 3. Preserve and route information by species

Capture the exact user turn as an artifact before routing statements.

- **Claim:** a verifiable fact, with exact quote offsets, entity, registered field, evidence, and
  correction lineage when applicable.
- **Memory:** an advisory preference or behavioral learning through the scoped-memory seam. Memory
  never becomes fact.
- **Project intent:** a choice or constraint local to this project.
- **Field/source proposal:** a novel typed field or source goes through `propose_field` or
  `propose_source`; proposal creation grants no promotion or trust authority.
- **Artifact/upload:** submit an already captured workspace artifact through `submit_ingestion`
  with explicit material context. Raw bytes arrive through the human/API upload boundary, not
  through model-controlled filesystem invention.
- **Unmapped evidence:** preserve it as durable interview evidence and surface the mapping gap.

Never paraphrase a user statement as its canonical evidence. Never use a proposal id as if it were
an approved field/source. Sensitive/contact data remains subject to its existing gates.

## 3a. Report receipts, never claim capture

A durable write exists only when a governed tool returned a receipt for it. Your own summary of the
conversation is not a record of anything.

- Do not tell the human that something was captured, recorded, saved, stored, logged, noted, or is
  "now project state" unless you are reporting a routing receipt `record_interview_answer` actually
  returned to you on this turn. Name what the receipt contains — statement ids, claim refs, memory
  refs, project-state refs — rather than asserting the effect.
- When you did not route the turn, say exactly that: what you understood, what you did not record,
  and what you still need. An honest "not yet recorded" is correct; an unbacked "captured" is the
  one failure that is never acceptable.
- Route every substantive user turn before you finish it. If nothing in the turn is material — a
  greeting, a meta-question about the process, an instruction to you — route it explicitly with
  route `unmapped` (route key plus the exact quote offsets) instead of routing nothing. `unmapped`
  is a real, honest answer, not a fallback for laziness.
- A `completed` or `awaiting_input` finalization of a substantive turn that produced no routing
  receipt is refused by the platform, and the refusal is visible to you. Route the turn — including
  via `unmapped` — and finalize again rather than restating the same claim.

## 3b. Authoring rules for routing

The tool schema states each rule on the field it governs; these are the same rules at procedure
level, with the reason they exist.

- **Quote, never summarize.** A claim's `value` must be copied verbatim out of the exact span
  `answer[quote_start:quote_end]`. Facts here are evidence-locked to the user's own words, so a
  tidied-up paraphrase is refused — narrow the offsets to the words that state the fact instead of
  rewording them.
- **Offsets are exact character positions** into the captured `answer` you were given: `quote_start`
  inclusive, `quote_end` exclusive, 0-based. Send the answer back byte-identical; it is hash-checked
  against the captured turn, so retyping, trimming, or re-wrapping it fails.
- **One statement per material fact.** Split a turn that carries several facts, a preference, and a
  project decision into separate statements with their own quotes, rather than one broad statement
  over the whole turn. Each species then lands where it belongs and each fact carries its own
  evidence.
- **Route `unmapped` when unsure.** If a part of the turn is material but you cannot map it to a
  registered field, a memory, a project decision, or a proposal, route it `unmapped` with its exact
  quote. That preserves the evidence and surfaces the mapping gap; guessing a field key or inventing
  a claim to look complete is the failure.
- **Corrections carry lineage.** When the user restates or contradicts something already routed,
  reference the prior statement or claim rather than writing a fresh, unrelated one — and a claim
  correction must keep the same entity and field key.
- **A refusal is information, not a dead end.** If a governed tool refuses your call, you see why.
  Fix the offending statement — usually by re-quoting exactly — and call again; do not restate the
  fact in prose and move on.

## 4. Synthesize and stop at human gates

After enough grounded product context exists, synthesize ICP options. Present assumptions,
exclusions, missing evidence, and the proposed motion. The human alone:

- confirms the project product;
- confirms or edits the ICP;
- records a readiness override.

These tools are intentionally absent. Ask for the action rather than simulating it.

Evaluate product, client-knowledge, and ICP/discovery readiness separately. Pass exact claim,
memory, artifact, gap, proposal, and ingestion references into readiness evaluation. Your
`agent_sufficiency_status` is advisory and cannot turn a failing deterministic result into ready.

Call `start_confirmed_project_run` only when durable product and ICP confirmations exist and the
discovery readiness decision is ready or has a durable human override. The tool and Recipe #1
router revalidate every lineage and gate. If they refuse, report the refusal and remain
`awaiting_input` or `blocked`; never claim the project started.
