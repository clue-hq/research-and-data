# Settings remaining integration — 2026-09-16

Implementation in Irvine, branch `settings-page`, from planning checkpoint `9fca86808`.
User authorized the completion plan; D1–D8 are implementation recommendations being applied.
Research fields frames/primitive reuse and Pages snippet/default contracts still need resolution;
asynchronous questions are pending. No complete/live-accepted claim is justified.

Implemented so far: manage-settings permission and authenticated project shell profile; shared
transactional manager authority; research registry migration `3a75cb367c2b`; scoped create/edit/
retire API; all three research catalog callers use workspace menus; retirement/global-key collision
protection; custom values and evidence projections in progress. Suspended members remain read-only;
invitation retry remains revoke then invite. Pages/Billing dummy and other inert previews retained.

Verification: migration up/down/up on three disposable Irvine DBs passed. Most recent focused
backend run: 144 tests passed (auth, registry, lenient writer, account catalogs/driver). Two earlier
new-test setup mistakes (error envelope and required fixture columns) corrected. Frontend tsc
exposed fixture updates needed for additive payload fields, now being corrected; other errors in
untouched files require baseline attribution. Full gate and browser verification still pending.

No live migration, runtime restart, provider email, or remote push performed this implementation
session yet. Temporary verification runner reads ignored runtime credentials without printing them
and creates/drops a separate disposable database. Never migrate a sibling worktree database.


Verification checkpoint: production Next build passed; all 2,283 frontend tests passed after
updating the source-chip structural test for the shared component; lint has only two unchanged
design-editor warnings; design-system build and all 27 import contracts passed. Standalone tsc
still reports 50 errors in unchanged tests; the same locations/codes exist in a clean HEAD archive
(the archive additionally lacks generated vendor declarations). Full mypy reports four existing
errors in ad_assets, account_research_claims and career-date narrowing in account_research_driver;
this slice does not change those lines. New/changed Python passes focused Ruff checks.

Runtime upgraded: verified Irvine DB identity and zero claimed tasks, stopped only its recorded
API and three workers, migrated `27aa2ae947bc` through the rebased join to `3a75cb367c2b`, restarted
API PID 18244 and workers 18247/18376/18520; all report ready. Redis/design/frontend retained. The
47 queued tasks were preserved. Runtime startup/migration evidence is ignored under
`.runtime/settings-live/`. Historical design pin `64232a0` resolves in clue-frontend/port-of-spain;
its Data model still has the old dummy columns, not the requested Research fields redraw.


Closing automated checkpoint: 496 combined backend tests passed (auth, registry, lifecycle/races,
Client-KB, account/person catalog/store/driver/launch/tools/claims, all account/contact projections).
Custom evidence tests cover retirement and erasure as well as subject/workspace isolation. The
expanded accounts-list run exposed a missing ARV2 pack seed in an existing scope assertion and an
expected-payload update for additive claimId; both corrected without weakening assertions. Final
throwaway DB was removed. Backend saved in local commit `6d63a7c36`.

Browser through ChatGPT/CUA: Profile display name temporarily changed, persisted across reload,
appeared in main shell menu, then original value restored and reload-verified. Members renders
without long-email cell overlap at the current viewport. Current signed-in workspace is the
existing onboarding workspace (not the earlier design demo); no sibling services used.

Invitation acceptance is still blocked: the previously authorized recipient was entered with
Member visibly selected. Automatic approval review twice refused the Send click, reporting Admin
access despite the screenshot/AX Member selector. No invitation was sent and no alternative API
send attempted. Requested explicit Member-role approval asynchronously. Preserve this pending
form for follow-up; do not claim delivery/receipt/acceptance. Research fields visual gate and
Pages contract questions also remain unanswered. No new paid research launched.


Frontend checkpoint saved as `89089dca8`. Direct browser navigation to the authenticated API URL
was refused by the browser with ERR_BLOCKED_BY_CLIENT; did not bypass through page fetch/evaluate.
The real API lifecycle is verified through the authenticated ASGI suite; browser create/edit/retire
still awaits the management screen. No network/provider-readiness or paid research claim is made.


Final follow-up: 15 focused registry/API tests passed on a fresh disposable DB, including actual
research-vocabulary erasure (create/edit/retire/write all refuse afterward), cross-workspace ASGI
reads/writes, strict payload validation, and simulated revocation after principal resolution for
POST/PATCH/DELETE. All temporary verification DBs were removed. Updated the specification's
previously conflicting trigger, catalog-caller, lenient-fallback and custom-column clauses to match
D1–D8; checklist now distinguishes completed code from outstanding UI and live acceptance.

Remaining user inputs: Research fields frames or approval to reuse Settings primitives; Pages V1
metadata/defaults, fallback and snippet/form contract; explicit Member invitation approval requested
after automatic review refused the UI send. No email was sent. No paid research was launched.
No remote push. Preserve the prepared Members tab for the next authorized action.

Invitation follow-up: explicit Member-role approval was received; the browser successfully sent
the approved invitation, and its pending Member row survived reload. The user confirmed email
receipt, then reported acceptance stopping after first/last name with a generic verification error.
Live read-only Clerk environment inspection confirmed password is required; names are optional,
legal consent and MFA requirements are off. Our ticket-only form omitted the password entirely.

