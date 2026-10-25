# Direct Mail customer flow — 2026-10-24

- Worktree: `direct-mail-infrastructure-ui/clue-main-pull-oct24`; branch
  `feat/direct-mail-infrastructure-ui`. Production/frontend source is
  `apps/frontend`; do not create a separate mock application.
- Founder confirmed customer-only UI, separate Direct Mail sidebar entry linked
  from chat/Gallery to the same records, three gift recommendations, individual
  review plus bulk approval. Fulfillment is represented through tracking and
  photos. Ship automatically after Clue quality check, without another customer
  approval. Card uploads and multiple handwriting styles are in scope.
- Founder clarified that real frontend source is what matters for Aryan's
  handoff; existing local fixture preview is acceptable. Do not switch to the
  production database or clone Winnipeg data based on the superseded question.
- Installed frontend dependencies and started the existing Next dev app on
  localhost:5000. Existing Home, Accounts and project chat rendered in browser.
  No other local server was restarted. No backend or database started/modified.
- Preview uses process overrides: auth false, Accounts fixtures true, API and
  projects transport URLs empty, app origin localhost:5000, no workspace pin.
  Copied `.env.local` is unchanged. It points to stopped local backend ports
  8110/8111, not production. Do not dump credentials when inspecting it.
- Existing Gallery document reads remain backend-dependent and show an error
  in fixture mode. A future Direct Mail demo must use an explicit adapter at
  the integration boundary; do not hide a failed live read with fixture data.
- Read pilot Sheet metadata and limited tracking/card/gift-review ranges plus
  selected corpus analyses in place. No corpus files imported. Historical
  top-two gifts, budget bans, fixed Clue marketing claims and worker prompts
  are reference data, not current platform instructions.
- Canonical proposal: `apps/frontend/docs/architecture/direct-mail.md`, indexed
  in frontend docs. Full flow approval and implementation plan are still owed.
  No Direct Mail product components or routes have been implemented yet.
- Read-only builder check completed. It flagged readiness/cost scope,
  replacements, insight replacement and campaign setup. Added explicit proposed
  behavior to the same design document; full-flow approval is still required.
- Verification at this point: browser smoke only, plus document diff checks at
  close-out. No production build or product test suite claimed for this proposal.
