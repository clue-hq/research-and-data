# 2026-07-03 - Non-technical founder brief for research harness discussion

## What happened
User attached `.context/attachments/NJeKUx/Transcript of Design Research Subsystem.md` and asked to
compile the discussion into a document for a non-technical co-founder: requirements satisfied, why
the system is designed this way, product POV first, technical explanation high-level only.

Read the required workspace memory, the transcript, the existing overview/Stage-0/cost architecture
docs, the uncommitted technical proposal
`docs/architecture/clue-hq-harness-replatform-proposal.md`, and the referenced
`proposed-research-design.png`.

## Deliverable
Created `docs/architecture/clue-hq-research-harness-founder-brief.md`.

The new doc is intentionally separate from the technical proposal. It translates the discussion into
founder-facing language covering:
- the shift from fixed ABM pipeline to agentic ABM harness;
- the requirements satisfied (non-linear execution, agency with gates, dynamic fields, research
  loops, dossiers, ingestion, storage, Stage-0 recon/interview, optional CRM, 100 to 500 account scale,
  live visibility, recipes/node graphs);
- the product journey from URL submission to dossier/handoff;
- the high-level four-layer architecture (kernel, toolbelt, orchestration, reproducibility);
- rationale for key choices and what the system is not promising;
- product surfaces and a plain-language build plan.

## Decisions / assumptions
- Treated existing uncommitted proposal artifacts as prior context and did not rewrite them.
- Kept the brief in `docs/architecture/` because it summarizes architecture/product direction, but
  wrote it for non-technical review.
- Used "agent proposes, engine disposes" as the central safety framing.
- Preserved the boundary that the research subsystem owns verified meaning and dossiers, while
  artifact-shaped content/design remains downstream.

## Verification
- Docs-only change; no tests required.
- Reviewed the generated markdown for obvious structure/format issues and ASCII cleanliness.

## Follow-ups
- If founders approve this positioning, convert the technical proposal's build sequence into
  milestone specs (M14+) or an ADR.
- Decide recon cost envelope, fact-capture UX posture, source/field approval posture, and canvas V1
  scope.
