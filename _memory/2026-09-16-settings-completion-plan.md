# Settings completion planning — 2026-09-16

- Founder requested thorough code study and a detailed implementation plan after the spec audit.
  Planning only: no application code, runtime, database or provider changes in this session.
- Founder ratified Suspended as a separate read-only member state, and revoke-then-invite-again
  for failed/rate-limited invitation delivery. Updated the design and implemented contract to
  preserve both rulings. Other identified deltas remain proposals, not inferred approvals.
- Inspected current Settings/auth/frontend seams, registry migrations and write/read helpers,
  ARV2 catalog composition and lenient writer, custom-field/evidence projections, and the existing
  design publisher. Implementation baseline: Irvine settings-page at 5bd1a66c1.
- Wrote docs/superpowers/plans/2026-09-16-settings-integration-completion.md with phased tasks,
  source files, decision/dependency tables, automated/live acceptance and required Pages V1 work.
- Critical findings: workspace definitions reject every UPDATE via a trigger and pack is NOT NULL;
  both need deliberate migration changes. Retired local keys may become UnknownFieldError and
  reach the writer's global proposed-field fallback; lifecycle and collision protection are needed.
  Account/person driver composition plus direct person launch are three catalog call sites.
- Corrected an intermediate hypothesis: state-read tools expose open keys only, but driver context
  already includes catalog_menu_text with descriptions for both agents. Reuse and test that path;
  do not invent a second prompt mechanism.
- Account custom-field DTO has no claim reference and evidence access depends on generated-page
  citations. Contact detail has no explicit custom-values slot. The plan proposes contract changes
  to make evidence and contact payload promises deterministic while preserving privacy rules.
- Pages already has a real publisher with revisions/rollback/noindex. Settings defaults still need
  product decisions and integration; do not claim publishing itself is absent or Pages outside V1.
- Spec's status/header/old 404 claim corrected; historical design pin retained. Research frames and
  changing the original whole-build design gate remain explicit decisions. No new Figma availability
  claim, email delivery claim, service-health claim or test-pass claim from this planning session.
- Closing checks: local Markdown links passed validation, source symbols/files were checked, and
  scoped diff review plus git diff --check passed. Application tests were not rerun for this
  documentation-only change. Commit only these planning/ruling documents; existing untracked
  .context attachments and drafts remain untouched. No push or live migration performed.
