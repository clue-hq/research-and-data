# Isolated recording demo — 2026-11-02

- Work is on `codex/illumio-usbank-demo` in this managed worktree. Source V2 worktree and port 5001 were left unchanged; isolated frontend uses localhost:3000.
- Added one-account fixture, sourced public retail assets, supplied ad, deployed design preview, generated branded card front and handwriting-inspired back. No production mutations. Provenance and replay instructions are in the frontend demo doc; no customer research is copied into this memory note.
- Shared the existing fixture fulfillment progression/reset behind an injected repository adapter. Distinct browser database, approval snapshots and exact-message artwork matching retained.
- Validation: 32 focused tests; design-system build; production build; lint zero errors (11 existing unrelated warnings). Browser exercised previews, itemized approval, every fulfillment stage, reload and reset. Reset to original draft for presentation.
- Tool notes: system Python lacks requests; public downloads used urllib with approved network access. Direct tsx CLI IPC was sandbox-blocked; `node --import tsx --test ...` passed. Browser screenshot clipping kept the origin incorrectly; captured the full canvas and cropped to observed frame bounds.
- Remaining boundary: account landing page is a saved preview, not newly published; QR goes to the public product destination. Other modules retain pre-existing fixture data. No live ordering, carrier tracking or agent execution.

## Gift and photographic card revision

- Replaced the coffee concept with sourced puzzle products and a matching note. Historical public research is identified as historical; no hobby is inferred.
- Added an optional native photographic front layout and an unchanged official brand photograph. Existing full-card artwork keeps its original rendering.
- Enlarged preview now shares Front / Message controls with the inline card. Updated generated handwriting remains exact-text bound; QR routing is unchanged.
- Revised concept uses a new isolated browser record so earlier scenario drafts/approvals remain preserved. No source V2 edits or production mutations.
- Focused suite: 32 tests passed. Browser confirmed new gift selection, photographic front and message-side flipping. Design-system and production builds passed; lint has zero errors and the same 11 pre-existing warnings.
- Tool recovery: CUA returned an unavailable browser binding; resetting its JS session restored the existing tab. One stale accessibility target was refreshed before continuing. An official webpage returned HTTP403 to urllib; its linked public CDN photograph downloaded successfully.
- Closing verification: queue displays the new selected product and $142 total; original source V2 worktree remains clean. Saved browser screenshots show the photographic front and enlarged message controls. No approval or purchase was performed during this revision.

## Front quality revision

- Replaced the low-resolution overhead photo with versioned generated photographic artwork based on public office references. Matches the approved reference's cream texture, frame and footer; provenance explicitly distinguishes generated composition from documentary photography.
- Targeted v2-to-v3 card migration preserves customized fronts, message edits, approval snapshots and credit history. Unapproved mailers require review again after the visual change; migration is idempotent.
- 33 focused tests passed, including migration/approval regression. Browser verified both inline/enlarged front and Front / Message toggles; left the new front open on port 3000. No changes to source V2 worktree.
- Source discovery: architect/gallery pages returned HTTP403 and a gallery thumbnail returned404; official CDN/reference image downloads worked. No authentication or access controls were changed.
- Closing checks: production build/type checking passed; lint passed with 0 errors and the same 11 unrelated warnings. Diff whitespace check passed. All work remains local.

## Queue formatting

- Formatting-only revision of the local Direct Mail queue: standard 14px primary text, 13px secondary text, larger account/product images, clearer material controls, right-aligned estimate, and the existing outline-button treatment for Review/Track. Removed redundant row wording.
- Kept account-level materials distinct from recipient mailers; no fixture data, approvals, branding, or new accounts changed. Source V2 worktree stayed clean.
- Browser verified the table without horizontal overflow at the current desktop width, the landing-page preview, and the Review link; screenshot saved at `/private/tmp/illumio-queue-formatted.png`.
- Design-system build, production build/TypeScript and whitespace checks passed. Lint: zero errors, 11 existing unrelated warnings. Initial build command ran from repo root and failed because the frontend package lives under apps/frontend; rerun there passed. No new tests added for this presentation-only change.
- Browser binding was stale; resetting the CUA session restored access. No push or deployment.

## Gift review cleanup

- Removed the duplicate accompanying-message section from gift selection; the editable note and card review remain in the next step. Shortened built-in research and recommendation copy.
- Gift cards now place retailer links immediately below photos, use the design-system green Recommended badge, and align price/selection footers. Native radio inputs support keyboard arrows; links remain separate interactive controls.
- Exact previous fixture wording refreshes on load without replacing custom text, selected products, notes, approved records or credit history. Added a regression for that boundary.
- Browser verified selection, keyboard navigation, links directly below all three photos, no card overflow, and progression to the unchanged note step. Restored the recommended selection and left the gift review open on port 3000. Proof: `/private/tmp/illumio-gift-review-refined.png`.
- Design-system build, production build/TypeScript, 12 focused tests and whitespace checks passed. Lint: 0 errors, 11 pre-existing warnings. The new regression initially used the pre-review revision for approval; corrected the test to use the returned revision and reran successfully. CUA stale binding recovered with a session reset.
- Source V2 worktree remains clean; no production changes, ordering, pushing or deployment.

