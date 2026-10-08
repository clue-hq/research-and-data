# Website agent on Puck: production roadmap

Status: **draft for founder review** (2026-10-08). Built on the Puck spike: phase 1 (editor,
clones, brand theme, multi-page; `trials/puck-spike/FINDINGS.md`) and phase 2 (our agent on Puck;
`trials/puck-spike/AGENT-FINDINGS.md`). Open issues: `trials/puck-spike/ISSUES.md`.

## Where we are

**The spike answered the question:**
- a lean agent on Puck builds a 1:1 page for $0.57–0.99, against $4.14 for the platform website
  agent;
- it made zero Puck mistakes in 296 model calls and stays on brand;
- it handles edits and multi-page sites.

**The remaining gaps are:**
- judgement (scope; the brief overriding a skill);
- inputs: capture of JavaScript-heavy sites, research coverage, images;
- edit cost, which is still above its target.

This roadmap takes the trial to production without throwing away what it proved.

## Principles carried from the trial

- **A lean harness:**
  - a small fixed prompt (about 6.7k tokens, 12 tools);
  - short skills that don't contradict each other;
  - a new rule only with a failing case behind it, logged in a changelog.
- **Contracts in code, judgement in the prompt.**
- **One session per request, with files as memory.** Context clearing only in long sessions;
  compaction as a safety net.
- **A cost and token record for every call,** from day one.
- **Pages are data over our own components.** We own the page model, validation, theme, site model
  and publishing; Puck is the editor and renderer host, and could be replaced.

## What carries over and what is new

| Carries over from the trial (port, then harden) | New for the platform |
|---|---|
| Component contracts (Zod), brand sections, the clone renderer (with the link fix) | Storage: site documents, pages, shell and versions in Postgres |
| The theme: brand kit to CSS variables, nearest-surface headings | The agent's workspace as a view assembled per request (brand, catalog and seller shared; research per account) |
| The site model: pages, shared shell, links between pages, nav | The editor inside our app's UI |
| The validator (contracts) and the catalog generator | The agent on the fleet: Head-of-ABM routing, chat progress, stop |
| Skills and system prompt, with their changelog | Publishing into the page origin's format; custom domains unchanged |
| Harness middleware (ordered tools, finish guard, clearing threshold, compaction, run records) and the tools | Multi-tenant isolation; the cost ledger and Langfuse tracing |

## Phase 1: platform integration v1 for websites

**Goal:**
1. A marketer asks Head of ABM for a 1:1 site in chat.
2. The Puck agent builds it.
3. They edit it in our editor.
4. They publish it to their domain.

It runs beside the current website engine behind a flag. Nothing is retired until the evidence says
so.

| Workstream | What | Estimate |
|---|---|---|
| 1. Shared package | Components, schemas, theme, clone renderer, validator, catalog generator, tests | 1 week |
| 2. Storage and API | Site documents (pages, shell, versions, undo), assets, per workspace; migrations | 1 week |
| 3. Agent on the fleet | The harness on the platform runtime (model config by env, gateway, cost ledger), the workspace view, a website design leg (Head of ABM opens it, progress in chat, stop), a fresh session per request | 2 weeks |
| 4. Editor in our UI | Puck's parts (preview, fields, outline) inside the chat-shell layout; our inspector controls; inline clone editing; page switcher; asset picker; autosave and versions | 2 weeks |
| 5. Publishing | A static render per page, CSS written once per site, the page origin's package, custom domains as today | 1 week |
| 6. Hardening | QA across sellers (Garner, Conduit, Alt Carbon), the skills regression set, the decision on existing website documents | 1 week |

**Brand fidelity (required in production; founder 2026-10-08, from the component library spike):**
- the agent sees every type role in the kit (12 for Garner), with its size and whether it was
  measured or derived;
- ingestion measures more roles from the page instead of deriving them (small serif titles, lead
  paragraphs);
- surfaces cover the colours the page uses for bands (Garner's dark green exists only as heading
  ink today);
- the kit covers logos (a "contain" fit), a second button style, and links that resolve inside the
  site, and the skill shows the kit's prop names.

