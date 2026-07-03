# Clue-HQ Research Subsystem - Founder Brief

> **Audience:** non-technical founder / business stakeholder  
> **Status:** discussion brief, not final implementation spec  
> **Purpose:** translate the research-platform discussion into product requirements, rationale, and a high-level technical shape.

## 1. Executive summary

The research subsystem should not be a rigid ABM pipeline where users must move through the same fixed sequence every time. ABM work in real teams is non-linear: teams may research first, design first, import a target list first, change the ICP mid-run, ask for a new field of research, rerun a subset, or make a broad change after many artifacts have already been generated.

The product direction is therefore: **Clue-HQ should become an agentic ABM harness platform.** It should provide trusted specialist tools for research, design, scaling, review, export, and future campaign operations, while a skills-guided deep agent helps the user compose those tools in the order that fits their workflow.

For the research subsystem, this means:

- Keep the current foundation: evidence-backed claims, source provenance, identity resolution, verification, compliance, and cost controls.
- Expose research capabilities as reusable tools instead of locking them into one fixed stage order.
- Let the agent plan, ask questions, inspect progress, rerun parts of the work, and loop on research gaps.
- Journal every run as a repeatable graph so good workflows can be reused, audited, and represented in a node-based interface.
- Give users readable research outputs, not just database rows: briefs, dossiers, coverage notes, and source-backed reasoning.

The key principle is:

**The agent proposes. The engine disposes.**

In plain terms: the agent can decide what to try next, but the system still enforces evidence, budgets, source trust, compliance, identity binding, and verification. That is how the product gets flexibility without turning into an uncontrolled chatbot.

## 2. What product problem this solves

Traditional ABM tools assume a fairly linear workflow:

1. Define ICP.
2. Find accounts.
3. Score accounts.
4. Research accounts.
5. Create content.
6. Launch campaign.

That sequence is useful as a default, but it is not how all teams actually operate.

Some teams may already have a target list. Some may need the platform to discover targets. Some may want to start from brand or design direction. Some may run research, then change the ICP. Some may inspect the 15th generated artifact, realize a global change is needed, and apply it across all artifacts while preserving the custom edits already made.

The important observation is:

**The components stay mostly the same. The order changes.**

Research, scoring, design, scaling, review, compliance checks, and export are still the building blocks. What changes is how a team strings them together. The platform should support that flexibility without losing repeatability.

That is why a harness model is the right product shape:

- The platform owns high-quality domain tools.
- The agent understands the user's goal and composes those tools.
- Skills and recipes make the composition repeatable.
- A visual node graph helps users understand and rerun the workflow.

## 3. What requirements this design satisfies

### Requirement 1: Non-linear ABM execution

Users should not be forced through one rigid path. The system should allow workflows like:

- Start with client URL, then interview, then ICP, then discovery.
- Import accounts first, then back-score them against the ICP.
- Add a new research field mid-run and research only the affected accounts.
- Pause research, adjust budget or target segment, then resume.
- Rerun verification after a policy change.
- Re-score accounts after the ICP changes.

The design satisfies this by converting stages into **tools**. The default linear pipeline still exists as the first saved recipe, but it is no longer the only way to operate.

### Requirement 2: Agency without chaos

The deep agent should be able to plan and steer work, but it should not be allowed to fabricate facts, spend without limits, or bypass governance.

The design satisfies this by separating responsibilities:

- The agent chooses the next action.
- The toolbelt executes actions through governed tools.
- The claim store only accepts evidence-backed facts.
- Verification gates decide what can be promoted.
- Budget and source policies decide what can be attempted.

This preserves the current research system's strongest idea: **trust is enforced by the data model and gates, not by hoping the agent behaves well.**

### Requirement 3: Dynamic research fields

During client understanding or ICP synthesis, the agent may discover that a new kind of field matters for this client. For example, a specific buying signal, vertical-specific metric, or customer-fit indicator that was not already in the registry.

The platform should not drop that insight just because the schema did not anticipate it.

The design satisfies this with a **field proposal flow**:

- The agent can propose a new field.
- The field is staged with a rationale.
- Human approval is required for sensitive or personal fields.
- Once approved, it becomes part of the field registry and future research plans.

This keeps flexibility while avoiding random one-off fields that break the system.

### Requirement 4: Research loops and visible gaps

Research rarely succeeds perfectly in one pass. Some facts are unavailable, some sources disagree, and some fields require multiple strategies.

The product should not silently drop failed fields. It should retry intelligently, then explain what could not be found.

The design satisfies this with a **goal-judge loop**:

- The system compares the desired research goal against current coverage.
- It identifies missing fields, weak evidence, conflicts, or blocked attempts.
- It can run another research round with a different strategy.
- It stops based on deterministic limits: max rounds, budget, and marginal yield.
- If still unresolved, it surfaces the gap clearly to the user.

