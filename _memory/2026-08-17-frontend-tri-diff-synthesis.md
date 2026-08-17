# 2026-08-17 — Tri-area diff: codex/chat-shell tip (c7f2bc5) vs integrated apps/frontend

Three Opus agents compared chat / projects / skeleton areas. Full reports in the session task
outputs; this note carries the load-bearing conclusions for future sessions.

## Meta-facts (verified, de-risking)
1. **Zero design-system drift**: tokens.css md5-identical (348 vars), globals.css byte-identical,
   ui/* + ai-elements/* + fonts identical. Lifted components can never be silently unstyled.
2. **Their chat pane is EMPTY** (`<div aria-label="Conversation"/>`, composer wired to no-ops).
   Chat adoption = slot OUR ChatTranscript/gates/composer into their geometry slots
   (.conversationStage / .composerDock). There is no "their chat" to port.
3. **Our composer is newer than theirs**: their components/chat/* is an ancestor fork lacking 4
   production fixes (submit accept/reject+lock, clearSubmittedDraft w/ undo scrub, controlled
   prompt vs blur-only, external entity sync + paragraph-leak fix). KEEP OURS; optionally move to
   components/chat/ path.
4. **Their features/accounts is FROZEN at the design baseline** (no commits since ancestor).
   100% of accounts visual drift is ours-side. 16 presentation files to regress to theirs
   (biggest: accounts-table, account-detail-screen, account-detail-primitives); keep our
   hooks/data/model; 6 ours-only undesigned components need founder ruling (account-facts,
   evidence-list, table-pagination, account-avatar, accounts-recovery-screen, bulk props).
5. **Onboarding: zero parity debt.** Shell: ours superset; ONE merge file = project-sidebar-tree
   (their .projectLink + 32px toggle markup/CSS × our projectMutationsAvailable gating).
6. **Their prototype features/projects tree is dead code in their own tree** (routes redirect;
   nothing imports ProjectWorkspaceShell there). Do not adopt; separate cleanup PR later.

## Route architecture (their as-built, commit e03b4cb)
- `/projects/{id}` = pure redirect: ?thread= → /projects/{id}/chats/{thread} (forwards params);
  threadless → gallery href. `/projects/{id}/chats/{chatId}` = canonical chat.
  `/projects/{id}/artifacts/{artifactId}` (+?kind,thread,edit,selection). `/chat/*` = legacy shims.
- **Pane state = ?surface= (chat|gallery|web|ad) + ?edit=1 + ?selection= — there is NO ?artifact=
  param anywhere in their tree.** The ratified ?artifact= conflicts with as-built; founder must
  reconcile (R2 below).
- chat-shell-routes.ts liftable verbatim (46L, dep-free) EXCEPT projectGalleryHref hardcodes
  fixture id "thread-primary" — cannot ship.
- Backend href emitters to flip in lockstep (4 sites): platform/api/clue_api/chat/schemas.py:299,
  router.py:903,912,977. Our Zod guards (startsWith "/projects/") tolerate both shapes → ordering free.
- Our ?thread= emitters/readers sweep (complete): use-add-to-chat-controller:151,
  chat-threads.repository:137, project-home.repository:74/81, chat.fixture:29/39,
  sidebar-projects.fixture (8 hrefs), account-workspace-screens:233;
  readers: projects/[projectId]/page.tsx, gallery/page.tsx,
  use-project-chat-controller replaceThreadInRoute:221-227 + selectThread:827 (doesn't write URL;
  remount via key in project-workspace-shell), application-shell:40 ok as-is.
  Tests asserting old shape: sidebar-projects.repository.test:36, project-home.repository.test:80/93/128,
  chat-repositories.test:104, chat-schemas.test:92. Contract docs conflict: our projects.md documents
  ?thread= (6 places); theirs forbids it (projects.md:301-315 canonical table).

## Founder rulings register — RATIFIED 2026-08-17 (R1-R8 answered verbatim)
R1 /projects/{id}: **adopt their redirect semantics.**
R2 pane-state vocab: **adopt their as-built ?surface=/edit=/selection=.** SUPERSEDES the earlier
   ratified ?artifact= param (the W-plan and editor-surface.tsx header note must be amended when
   next touched; split view mounts via surface=web|ad on the chats route).
R3 gallery URL: **compat-redirect like theirs.** (Threadless entry: /projects/{id} renders the
   workspace which client-canonicalizes to /chats/{resolved-thread} — redirect semantics with
   production thread resolution; "thread-primary" fallback deleted from the lifted helper.)
R4 thread switcher: **accepted — no in-shell switcher; deliberate design decision.** Sidebar owns
   thread switching; the in-pane <select> goes away in Phase C.
R5 session-menu Delete: **build the UI, keep it inert for now** (visible-but-inert pattern, like
   the editor contract's §3 items).
R6 inspector-replaces-conversation while editing: **accepted for v1; founder personally owns
   revisiting during design-editor integration.**
R7 shell mount owner: **our layout-level mount; strip ApplicationShell from lifted views.**
R8 auth-era screens (SessionControls overlay, select-workspace, access-denied): **leave as-is;
   do not design now.**
R9 six ours-only accounts components — STILL OPEN; goes with the co-founder parity handoff.
R10 THREAD_NOT_FOUND under path segment — not explicitly ruled; conservative default adopted:
    keep the existing in-pane alert (no new UI), canonicalization uses router.replace.

## Key landmines (full lists in reports)
Missing /icons/chat/* (5 svgs) + 4 public binaries; 23 chat CSS classes absent from our bisected
module; stub window.dispatchEvent bus behind rename/archive/delete (no listener anywhere);
getProjectWorkspace returns null in HTTP mode (their route crashes if lifted);
ProjectWorkspaceSchema .strict() with artifacts z.tuple([]); ProjectEntity.version load-bearing
for contextRefs; ?handoff= writer races replaceThreadInRoute; **[H12 CORRECTED by founder review 2026-08-17:
App Router does NOT remount on dynamic-param change — the shell's remount key is the ONLY
URL→thread mechanism and MUST STAY; navigation becomes the single switch mechanism
(selectThread=push, canonicalization=replace, no internal setActiveThreadId double-path)]**; dead gallery CSS in project-flow.module.css invites wrong reuse;
route files dropped outside (protected) silently bypass auth.

## PHASE R COMPLETE — close-out 2026-08-17

All seven tasks landed on `integration/frontend-design-part-iv-v2` (faf3383d R-1 helpers,
2866dac9 R-2 chats route, 1302ccd3 R-3 single-mechanism writers, f104ff02 R-4 absorber+gallery
compat, 3135cc9f R-5 frontend emitters, 53251541 R-6 backend+contract docs, R-7 supersessions+
verification). **The chats path is canonical end to end**: every entry point (sidebar links,
home bootstrap href, add-to-chat push, legacy ?thread= deep links, threadless project/gallery
entries) lands on /projects/{id}/chats/{chatId} rendering the unchanged production chat;
?thread= survives only as the absorber redirect; ?surface=gallery carries the Gallery intent
through the whole chain.

Two founder review-catches shaped the implementation (both recorded in the plan):
(1) the remount key is the ONLY URL→thread mechanism (App Router preserves client state on
dynamic-param navigation) — kept, with navigation as the single switch mechanism and
activeThreadId's setter deleted so a second mechanism is a compile error; (2) threadless
gallery links carry ?surface=gallery through the absorber so the Gallery intent survives.

R-7 browser verification (fixture mode, worktree-local server, zero console errors): legacy
deep link redirects w/ right thread; sidebar click → chats path; **handoff restore validates
threadId against the PATH param** (seeded sessionStorage handoff restored its entity chip);
send-time ?handoff= cleanup fired with path preserved (cleanup is gated on accepted
submission — its firing proves acceptance; failed-restore keeping ?handoff= in the URL is
pre-existing designed semantics, restore-until-sent); canonicalization leaves no residue,
back-button returns to prior thread; surface=gallery → artifacts pane; transcript + gate card
(+ actions) render on the chats route. Gates: frontend 330/330 + lint + build; make check
2816 passed / 5 failed — all five the documented pre-existing set (o3, pilot-budget ×3,
unified-gate head pin), zero new.

**Next:** Phase C (chat chrome) is unblocked — see its plan doc. The R2 supersession
(?artifact= → ?surface=) is annotated in the W-plan, editor-surface.tsx, and the contract doc.
Backend flip note for other branches: thread_href in chat/schemas.py is the single emitter;
merging branches must not reintroduce inline href builds.

## PHASE C COMPLETE — close-out 2026-08-17

All five tasks landed on this branch (02bd485c C-1 CSS restore + de668a88 editor-surface
grid pin, 499a6028 C-2 header/session-menu, 9d6702b1 C-3 chat surface, 1233d1b1 C-4 home
variant, C-5 audit+close-out). **The chats route renders the co-founder's chat shell around
production chat**: main.shell geometry (chat pane: ChatShellHeader + conversationStage +
composerDock; artifact rail: ArtifactStage), our transcript/gates/queue-Stop/refusal
alerts/composer slotted in with wiring untouched, rename/archive wired to the real
controller, Delete rendered-but-inert (R5, no aria-live), no in-shell thread switcher (R4),
no embedded ApplicationShell (R7), R6 inspector-replaces-conversation implemented as
designed. ?surface=/edit=/selection= read once at mount (no URL write-back — known
deferral matching the dummy).

Load-bearing implementation rulings (full trail in .superpowers/sdd ledger, distilled here):
(1) **ProjectApplicationShell now mounts /projects/* rail+pinned-expanded** except
/projects/{id}/artifacts/* (overlay/collapsed, W0.4-verified) — the dummy's as-built chat
mount, and required: R4 makes the sidebar the ONLY thread switcher and the old in-page
trigger died with ProjectWorkspaceView. (2) ConversationPane, ProjectWorkspaceView,
ArtifactWorkspace **deleted** (orphaned by the view-layer swap; old ArtifactWorkspace was a
hardcoded empty state, so surface=gallery → the lifted gallery loses nothing). (3) The
editor-shell reducer gained the panelOpen pair (default true → artifact route untouched);
editorVisible additionally requires a non-null artifactKind so ?surface=web&edit=1 with no
artifacts collapses to conversation, never an empty chatBody. (4) ChatShellHeader carries a
required onArchive (the produces-line omitted it; R5 requires Archive wired). (5) C-5 audit
removed the dead lifts C-1 Step-2 deferred: .chatTitleButton* family (unreferenced in BOTH
trees; title = chatTitleLabel span + rename input) and the two W0.5-restored
.galleryEmptyStage blocks (the lifted gallery renders its own empty state). Coverage now:
every styles.* ref resolves except inspectorSectionCompact (documented upstream defect);
zero unreferenced classes.

Verification: parity pairs in /tmp/phase-c-parity/ (chat empty + transcript, session menu,
rename-in-place, gallery surface, maximized, vs 3080); reduced-motion emulated live
(transition-duration 0s on .shell/.composerFrame); production behaviors all proven on the
new surface (send, gate card + actions, rename round-trip, archive path, Delete no-op,
handoff chip restore from seeded sessionStorage, legacy-redirect chains). Gates 353/353 +
lint + design-system:build + build. **Upstream re-sync: zero drift** — codex/chat-shell tip
still c7f2bc5, the exact commit every lift came from.

Known-open (deliberate):
- **R6 deferral**: while editing, the inspector replaces the conversation (running turn's
  gate/Stop invisible mid-edit) — founder personally revisits during design-editor
  integration. Implemented as designed; do not soften without that ruling.
- **Artifact tabs legitimately empty until W1.3**: workspace.artifacts is z.tuple([]) — the
  rail shows only the Gallery tab and the gallery its designed empty state. No fabrication.
- **Sidebar label after rename**: the header title updates via loadThreads; the sidebar's
  conversation label is the separate sidebar-projects source and stays stale in fixture
  mode (production invalidation is its own seam). Pre-existing shape, not Phase-C.
- **Sidebar "New chat" doesn't navigate in fixture mode** (observed during C-5): the
  untouched use-sidebar-projects-controller createConversation path clicks, creates, but no
  route change and no console error; not a Phase-C surface (zero Phase-C files in the
  path). Needs its own triage — likely a fixture project-id mismatch between
  sidebar-projects and chat-threads fixtures.

**Next:** the W-lane hydrates the ?surface=web|ad split view (W1.3 read seam feeds the tabs
and gallery); Lane 3 accounts parity runs independently; the R2/R4-R7 rulings and the
supersession notes stay binding for both.

## Plan (agreed shape, pending founder go)
Phase R (me, ~2d): route slice — helper lift, /chats/[chatId] route rendering OUR
ProjectWorkspaceShell, /projects/{id} absorber redirect, emitter/reader flips, backend href flip,
tests+contract docs. Needs R1-R3, R10.
Phase C (me, ~4-6d, after R): chat chrome adoption — CSS block + header + session menu + view
geometry; slot our transcript/composer; rewire stub bus to renameThread/archiveThread; keep our
composer (+variant="home"). Needs R4-R7.
Phase A (co-founder, parallel): accounts parity regress-to-baseline (16 files) on a feature
branch off this lineage; R9 rulings; theirs' frozen tree = reference.
W1 editor work continues parallel; R2 outcome may amend the W-plan's ?artifact= assumption.
Dead-code cleanup (both trees' dead masses) = separate later PR.