## Insight-based gift alternatives

- Added four provenance-linked public insights and three distinct gift directions; retained the recommended product. Research and catalog data stay in the fixture seam, not presentation components. Additional verified products can be selected from a modal without losing prior options.
- Alternative-search feedback persists locally; the UI names the unconnected live-search boundary and the repository blocks generic synthetic recommendations for sourced records. No actual agent run or purchasing integration was added.
- Gift changes preserve customized notes. Exact suggested wording from a different gift must be updated before review; fitting suggested copy is available in the note step. Existing exact-text handwriting artwork remains bound to its original text.
- Added migration, selection/cost, note-readiness and request-preservation coverage. All 25 focused tests passed. Initial tests exposed an overlong note and obsolete product assumptions; shortened the suggestions and updated the fixture assertions. The tsx CLI hit sandbox IPC permissions; `node --import tsx --test` ran without escalation. Bare tsc includes existing unrelated test errors; Next's production build and its TypeScript check passed.
- Browser verified source dialogs, actual product photos, choosing/restoring an alternate, note suggestions and feedback persistence. Final draft retains the recommended gift and original note. Other accounts, the source V2 worktree and production remain untouched.
- Official LEGO page rejected a direct HTML fetch; used the public retailer image identified in image search. No access controls were bypassed. Source and media URLs are recorded in the demo documentation.
- Closing checks: design-system build, production build/TypeScript and 25 focused tests passed. Lint: zero errors, the same 11 unrelated warnings. Browser confirmed all three product images load, no horizontal overflow, restored recommendation and exact handwritten note, and persistence/cancellation of the test feedback. Screenshot: `/private/tmp/illumio-insight-gifts.png`. No push, send, order or deployment.

## Gift message synchronization and recovery

- Fixed disabled review controls caused by a recovery draft's older revision. Drafts now retain editable-field baselines; unrelated changes merge on save, while overlapping edits open a comparison dialog. Removed the persistent conflict banner; kept optimistic revision checks and approved-record locks.
- Gift selection updates note and preview immediately, including recovered legacy gift-only drafts and alternative picks. Custom wording is retained per gift and restored on return. All five researched choices have distinct prepared note text and exact-text handwritten artwork; editable fallback retains branding and QR.
- Revised copy using prior pilot structure without importing corpus data. Narrow migration updates only exact old fixture suggestions; custom text and approvals survive. Generated variants are local prepared assets, not live agent generation.
- Full frontend suite: 3,731 passed, 5 skipped, zero failures. Final focused editor/fixture suite: 15 passed. Design-system build and production build/TypeScript passed; lint has zero errors and 11 existing warnings. Browser verified immediate book/LEGO note switching, restored the recommended gift, opened alternatives/feedback, and progressed through Continue. Proof: `/private/tmp/illumio-gift-matched-note.png`.
- Initial npm test hit tsx IPC sandbox restrictions; approved local-IPC rerun passed. An edit script first used the wrong cwd and was rerun at repo root. Inline ESM evaluation was incompatible with tsx's CommonJS output; CommonJS evaluation succeeded. Auto-review blocked reloading the user's tab due to unsaved-edit risk; verification used a separate tab, preserving the original. Superseded generated drafts were left outside the repo.
- Source Harvey/V2 worktree stayed clean; no production changes, approval, ordering, sends, or push. Port 3000 left at gift selection with the three requested controls enabled.

## Local presentation hostname

- Added `illumio.clue.test` mapped to IPv6 loopback in this Mac's `/etc/hosts`, through the macOS administrator prompt. Port 3000 remains the same loopback-only preview process; original localhost address still works.
- Added the exact hostname to Next's `allowedDevOrigins` so development assets and hot reload can use it. No wildcard or network binding expansion.
- Verified HTTP 200 at the custom address and opened the gift/card review in a separate browser tab. New origins have separate browser storage; original localhost drafts were not migrated, cleared or reloaded.
- HTTP custom host is for local presentation, not a public deployment or TLS setup. Browser APIs restricted to secure contexts are not covered by this verification.
- No source Harvey/V2 changes, ordering, approvals, or push.

## Recording sidebar parity

- Verified the deployed project's name and four chat titles/order through a read-only browser visit. Added a fixture-only sidebar snapshot through the existing repository seam; reused the existing sidebar tokens, folder icons, row spacing and hover controls.
- Source chat links open their verified deployed conversations in a separate tab. No chat content was fabricated/copied and no live mutation occurred. Default fixture catalogs and HTTP repositories remain unchanged.
- Browser confirmed the local custom-host queue displays the single expanded project and four matching chats. Proof: `/private/tmp/illumio-sidebar-matched.png`. A stale browser binding was recovered by resetting the CUA session; the current tab was not reloaded.
- Design-system build, production build/TypeScript, seven existing sidebar/controller tests and isolated adapter assertions passed. Lint: zero errors, the same 11 existing warnings. Changes stay in the Illumio checkout; no push.
