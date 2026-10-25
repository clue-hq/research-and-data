# Direct Mail revision 2

Plan: docs/superpowers/plans/2026-10-25-direct-mail-campaign-context.md
Base: f5a9b1590; branch feat/direct-mail-infrastructure-ui.

- Founder: preferred gift range and hard ceiling guide search; editable locked
  project preferences; no reservations. Explicit final send approval required.
- Existing inline execution authorization persists. No repeated plan approval.
- Pre-flight: domain defaults consumed by controllers and presentation; preserve
  existing drafts/approvals, source data and channel ownership.
- Ruling: use this bounded ledger. The skill workspace helper looped on denied
  mkdir and was interrupted; auto-review rejected rerunning it elevated because
  of runaway filesystem risk. Do not rerun it. Manual notes avoid that helper.
- All three tasks implemented. Project guidance is a preferred range plus hard
  gift-price ceiling; locking does not reserve credits. Final approval deducts
  the mock estimate once, with insufficient-credit refusal and recorded-debit
  refunds before ordering. Real settlement remains an explicit backend seam.
- Added project recipient/channel tables in chat and Gallery, research source
  and merchant links, recommended badges, feedback instead of manual insight
  selection, reusable note templates, microsite publication versus physical QR
  status, and six chronological customer tracking stages.
- A bounded historical example enters through a preview-only optional loader.
  Its source JSON stays ignored and outside deployment output; no corpus files
  were committed. One recorded gift is shown and two alternatives remain pending.
  Exact historical note exceeds the current card-fit limit and is truthfully
  blocked. Do not imply print-ready status, current quotes or verified receiving.
- Fresh review found copied physical QR assignments and pilot-load failure
  blocking drafts. Both reproduced and fixed with regression tests. Decimal
  cents and missing publication labels also fixed. New sends clear QR ownership;
  failed optional sources preserve existing saved mailers with a source notice.
- Browser verified template save, pilot image/note, project table in full view
  and chat, settings save/lock with unchanged credits, and ordered tracking with
  future outbound steps pending. Multiline signatures now use a textarea.
- Gates: focused tests 28/28; full frontend suite 3,664 passed, 5 existing skips,
  zero failures; design-system build passed; lint zero errors, 11 existing
  warnings; final production build passed. Raw standalone tsc encounters known
  pre-existing test errors; no claim of a clean standalone tsc gate.
- Next output tracing initially included the ignored local sample. Added global
  `.local/**/*` exclusion and rebuilt; inspected route trace (zero private
  entries) and full `.next` tree (zero pilot source copies, standalone present).
- Final state: frontend-only, no real agent, payment, purchase, QR routing,
  fulfillment or email transport changes. API handoff documents these seams.
  Feature branch retained, local commit only, localhost:5000 remains running.
