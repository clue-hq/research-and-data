# V2 ledger — plan: docs/superpowers/plans/2026-10-25-direct-mail-v2.md

- User approved research direction and requested separate V2, preserving V1.
- Base c8ef52ce6; V1 remains feat/direct-mail-infrastructure-ui on port 5000.
- New managed worktree direct-mail-v2/clue-main-pull-oct24; branch
  feat/direct-mail-infrastructure-v2; target free port 5001.
- Using existing dependencies copied with APFS cloning; no new dependencies or
  private corpus/env copy needed for isolated frontend preview.
- Ruling: existing worktree is V1, so create a second despite normal reuse advice;
  preserving its files and running server is the user's explicit requirement.
- Ruling: approved research and direct build request authorize inline execution;
  do not ask for another design/plan confirmation.
- Ruling: do not rerun the known runaway skill workspace helper; keep a bounded
  ledger here. Root owns implementation and one fresh final review follows.
- Pre-flight: shared workspace domain feeds all new views; existing Direct Mail
  controller owns gift approvals. Join by stable account/contact/mailer IDs.
- Tasks 1–2 implemented: shared schemas/fixtures/repository and connected plan,
  chat, account drawer, artifact previews, email review and results.
- Focused domain tests: eight pass, including cross-domain IDs and Avery approval
  with Priya's address hold. Full suite: 3,672 pass / 5 skip / 0 fail.
- Build caught a missing JSX closing div; corrected. Lint caught effect loading
  and button ARIA usage; corrected. Final lint: 0 errors, 11 inherited warnings.
- Production build passed. Design-system build passed after correcting cwd.
- V2 running on 5001, separate from V1 5000. Browser verified account-owner change
  keeps sender, and chat → plan → gift/card/note → $98 cost approval → tracking.
- Task 3 in progress: finish browser checks, fresh review and local checkpoint.

- Final review: two important findings reproduced RED→GREEN in tests: open
  email dialogs now capture immutable copy/revision; fresh reply guidance uses
  current ownership and outstanding reply status. One artifact-version mismatch
  was elevated to correctness because shared-record consistency is a V2 goal;
  every surface now uses the same resolver (regression test passes).
- Review boundaries accepted: live providers/orders/publication/CRM and live
  availability events remain outside this frontend preview. Existing gift gates
  remain in force. Author verified browser behavior independently.
- Final suite after review fixes: 3,675 pass, 5 skip, 0 fail. Lint 0 errors,
  11 inherited warnings; production build and token generation pass.
- Browser QA: note/card/cost approval, tracking, owner assignment, same-record
  landing-page preview, Escape dismissal, artifact empty search/reset, email-only
  account editing/approval, incoming reply stop, and analytics all verified.
  Desktop layout inspected at 1159×899; narrower account table keeps next actions
  visible and moves connected-asset shortcuts into the account drawer. Mobile
  breakpoint styling exists but was not device-tested.
- V1 git status remains clean and its port-5000 listener is the original PID94397.
  V2 uses port5001/PID18120. QA locally approved Avery and Drew and reassigned
  Northstar to Jamie; Alex remains the prepared sender. No external actions.
- Closing: keep both branches/worktrees under the user's explicit request; no
  merge/push/PR/remote deployment. Documentation records the provider handoff and
  limits. Keep manual ledger rather than invoking the previously runaway helper.
