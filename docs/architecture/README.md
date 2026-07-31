# docs/architecture — the Clue-HQ backend doc map

> **Read this first when you are unsure which document governs.** Last revised 2026-07-24.
> This folder is the architecture record of the platform backend (repo: dar-es-salaam).
> The design engine has its **own** authoritative doc set in its own repo (`havana`,
> `docs/` — start with `deepagent-architecture.md`); nothing here overrides it.

## Terminology (binding, 2026-07-16 — harness doc §1a)

**Project** = one end-to-end ABM motion. **Campaign** = a channel program *within* a project
(mailer drop, LinkedIn ads, micro-site). Docs written before 2026-07-16 say "campaign" where they
mean *project* (campaign_run, campaign-scoped ICP, Doc M's campaign scope); map accordingly. New
docs (Doc A, Doc S) use the new vocabulary.

## The index

| File | Code | Role | Status |
|---|---|---|---|
| `clue-hq-research-architecture-overview.md` | — | The map: four outputs, end-to-end flow, output contract, D1–D8 register, this doc set's reading order | Authoritative (orientation) |
| `clue-hq-research-layer-architecture.md` | — | The substrate spine: claim store, identity, field registry, waterfall, verification, scoring | Authoritative (data layer) |
| `clue-hq-discovery-and-research-staged-architecture.md` | — | Staged flow, research modes M1–M4, source intelligence | Authoritative (data layer) |
| `clue-hq-stage0-client-and-icp.md` | Doc B | Stage-0 front edge (pre-harness baseline) | Authoritative (data layer) |
| `clue-hq-signal-execution-cost.md` | Doc C | Two-tier signals, bounded fan-out, cost governance | Authoritative (data layer) |
| `clue-hq-compliance-and-personal-data.md` | Doc D | Jurisdiction switch, use-classes, lawful basis, DSAR | Authoritative (compliance) |
| `clue-hq-harness-architecture-and-requirements.md` | — | **The harness-era record (v1.2): 22 requirements**, four planes, build sequence, decisions register, open decisions O1–O12 | **Authoritative (platform)** |
| `clue-hq-harness-replatform-proposal.md` | — | Evidence trail of the harness pivot. Its node-canvas surface was **retired 2026-07-11** (see its header addendum) | Frozen history |
| `clue-hq-research-harness-founder-brief.md` | — | Plain-language narrative (incl. §12, the agent-workspace update) | Context, not spec |
| `clue-hq-scoped-memory-and-context-assembly.md` | Doc M | Subsystem two: five-scope memory, deterministic context assembly, DSAR | Authoritative (memory) |
| `clue-hq-scoped-memory-decisions-notepad.md` | — | Doc M's decision trail | Frozen history |
| `clue-hq-platform-agent-runtime.md` | **Doc A** | **The binding agentic vocabulary** (v1.2): tool / skill / worker fleet (shell vs unit) / deepagent, platform deepagent anatomy, seven-layer context assembly, tool-output lifecycle, product profiles, §1.5 component classification | **Authoritative (agents)** |
| `clue-hq-content-and-artifact-scaling.md` | **Doc S** | The content plane (v1.1): content schema ↔ slot contract, three-beat flow, template finalization, scaled derivation, havana gap list; resolves overview D2 | **Authoritative (content plane)** |
| `clue-hq-repo-structure-and-observability.md` | **Doc R** | Ratified plan: uv-workspace repo layout (libs/ · subsystems/ · platform/), structlog-first observability (`clue-obs`), phases R0–R3, branch conventions | **Ratified plan (execution pending)** |

## Repo layout (Doc R — executed Phase A, 2026-07-17)

uv workspace, three zones: **`libs/`** (shared, subsystem-agnostic: `clue-core`, `clue-config`,
`clue-db`, `clue-gateway`, `clue-locks`, `clue-obs` (structlog + OTel), `clue-spine` (workspace
owns brands/projects; brands own products; projects select one same-workspace brand));
**`subsystems/`** (`research/` — the M0–M13 build; `memory/`,
`content/` — contracted scaffolds); **`platform/`** (`toolbelt/`, `agents/`, `fleet/`,
`projections/` — contracted scaffolds; `api/` arrives at R3 with build step 2). Tenancy is keyed
`workspace_id` everywhere (the 2026-07-17 rename; the `tenant_private` reuse-scope enum value is
deliberately retained). Import rules are enforced by import-linter in the root `pyproject.toml`.

## Authority order when docs conflict

1. **Harness doc (v1.2)** — for platform-era requirements, decisions, and open items.
2. **Doc A** — for anything about agents, deepagents, fleets, context assembly, or naming
   agent-shaped things. Its §1.5 classification and no-fake-agency rule are binding.
3. **Doc S** — for the content plane and artifact scaling.
4. **Doc M** — for memory and context-assembly mechanics (Doc A's L4 layer defers to it).
5. **The substrate doc set** (overview, research-layer, staged, B, C, D) — for data-layer
   internals; the harness doc explicitly does not weaken them.
6. The proposal, founder brief, and notepad are history/context — never cite them against the
   documents above.

## Reading order for a new agent session

Overview → harness doc (header changelogs, §1a, REQ list, §10 register) → Doc A end-to-end →
Doc S end-to-end → the substrate doc a task touches → Doc M if memory is involved. Also read
`_memory/` per the session protocol in `CLAUDE.md`/`AGENTS.md`.

## Standing flags

- **O11 (harness doc; backend resolved 2026-07-27):** dossier means a structured account/contact
  research view with provenance/evidence actions and reference-only saved versions. Consumers read
  claims/narrative/block projections, not a canonical rendered document. Exact frontend layout and
  any optional downstream renderer remain open.
- The frontend/product plan pack and the treaty (`08-backend-contract.md`) live outside this
  repo (co-founder side); treaty changes are additive-only (REQ-16/17).
