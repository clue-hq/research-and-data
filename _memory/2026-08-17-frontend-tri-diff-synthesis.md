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