Fixed invitation signup to collect the password and use Clerk v7
`create({strategy: "ticket", ...})` (the `ticket()` helper does not accept a password). Inputs now
survive errors via a normal client submit handler; only complete signup can finalize, and provider
password-policy errors remain visible. Credentials stay browser-to-Clerk. No auth settings changed,
no real ticket consumed, and no invitee password entered by the agent.

Verification: 13 focused auth tests and all 2,287 frontend tests passed; design-system build,
lint (two existing design-editor warnings) and production build passed. Initial npm test was
blocked by sandbox IPC and passed after escalation. Public Clerk config read needed network
escalation. Native Arc inspection stalled and returned an unrelated page; a separate form preview
at the IPv4 loopback address was connection-refused. Neither establishes browser acceptance proof.
User must refresh the original invitation page, choose a password and finish acceptance; final
membership/redirect validation remains outstanding. No remote push.

Responsive Settings follow-up: replaced the <=860px horizontal navigation with a sidebar icon
beside the page heading and a vertical left drawer. Desktop and mobile share SettingsNavigation;
Base UI Dialog owns focus trapping, Escape, outside-click dismissal and focus restoration. Picking
a destination or resizing to desktop closes the drawer. Existing product tokens and sidebar icon
are reused; coarse pointers get a 44px target and reduced-motion disables transitions.

Verification through ChatGPT/CUA: checked 739x988 Members, 390x844 Profile and 1280x900 desktop;
opening, keyboard focus wrap, Escape/return focus, route selection, outside click and open-drawer
resize to desktop all passed. Temporary viewport override reset; original Members tab restored.
Design-system build, lint and production Next build/type check passed. Lint retains only the two
existing design-editor warnings. git diff --check passed. No new standalone tests for this small
UI change; interactions were exercised in the real authenticated app.

Invitation acceptance follow-up: the user confirmed acceptance now works. Fresh Members reload
shows the approved test invitee as a joined Member with the current joined date. This closes the
send/receipt/signup/acceptance proof; the invitee's own selected workspace/redirect remains a
separate unobserved check. Role/removal/re-admission live checks and Research fields/Pages work
remain open as listed in the plan. No additional invitations, role changes or remote push.

Research fields design review: user requested a preview before approving implementation. Created
an interactive conversation preview, `research-fields-preview.html`, in this thread's authorized
visualizations directory (2026/09/14/01a0a13b-d662-7fb3-b5d3-c1aef092523a). It demonstrates the
Accounts/Contacts overview, field list, inline Create form and collision feedback, inline edits,
and two-step retirement. Samples only; no application API calls or application source edits.
Design review controls offer Admin/Member presentation and comfortable/compact row spacing.

Browser verification passed for sample create, duplicate error, description edit/save, retirement,
and 390px/1024px layouts. The standalone renderer blocks form submission by design, so preview
Create uses a local button handler; this is not an application implementation decision. Initial
serve needed sandbox escalation; one exact-label locator missed required-field text and was
replaced with its observed input ID. Research fields visual approval and live integration remain
pending. User-facing preview is inline; temporary browser/server used only for verification.

Research fields implementation: founder approved the preview, satisfying the visual gate. Replaced
the old Data model dummy/Display controls and fixture schema/data with the live entity registry,
retained Accounts/Contacts overview and field routes, redirected legacy Display links, and renamed
navigation to Research fields. Added the inline Create form, typed field errors, shared autosave
name/description editors, two-step retire menu, origin/creator/date and responsive stacked cells.
Reused existing tokens, Base UI menus, inputs/buttons and confirmation cards. Scope-keyed controller
invalidates late responses, blocks duplicate submissions and merges only the submitted attribute.
Shared autosave adds multiline semantics, unmount guards, Escape rollback and keyboard focus return.

Verification: 2,298 frontend tests passed, including new lifecycle/concurrency/scope controller tests
and actual server rendering for manager/member/platform/empty states. Design-system generation,
lint (only two pre-existing design-editor warnings), production build/type checking passed. New
test setup initially failed on top-level await/CommonJS and CSS modules, then corrected; first lint
flagged ambiguous returned-ref naming, corrected by explicit Ref-suffixed destructuring. tsx needs
escalation for its local IPC socket. No backend/schema/process changes or new dependencies.

Real ChatGPT browser checks on Irvine :3147: list reads show the actual registry; created temporary
`account.settings_acceptance_check_20260916`, edited description and label, verified reload persistence,
Escape rollback, Enter/Ctrl+Enter saves/focus restoration, inline duplicate-name error, Accounts vs
Contacts scope and legacy Display redirect. Mobile 390px and narrow desktop 739px are readable;
Members still has no cell overlap. Viewport reset. No paid research started. The temporary field's
label is now "Settings acceptance check 20260916 renamed"; Confirm retire is prepared in the browser.
Requested at-action approval for irreversible retirement per the browser confirmation policy;
final live retirement/reload awaits that answer. Generated research/evidence, the invitee's selected
workspace, remaining member lifecycle checks and Pages remain separate open acceptance/contract work.