An empty field with a clear reason is a correct output. A fabricated field is the real failure.

### Requirement 5: Human-readable research dossiers

The claim store is excellent for trust and machine processing, but users need readable outputs. A founder, marketer, or sales leader should be able to read what the system learned and why it matters.

The design satisfies this with a **dossier layer**:

- The dossier is generated from verified claims.
- Every important statement points back to source-backed evidence.
- It includes business interpretation: what the facts mean for the account and personas.
- It includes a coverage and gaps appendix.
- It is a view over the claim store, not a new source of truth.

This gives the user a polished research document without sacrificing provenance.

### Requirement 6: Client material ingestion

Clients may upload decks, docs, PDFs, text files, web pages, exports, images, or other raw material. The system needs to turn these into structured client knowledge.

The design satisfies this by treating uploaded material as another source:

- Files are stored safely.
- The system extracts text or content.
- Extracted statements become claims with evidence spans.
- Client-provided facts about the client are high-trust.
- Client claims about target companies still need corroboration.

This supports Stage 0 without requiring a CRM connection.

### Requirement 7: Storage backend

The platform needs a proper place to store uploaded files, evidence snapshots, dossier exports, and other artifacts.

The design satisfies this with a **StorageBackend adapter**:

- Local filesystem in development.
- S3-compatible object storage in production, including S3, R2, or MinIO-style services.
- A consistent storage interface so the rest of the product does not care which provider is used.

This avoids hardwiring one cloud provider too early.

### Requirement 8: Stage 0 as client understanding, not a form

Stage 0 should not be a static questionnaire. The platform should understand the client's business before asking questions, and then ask better questions.

The design satisfies this with three moves:

1. **Eager preliminary recon:** when the client provides name and URL, a small background research run starts immediately.
2. **Governed interview:** when the user opens chat, the agent already has a brief and asks gap-driven questions.
3. **Client memory:** facts stated by the user become client knowledge claims; operating preferences become client memory read by future skills.

The user experience becomes: "Here is what I learned about you. Correct me and fill the gaps." That is better than starting with a blank form.

### Requirement 9: CRM is optional, not required

New clients may not trust the platform enough to connect CRM on day one. The product cannot depend on that.

The design satisfies this by making readiness achievable through:

- Company URL.
- Client interview.
- Uploaded material.
- Named best customers in chat.
- CSV exports or pasted lists.

CRM OAuth becomes an accelerator after trust is earned, not a prerequisite for value.

### Requirement 10: Scale to hundreds of accounts without watching every worker

The system may need to research 100 to 500 accounts. A human cannot monitor every account manually, and judging every internal worker step with an LLM would be expensive and redundant.

The design satisfies this with a layered quality model:

- Hard runtime caps prevent runaway work.
- Every promoted claim needs evidence.
- Claims are judged after production.
- Account-level progress is judged at round boundaries.
- A run supervisor watches aggregate signals like gaps, cost, verification health, stalls, and source failures.
- Humans review exceptions, canaries, and ranked high-value outputs.

The recommended default is a canary pattern: research the top group first, check quality, then open the larger fleet.

### Requirement 11: Live visibility into long-running work

Users should be able to ask, "How is this run going?" or "What is happening with Acme?" without interrupting the workers.

The design satisfies this through:

- Run overview projections: progress, accounts by state, spend, health, ETA.
- Account-level progress views: current step, filled fields, gaps, flags, latest claims.
- A narrator stream that posts digest updates into chat.
- Steering tools to pause, reprioritize, tighten budget, or disable a source.

The chat agent becomes the user's window into the run, not the thing doing all the work itself.

### Requirement 12: Repeatability and node-based workflows

If an agent produces a great process once, the platform should be able to rerun that process.

The design satisfies this with:

- A run graph journal: every tool invocation is recorded with parameters and versions.
- Recipes: saved, parameterized workflows that can be rerun.
- A node canvas: a visual representation of the workflow, its tools, and live status.

The promise is not bit-identical LLM output. The promise is **outcome-reproducibility**: the same process, same pinned configs, same rules, same gates, and auditable outputs.

## 4. The user journey this enables

### Step 1: Client provides company name and website

The platform starts a small background recon run. It looks at the client's website, official pages, public footprint, and obvious proof points. It produces a short source-backed brief and a list of unknowns.

### Step 2: User opens the chat interface

The agent does not ask generic onboarding questions. It says, in effect:

"I looked at your company. Here is what I think you sell, who you seem to serve, and what I could not determine. Please correct me."

As the user talks, the system records:

