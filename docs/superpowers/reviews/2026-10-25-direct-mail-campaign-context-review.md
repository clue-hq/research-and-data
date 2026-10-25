# Direct Mail campaign context review

Reviewed revision against `apps/frontend/docs/architecture/direct-mail.md`,
Revision 2, and its implementation plan. Fresh read-only reviewer inspected the
diff and new source; no private pilot contents were sent to the reviewer.

Findings and dispositions:
- Important: copied QR assignment in new campaigns. Regression reproduced;
  new physical sends now clear printed URL and verification, retaining only
  deliberate destination context and account-scoped assets.
- Important: optional pilot loading blocked saved drafts. Regression reproduced;
  failure now returns saved data with a separate retryable source notice.
- Decimal cent conversion was graded Minor, promoted to Important because valid
  money inputs must work. Failing 19.99 regression added; conversion now rounds
  to integer cents and browser save/lock succeeded without any credit deduction.
- Missing publication label was graded Minor, promoted because the design
  explicitly separates publication from QR assignment. The UI now shows draft,
  published or publication-not-verified alongside the physical QR status.

Additional local verification caught the private pilot file in Next's output
trace. The app config now excludes `.local/**/*` from standalone output. The
final build passed; the pilot route trace has no private entries and no pilot
source copy exists anywhere under `.next`, including standalone output.

Review declined live billing/fulfillment semantics (intentionally not connected),
private pilot accuracy (executor verified against the source Sheet), visual QA
(executor browser checks) and the then-running build. No findings were silently
dropped; the source retains explicit integration boundaries for Aryan.