**About 8 engineer-weeks; 4–5 calendar weeks with parallel lanes.** Confidence: medium. The biggest
unknowns are how much polish the editor needs and the agent's chat integration.

**Exit criteria:**
- three sellers × two accounts each, built, edited and published end to end;
- builds at or under $1 and 10 minutes;
- edits in fresh sessions;
- zero validation errors;
- the founder rates the pages.

**Decisions needed before the spec:**
- the storage model;
- the editor's chrome;
- where the agent runs (fleet worker or inline);
- the publish format;
- the flag and retirement plan for the current website engine;
- the Puck version pin.

## Phase 2 (in parallel): capture upgrade for JavaScript-heavy sites

Source: `docs/superpowers/specs/2026-10-08-capturing-javascript-heavy-sites-notes.md`.

| Step | Effort |
|---|---|
| Honour the clone-review gate's `degraded` flag everywhere sections reach an agent | days |
| Prototype: record and replay, scroll-explore, save sections in view (under way; no model spend) | 3–4 days |
| Save each section while in view, with its visible state baked in, inside today's capture | 1–2 weeks |
| Record and replay, plus a reference screenshot per section for the review gate | about 1 week |
| Interactive states as data, plus runtime behaviours for the top patterns | 2–3 weeks |

**Exit:** sites like altcarbon.com produce usable sections, or honestly labelled stills, never
silent blanks.

## Phase 3: the seller component library

- **Spike first:** our agent rebuilds Garner's five most-used clones as React components built from
  brand tokens. Each is judged against its clone with a side-by-side render, a pixel-difference
  score and a founder review, then one page is built from them. About 1 week and $2–4.
- **Then:**
  - a per-seller rebuild step with human approval;
  - the components registered in the catalog;
  - agents composing from the seller's own components, and writing new ones in their style.

  About 3–4 weeks.
- **Open:** sandboxed builds for agent-written code, per-seller cost, and the approval experience.

## Phase 4: scale and growth

- **One-to-many:** site templates with account bindings, a variant per account generated from one
  template, batch builds, and cost per account.
- **Attribution:** a per-account tracking script added at publish (simple on code-based pages).
- **Booking and calendar pages and forms from a prompt;** a small per-seller database.
- **A claims tool,** so the agent can check a fact's source and quote before using it.
- **Brand kit rules in the agent's brand file,** after a test (the patch is parked in
  `trials/puck-spike/proposed/`).

## Across all phases (start in phase 1)

- **A skills regression set:**
  - cases A, B and C, the ten edits, and E5;
  - run before any skill change, with accuracy and cost compared against the previous version;
  - about $5–8 for a full run.
- **Fix the brief upstream:** Head of ABM describes proof candidates instead of prescribing them
  (the cause of the Syracuse proof misses).
- **Image descriptions** for captured images (reuse the ingestion describer).
- **Edit cost:** hold small edits near $0.05; watch provider-side cache misses through the per-call
  records.
- **Founder review gates:** skill text, and design decisions before implementation.

## Risks

| Risk | Mitigation |
|---|---|
| Puck is pre-1.0 | We own the page data (a list of `{type, props}`) and every layer around it; pin the version |
| Editor polish takes longer than planned | Build the editor on Puck's parts in our own design; time-box it and ship the inspector first |
| Copy quality is limited by the model | The model is an env setting; the regression set measures any switch |
| Capture limits on JavaScript-heavy sites | Phase 2; honest labelled stills instead of blanks |
| Page weight | Static publish (no React runtime); CSS once per site |
| Agent-written code on a tenant's pages (phase 3) | The brand-token check, a sandboxed build and human approval before a component joins a catalog |
| Cost drift | Per-call cost records and the regression set's cost columns |

## Sequencing sketch

| Weeks | Work |
|---|---|
| 1–5 | Phase 1 (2–3 lanes) |
| 1–4 | Phase 2 in parallel (the prototype now; capture steps next) |
| 3–4 | Phase 3 spike |
| After phase 1 | Phase 4, by priority |