- Facts about the client as evidence-backed client knowledge.
- Preferences and instructions as client memory.
- Proposed signals or research fields as staged proposals.

### Step 3: ICP is synthesized and confirmed

The platform proposes one or more ICPs. The client edits and confirms. The ICP is versioned so future changes can be tracked and rerun.

### Step 4: Accounts enter through discovery, import, or both

The platform can discover accounts, accept an imported list, or use imported customers as seeds for lookalike discovery. Imported accounts are still back-scored so the client sees which ones match the confirmed ICP.

### Step 5: Cheap scoring happens broadly

All accounts get cheap, deterministic signals first. This keeps the run affordable and helps avoid deep research on poor-fit accounts.

### Step 6: Deep research happens only where it is worth it

High-tier accounts receive deeper account research, buying committee discovery, contact profiling, and value-narrative generation. Lower-priority accounts do not receive uniform expensive research.

### Step 7: The system loops on gaps

If important fields are missing or weak, the system can try another research strategy within budget. If the gap remains unresolved, it is shown clearly.

### Step 8: Users watch progress and steer

The user sees digests and can ask about the overall run or a specific account. They can pause, adjust scope, change budget, add fields, or kill a poor source.

### Step 9: The output is usable by people and downstream systems

The research subsystem produces:

- A scored account list.
- Verified account profiles.
- Buying committees.
- Persona-keyed claims and value narratives.
- Readable dossiers.
- Provenance indexes.

Downstream content and design systems can use the verified meaning without needing to redo the research.

## 5. The high-level technical architecture

The architecture has four layers.

### Layer 1: The kernel

This is the trusted research foundation.

It includes:

- Claim store: the database of facts.
- Provenance: source and evidence behind each fact.
- Identity resolution: making sure "IBM", "I.B.M.", and the correct domain refer to the right account.
- Field registry: what kinds of facts the system knows how to collect.
- Source registry: which sources can be used and how much to trust them.
- Verification: checking evidence, conflicts, identity binding, and faithfulness.
- Compliance and use gates: deciding what is lawful and appropriate to use.
- Budget ledger: controlling spend.

Why it exists: this layer makes research trustworthy. Without it, the platform becomes a polished generator that may fabricate.

### Layer 2: The toolbelt

This is the set of governed research capabilities.

Examples:

- Research the client.
- Propose ICP.
- Discover accounts.
- Import and resolve accounts.
- Score accounts.
- Deep-research an account.
- Resolve a buying committee.
- Profile a contact.
- Propose a new field.
- Propose a new source.
- Ingest material.
- Compose a dossier.

Each tool has clear inputs, cost estimates, preconditions, and outputs. The agent uses the tools, but the tools enforce the rules.

Why it exists: this turns the fixed pipeline into reusable building blocks.

### Layer 3: The orchestration layer

This is the deep agent and its skills.

The agent:

- Understands the user's goal.
- Chooses which tools to run.
- Asks questions when information is missing.
- Watches progress through projections.
- Suggests reruns or changes.
- Explains what happened.

Skills are the playbooks. They guide how the agent interviews a client, researches an account, escalates a gap, or writes a dossier.

Why it exists: this gives the platform flexible, domain-aware agency.

### Layer 4: The reproducibility layer

This records what happened and lets the team reuse it.

It includes:

- Run graphs.
- Recipes.
- Pinned versions of prompts, skills, source profiles, and ICPs.
- Node-based workflow views.

Why it exists: agency alone is not enough. Enterprise workflows need repeatability, auditability, and the ability to rerun a successful process.

## 6. Why this design is doing things this way

### Why keep claims at the center?

Because the product's differentiator is not "it can write a dossier." Many systems can generate a dossier. The differentiator is that every meaningful claim can be traced back to evidence.

The claim model prevents the platform from becoming a storytelling machine with weak facts underneath.

### Why not let the agent do everything directly?

Because an unrestricted agent is hard to trust, hard to cost-control, and hard to reproduce.

The agent should plan and steer. The governed tools should execute. This gives the user the feeling of a smart assistant while preserving operational discipline.

### Why use loops?

Because research is not one-shot. Good research discovers gaps, changes strategy, and reports what remains unknown.

The loop turns "missing info" from a silent failure into a managed product surface.

### Why not research every account deeply?

Because it is expensive and unnecessary. The two-pass model runs cheap scoring across everyone, then spends real research effort only on accounts likely to matter.

This is how the platform scales from a few accounts to hundreds.

### Why separate facts from preferences?

Because "we sell to hospitals" and "never use this phrase in outreach" are different types of information.

Facts belong in the client knowledge base as evidence-backed claims. Preferences belong in client memory so skills can respect them while operating.

### Why make CRM optional?

Because trust comes after value. A new client may share a URL, answer questions, name a few customers, or upload a CSV before they connect sensitive systems.

