---
schema_version: "1"
kind: skill
name: stage0-interview
version: v12
summary: Run gap-led Stage 0 from URL or current truth, route every information species, and stop at human and deterministic gates.
roles:
  - head_of_abm
readiness_requirements:
  - stage0.project_product_confirmed
  - stage0.client_knowledge_sufficient
  - stage0.icp_confirmed
tools:
  - name: evaluate_stage0_readiness
    version: "2"
    input_schema_sha256: 5946e16aa77e32627adb4c965430bec3685d40d914d723f6cfd6f93339b61fac
    output_schema_sha256: ea352b21dea5627ce2a4c67b42a0e0df0450f0f0d3aead0262437142f671a195
  - name: open_icp_confirmation_gate
    version: "1"
    input_schema_sha256: 88ff08eb29f645d5f37a1be67e601f71c08ba29e5821a722bd28411f624a171e
    output_schema_sha256: 048080bd8812b31b72b173b9e729f08045ba9dcac1cfa5b237bf155fc18634c7
  - name: propose_field
    version: "2"
    input_schema_sha256: 381ff072e572d2a4a11818b527d7b36fe1a64c0de63d7f34cebd70b44e26a4a2
    output_schema_sha256: 3250d58ae68070d2e2112986d8c91befd06795a506770b1ed62cf2f6c99f9842
  - name: propose_source
    version: "1"
    input_schema_sha256: 641252341ba5eab67aefcc7748a3cc27cac07a158418a1d9855c61fddc21ef5b
    output_schema_sha256: 708d9b5075c72103232daa51c12cbb83a5fe5bdf638bfa79659193f2324a851e
  - name: record_interview_answer
    version: "1"
    input_schema_sha256: 6e597a939a364afc1774e32331256d02c14101d33b2641e3851d449eef7c7ecc
    output_schema_sha256: 5f0e0fe7baad009e16af713744ef7abbc390615d627a69f5f25c43eb8734e7a8
  - name: start_confirmed_project_run
    version: "1"
    input_schema_sha256: 5d855fe786d02156e6bd7e0cd348ee9947453d1904c39764db4d7581faac3cac
    output_schema_sha256: 4b621e2cbd05d503e2433b7698d87e9d7d69956d8a94084225ca6d5b13e122f9
  - name: submit_ingestion
    version: "1"
    input_schema_sha256: 9b0a3d6ca25706d310fafd8a28969d6d39cff1272d904f3e4943eddb0b8b83c9
    output_schema_sha256: 8e2acc7a8819cb1eaff07dc0fa6f8a90b824572e5fb39cbf34a5380f3f1319bf
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Stage 0 vertical

Open this skill when the project is in Stage 0 or the user is establishing product and ICP truth.
Do not preload or apply it to unrelated stages.

This is the Stage-0 *procedure*: how to establish truth, ask from gaps, and route what the human
says. It is not the description of your surface. Which tools exist for you is stated once, by your
resolved resource and capability map, and that map is authoritative — a tool this skill names may
simply not be installed where you are running. When that happens, say what you would need and ask
the human; never simulate an absent tool, and never treat a step described here as done because the
procedure mentions it.

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

- **Claim:** a verifiable fact, with the exact quote it rests on, entity, registered field, and
  correction lineage when applicable.
- **Memory:** an advisory preference or behavioral learning through the scoped-memory seam. Memory
  never becomes fact.
- **Project intent:** a choice or constraint local to this project.
- **Field/source proposal:** a novel typed field or source goes through `propose_field` or
  `propose_source`; proposal creation grants no promotion or trust authority.
- **Dynamic Client-KB field:** first preserve the exact material fact through
  `record_interview_answer` and use its volunteered-statement receipt. Only then propose one
  bounded `client.*` field with `pack=client`, tenant-private reuse, a normalized candidate
  value, semantic description, freshness policy, and the canonical
  `volunteered_statement:<id>` evidence reference. The field remains supplemental: do not give it
  readiness, scoring, qualification, outreach, compliance, source, or trust authority.
- A pending dynamic field is not a claim. Say that human approval is required. If a promoted field
  returns materialization refs, report only those durable field/proposal/statement/claim/KB-version
  refs; never imply the candidate was written when the receipt is absent. Preserve a material
  statement as `unmapped` when no bounded reusable field is warranted.
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
  route `unmapped` (route key plus the exact quote) instead of routing nothing. `unmapped`
  is a real, honest answer, not a fallback for laziness.
