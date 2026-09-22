# ARV3 research quality — specification, not implementation

- Founder requested a thorough spec after reviewing the Premier and earlier v3 findings. Explicit
  additions: project pins may reference brand or project-local ICP/persona variants; explain concrete
  claim validation/correction and scalable evidence sharing; person-to-account reconciliation agreed.
- Added `docs/superpowers/specs/2026-09-22-arv3-research-quality-design.md` and companion ordered plan
  `docs/superpowers/plans/2026-09-22-arv3-research-quality.md`, based on checkout `2dd07c55f`.
- Design reuses Postgres scope/state, existing workspace-scoped artifact storage and disposable
  read-only specialist workspaces. Includes exact document lineage, project-context display identity,
  typed evidence proposals, atomic correction/withdrawal, membership assessments, durable reconciliation,
  governed specialists, media/hiring qualifications, telemetry and 24 final-behavior acceptance cases.
- Existing ARV2 annotation-only quality policy is explicitly identified. Keeping invalid observations
  for audit while excluding them from ordinary factual summaries was initially proposed and is now
  explicitly adopted by the founder (2026-09-22), with unresolved findings remaining visible.
  Implementation/activation and remaining frontend/schema details are separate; do not re-ask this policy.
- Read current project-context/automatic-targeting rulings: preserve automatic pin authority; do not
  reintroduce mandatory confirmation cards. Exact persona source-ICP identity is preferred to matching
  unrelated front-matter/document-row version integers.
- No application source, settings, database or runtime changed; no paid calls, worker starts, push or PR.
  Upstream sync remains a prerequisite before future application implementation, not performed for docs.
- Verification: local document links exist, 24 acceptance IDs present, fenced blocks balanced and
  whitespace checks pass. Application tests are not applicable to this documentation-only change.
- Minor tooling failures: initial guessed module paths/glob had no match and were corrected by file
  inventory; one patch context did not match and was reapplied with exact context. No runtime effects.
- Preserve unrelated edit to the cumulative-quality-review document and existing side-audit attachments.
  This specification does not mean implementation, new quality-policy activation or live acceptance.

- Adoption follow-up: updated spec, implementation plan and the master plan's activation-pending
  amendment to record the founder's explicit policy approval. No code/data/runtime changes. Document
  link and whitespace checks passed; unrelated edits and attachments remained untouched.