The product must deliver value before asking for deep integrations.

### Why produce dossiers?

Because business users need to review meaning, not inspect database rows.

The dossier makes the research useful to humans while staying grounded in the claim store.

### Why record workflows as recipes?

Because a great agent run should not be a lucky one-off.

Recipes let the platform turn successful work into repeatable operating patterns.

## 7. What this is not

This is not a promise that the platform finds every possible account. Open-ended discovery can estimate coverage, but it cannot honestly guarantee completeness.

This is not a plan to let an LLM become the source of truth. The LLM can nominate sources, synthesize, and reason, but evidence-backed claims remain the source of truth.

This is not an attempt to replace downstream content or design systems. The research subsystem owns verified meaning: facts, claims, buying committees, and value narratives. Artifact-shaped content and design execution remain downstream.

This is not a promise of identical replay. The same recipe can rerun the same process with pinned rules and auditable outputs, but LLM wording may vary. The useful promise is repeatable process and governed outcomes.

## 8. Product surfaces this implies

### Onboarding surface

- Company name and URL.
- Optional uploads.
- Optional named customers or pasted lists.
- Recon brief.
- Gap-driven interview.
- ICP confirmation.

### Run surface

- Account list with fit and intent.
- Tiering and budget estimate.
- Progress by phase or workflow node.
- Spend and cap.
- Source yield.
- Verification health.
- Gaps and conflicts.

### Chat surface

- Agent asks better questions from recon context.
- User can ask about overall progress or a specific account.
- Agent can explain why a field is missing.
- Agent can propose new fields or sources.
- User can steer mid-run.

### Review surface

- High-value accounts for human review.
- Conflicts and low-confidence claims.
- Personal claims that failed identity or use gates.
- Dossiers and source-backed value narratives.

### Workflow surface

- Node graph of the run.
- Saved recipes.
- Pin and rerun.
- Compare runs over time.

## 9. Build plan in plain language

### Phase 0: Make long-running work independent of chat

Runs should continue even if the chat session closes. This requires a background worker and a safe way to ensure only one driver owns a run at a time.

### Phase 1: Add storage

Support uploaded files, evidence snapshots, and dossier exports through a pluggable storage backend.

### Phase 2: Expose research as tools and progress views

Wrap existing research capabilities in clear tool interfaces. Add preconditions, cost estimates, projections, and progress streaming.

### Phase 3: Clean up shared utilities and conventions

Ensure common logic is shared in the right place instead of reimplemented. Keep module boundaries, but allow common utilities to live in shared packages.

### Phase 4: Add agentic research capabilities

Add the field proposal flow, source proposal flow, generic web source, ingestion, client interview source, client memory, and research gap loop.

### Phase 5: Add recipes and run graphs

Record workflows as graphs. Make the current linear pipeline Recipe #1. Add pin and rerun behavior.

### Phase 6: Add the deep agent and skills

Put the agent on top of the hardened toolbelt. Skills guide Stage 0, account research, gap escalation, and dossier writing.

### Phase 7: Add the dossier layer

Generate readable, cited account dossiers and derived insights from verified claims.

## 10. Decisions founders should align on

1. **How much preliminary recon should happen before commitment?** Recommended: enough to create a strong opening brief, but with a small hard cost cap.
2. **How should captured facts appear in the UI?** Recommended: implicit capture with visible "noted" moments and a batch confirmation step, not constant per-fact confirmation.
3. **How much workflow editing should users get in V1?** Recommended: agent authors the graph; user pins, reruns, and adjusts parameters first. Free-form graph authoring can come later.
4. **What source approval posture should we use?** Recommended: auto-allow lower-trust public sources with audit; require human approval for high-trust source tiers and personal/sensitive fields.
5. **What should the default canary size be?** Recommended: run the top group first, verify health, then open the fleet.
6. **Where should the deep agent live long-term?** Recommended: incubate near the research subsystem first, but design the toolbelt so the broader platform can consume it later.

## 11. The simplest way to explain the whole system

Clue-HQ's research subsystem is becoming a **trustworthy ABM research harness**.

It has a smart agent at the front, but the agent is not the source of truth. The source of truth is a claim database where every fact has evidence, source trust, freshness, identity checks, and compliance status.

The agent uses governed tools to move through research dynamically. It can ask the client questions, ingest materials, discover accounts, score them, research high-value accounts, loop on gaps, and produce dossiers. Every action can be recorded as a repeatable workflow.

That gives the product the three things it needs at once:

- **Flexibility:** teams can work in the order that matches their real ABM process.
- **Trust:** facts are evidence-backed and governed.
- **Repeatability:** successful workflows become recipes, not one-off agent luck.