- A `completed` or `awaiting_input` finalization of a substantive turn that produced no routing
  receipt is refused by the platform, and the refusal is visible to you. Route the turn — including
  via `unmapped` — and finalize again rather than restating the same claim.

## 3b. Authoring rules for routing

The tool schema states each rule on the field it governs; these are the same rules at procedure
level, with the reason they exist.

- **Copy the span; do not describe it.** `quote` is the user's own words, copied
  character-for-character out of the captured message. The platform searches that message for your
  exact text and records the span itself, so there are no offsets for you to count — but there is
  also no approximate matching: a span you retyped, tidied, re-punctuated, or reflowed is not in
  the message and is refused. When it is refused, copy it again from the message rather than
  rewording it. If the same words appear more than once and you mean a later one, say which with
  `occurrence`; otherwise the first is used, and the evidence is identical either way.
- **You never send the message back.** The platform loads the captured bytes itself, verifies
  their hash, and searches them. It also supplies the turn's `onboarding_input_id` and
  `artifact_key`, so there is no identifier here for you to carry, quote, or invent; L7 names them
  only so you can refer to this capture in prose.
- **Quote, never summarize.** A claim's text `value` must appear verbatim inside its own `quote` —
  a tidied-up paraphrase is refused, so narrow the quote to the words that state the fact instead
  of rewording them. A **typed** value (true/false, a number, a list) is different in form but not
  in discipline: it cannot appear verbatim in prose, so an entailment judge reads your quote on its
  own and admits the value only if those exact words support it. Quote the sentence that actually
  states the fact; a typed value is not a way around the evidence lock, and "the user did not quite
  say that" comes back as a refusal, not a silent write.
- **Never author an entity id.** A claim about the client itself needs no `entity_id` at all — the
  platform fills in this project's own client entity. Name an entity only when the claim is about a
  *different*, already-resolved one, and only with an id a governed tool or your context gave you;
  an id that resolves to nothing is refused rather than written at lower trust. A contact claim
  needs its contact.
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

## 4. Evaluate, synthesize, and stop at human gates

You decide when an ICP-synthesis readiness check is useful. Call
`evaluate_stage0_readiness@2` with only `{"gate":"icp_synthesis"}`. Never calculate or send
coverage, verified-claim counts, available fields, workspace/project/product/client identity, or a
verdict. The platform reads the pinned product-scoped Client KB, applies the required-field policy,
persists the decision, and returns the authoritative measurements.

Describe the returned version exactly as a **readiness-policy version**. It is not an ICP version.
Until `synthesize_icps@2` returns at least one durable `icp_spec` reference, say that no ICP
exists. Never call a readiness decision, readiness-policy version, proposal token, or
`human_only` value an ICP or synthesized spec.

When the current readiness verdict is `ready`, call `synthesize_icps@2` with no arguments. It
resolves the same trusted project/product/client/Client-KB lineage, synthesizes against durable
claims and project statements, and persists each option as a draft versioned `icp_spec`. Report
the returned `workspace_id + icp_key + icp_version` references and label them **draft ICP specs**.
Do not claim they are confirmed, active, locked, or ready for discovery.

Present assumptions, exclusions, missing evidence, and the proposed motion. The human alone:

- confirms the project product;
- confirms, rejects, or revises a draft ICP;
- records a readiness override.

Agent judgment and `agent_sufficiency_status` are advisory; they cannot turn a failing deterministic result into ready.

After reporting a draft returned by `synthesize_icps@2`, call `open_icp_confirmation_gate@1` with
that exact `icp_key` and `icp_version`. Supply no workspace, project, digest, snapshot, decisions,
or addressee: the platform derives all authority from the governed turn and persisted draft. End
the turn `awaiting_input` with exactly
`{object_type: "agent_gate", object_id: <returned gate_id>}` in `open_gate_refs`. Never place the
tool's display `gate_ref`, an ICP key, `human_only`, or a readiness-decision id in that object-id
slot.

The human answers through the structured gate route. **Approved** activates exactly the gated
draft. **Rejected** leaves it inactive. **Revised** carries the requested changes in its immutable
answer receipt; route those words as project evidence and synthesize a new ICP version rather than
editing or re-presenting the gated snapshot. A gate receipt is the only authority for any of these
claims—ordinary prose such as “looks good” does not activate an ICP.

Call `start_confirmed_project_run` only when durable product and ICP confirmations exist and the
discovery readiness decision is ready or has a durable human override. The tool and Recipe #1
router revalidate every lineage and gate. If they refuse, report the refusal and remain
`awaiting_input` or `blocked`; never claim the project started.
