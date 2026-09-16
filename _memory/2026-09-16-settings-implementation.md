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
