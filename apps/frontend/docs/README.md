# Clue frontend documentation

Status: canonical documentation index.

The repository uses one living document per product flow, integration contract,
or architectural decision. When a topic is discussed or implemented again, its
existing document is updated. A new document is created only when the work
introduces a genuinely separate scope.

This prevents chat history, temporary implementation notes, and duplicated
specifications from becoming competing sources of truth.

## Documentation ownership

| Area | Location | Audience | Purpose |
| --- | --- | --- | --- |
| Frontend architecture | `docs/architecture/` | Frontend and backend | Component boundaries, dependency direction, and implementation decisions |
| Backend contracts | `docs/api-contracts/` | Aaryan and frontend | Endpoints, schemas, payload ownership, and integration state |
| Figma implementation | `docs/figma/` | Design and frontend | Approved nodes, route mapping, assets, and fidelity notes |
| Product research | `docs/research/` | Product, design, and engineering | External product references, observed patterns, and Clue adaptation decisions |
| Design-system provenance | `packages/design-system/` | Design and frontend | Figma extraction, reconciled product tokens, and generated runtime CSS |

## Canonical documents

- [`architecture/frontend.md`](architecture/frontend.md) — repository and
  dependency rules.
- [`architecture/ai-elements-and-reasoning.md`](architecture/ai-elements-and-reasoning.md)
  — AI Elements installation, attachment composition, and reasoning-trace
  architecture.
- [`api-contracts/accounts.md`](api-contracts/accounts.md) — accounts and
  contacts backend handoff.
- [`api-contracts/projects.md`](api-contracts/projects.md) — projects, threads,
  messages, generation runs, attachments, and artifacts.
- [`api-contracts/session.md`](api-contracts/session.md) — authenticated session,
  workspace selection, and same-origin BFF boundary.
- [`api-contracts/settings.md`](api-contracts/settings.md) — profile, workspace,
  members, invitation delivery/acceptance and static Settings previews.
- [`api-contracts/onboarding.md`](api-contracts/onboarding.md) — onboarding
  authentication, profile, and workspace-setup handoff.
- [`figma/projects-chat-flow.md`](figma/projects-chat-flow.md) — approved project
  flow frames, assets, and implemented interaction states; includes the
  [chat appearance inconsistency register](figma/projects-chat-flow.md#chat-appearance-inconsistency-register-2026-09-20)
  for composer/transcript typography, mentions and attachment-chip parity.
- [`figma/onboarding-flow.md`](figma/onboarding-flow.md) — production onboarding
  Ready for dev nodes, route mapping, scope exclusions, and validation status.
- [`research/lightfield-chat-reference.md`](research/lightfield-chat-reference.md)
  — Lightfield chat research, observed reference behavior, and the approved
  Clue adaptation direction.

## Required update workflow

For every implementation topic:

1. Identify the existing canonical document or create one for the new scope.
2. Record the decision, component ownership, data contract, and backend impact.
3. Implement against that documented boundary.
4. Update status and validation notes after the implementation passes checks.
5. Update the appropriate API contract whenever backend-owned data changes.

Documentation must describe the current repository state. Future proposals are
explicitly labelled `Proposed` and are not presented as already implemented.
