"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useDiscoveryStatus } from "@/features/accounts/hooks/use-discovery-status";
import { ConversationContent } from "@/features/projects/components/conversation-content";
import { ProjectComposer } from "@/features/projects/components/project-composer";
import {
  composerRunControl,
  type ProjectChatController,
} from "@/features/projects/hooks/use-project-chat-controller";
import { useChatAttachments } from "@/features/projects/hooks/use-chat-attachments";
import { useDesignReferenceAttachments } from "@/features/projects/hooks/use-design-reference-attachments";
import { CHAT_ATTACHMENT_ACCEPT } from "@/features/projects/model/chat-attachments";
import { buildComposerCatalog } from "@/features/projects/model/composer-context-catalog";
import {
  DESIGN_REFERENCE_ACCEPT,
  MAX_DESIGN_REFERENCE_ATTACHMENTS,
} from "@/features/projects/model/design-reference-attachments";
import type { useProjectWorkspaceController } from "@/features/projects/hooks/use-project-workspace-controller";
import { useAddToOpenChatController } from "@/features/projects/hooks/use-add-to-open-chat-controller";
import { ResearchProgressCard } from "@/features/projects/components/research-progress-card";
import { openClarification } from "@/features/projects/model/clarification";
import { useResearchProgressController } from "@/features/projects/hooks/use-research-progress-controller";
import type {
  ProjectArtifact,
  ProjectWorkspace,
} from "@/features/projects/model/project-workspace";
import type { WebAnnotation } from "@/features/design-editor/adapter/annotations";
import { useSceneEditingSession } from "@/features/design-editor/hooks/use-scene-editing-session";
import { useSceneLiveReveal } from "@/features/design-editor/hooks/use-scene-live-reveal";
import type { Operation } from "@/features/design-editor/engine/scene/contracts";
import { useWebEditingSession } from "@/features/design-editor/hooks/use-web-editing-session";
import { useArtifactRename } from "../hooks/use-artifact-rename";
import { useEditorShellController } from "../hooks/use-editor-shell-controller";
import { useFileDrop } from "../hooks/use-file-drop";
import { agentRunLockForThread } from "../model/agent-run-lock";
import { artifactsToAutoOpen } from "../model/artifact-auto-open";
import { isWebsiteKind } from "../model/artifact-kind";
import { routeAttachmentFiles } from "../model/attachment-routing";
import {
  chatDockContent,
  chatDockDismissedBySubmission,
  chatDockOpen,
} from "../model/chat-dock";
import {
  chatSurfacePaneParams,
  chatSurfaceUrlState,
} from "../model/chat-surface-params";
import { discoveryLaunchToOpen } from "../model/discovery-launch-signal";
import {
  ANNOTATIONS_ONLY_MESSAGE,
  annotationChips,
  annotationContextRefs,
  editTargetChips,
  editTargetContextRefs,
} from "../model/edit-targets";
import { galleryCardTarget } from "../model/gallery-card-target";
import { openArtifactFromParam } from "../model/open-artifact-param";
import { useProjectDocuments } from "@/features/projects/hooks/use-project-documents";
import { useProjectDocumentTabs } from "@/features/projects/hooks/use-project-document-tabs";
import { ArtifactStage } from "./artifact-stage";
import { AssetLibraryPanel } from "./asset-library-panel";
import { ChatShellHeader } from "./chat-shell-header";
import { ClarificationCard } from "./clarification-card";
import { ImageInspector } from "./image-inspector";
import styles from "./chat-shell.module.css";
import { WebInspector } from "./web-inspector";

// The chats route's view layer (Phase C, C-3): the co-founder's chat-shell
// geometry — chat pane (header + conversation stage + composer dock) beside
// the artifact rail — re-authored from the branch's chat-shell-view around
// OUR production chat plane. The design's conversation area was an empty
// <div> and its composer was wired to no-ops, so adoption is pure frame
// adoption: our transcript, gate cards, queue/Stop banner, refusal alerts,
// and composer slot into the design's slots; all chat wiring is untouched.
//
// Founder rulings in force (2026-08-17):
// - R7: no embedded <ApplicationShell> — the (protected) layout owns the app
//   shell; this component's root is main.shell.
// - R4: no in-pane thread switcher or new-thread affordance — the sidebar
//   owns thread switching.
// - R6 (accepted for v1): while editing a web/ad artifact the inspector
//   replaces the conversation column — a running turn's gate or Stop is
//   invisible mid-edit. The founder personally owns revisiting this during
//   editor integration.
// - R5: the session menu's Delete renders but is inert (see the menu
//   controller).
//
// URL pane state (?surface=/edit=/selection=, ruling R2) is read once at
// mount as initial state, and — since chat-flow slice 5 — written back on
// every pane change, so every editing state the user reaches is a shareable
// deep link. Hydration stays one-directional: the effect below only calls
// router.replace; it never feeds the URL back into the shell state.

/** One stable empty feed, so a page mounted without artifacts does not hand
 * the auto-open effect a new array identity on every render. */
const NO_ARTIFACTS: ProjectArtifact[] = [];

/** Every tool call id in the transcript whose part has landed (`output-available`). */
function completedToolCallIds(transcript: ProjectChatController["transcript"]): string[] {
  return transcript.flatMap((message) =>
    message.parts.flatMap((part) =>
      part.kind === "tool" && part.state === "output-available" ? [part.toolCallId] : [],
    ),
  );
}

export function ChatSurface({
  artifacts,
  canEditDocuments = false,
  chat,
  controller,
  documentIds,
  paneState,
  projectId,
  workspace,
}: {
  /** Chat-flow slice 1: the chats page's server-fetched gallery feed — the
   * rail's real cards (the artifact route's exact `loadGalleryFeed` shape).
   * Absent → the gallery keeps its honest empty state; the feed rides these
   * props, never the workspace schema (`workspace.artifacts` stays the
   * schema-hard empty tuple). */
  artifacts?: ProjectArtifact[];
  canEditDocuments?: boolean;
  chat: ProjectChatController;
  controller: ReturnType<typeof useProjectWorkspaceController>;
  /** Artifact id → design-document id over the whole feed. Consumed by the
   * shared editing session (slice 3): the active tab's entry mounts the real
   * web render in the rail's canvas; a tab without one keeps the empty
   * canvas. */
  documentIds?: Record<string, string>;
  paneState: { edit?: string; selection?: string; surface?: string };
  projectId: string;
  workspace: ProjectWorkspace;
}) {
  const urlState = chatSurfaceUrlState(paneState);
  // The Target accounts tab's "Add to chat": prepared against THIS project and
  // the open thread, landing in this mount's composer (no picker, no navigation).
  const addToOpenChat = useAddToOpenChatController({
    onAdded: controller.addEntities,
    onFailed: controller.failContextHandoff,
    projectId,
    threadId: chat.activeThreadId ?? undefined,
  });
  // The Target accounts tab's live poll (spec 2026-09-12 §3): the status decides the spinner,
  // each read bumps the token the tab refetches on, and the launch signal primes the first read.
  const [discoveryPrime, setDiscoveryPrime] = useState(0);
  const discovery = useDiscoveryStatus(projectId, { prime: discoveryPrime });
  // The pinned research card (spec 2026-09-12): one per project, above the composer, alive
  // while the read returns a card. A completed ARV2 research launch primes the read — both
  // `launch_arv2_account_research` and `launch_arv2_person_research` create research jobs, so
  // either one is enough to make the next read find a card (the old lane's
  // `launch_account_research` is superseded and is NOT matched).
  const [researchPrime, setResearchPrime] = useState(0);
  const research = useResearchProgressController(projectId, { prime: researchPrime });
  const knownResearchLaunchIds = useRef<Set<string> | null>(null);
  useEffect(() => {
    const known = knownResearchLaunchIds.current;
    const ids = chat.transcript.flatMap((message) =>
      message.parts.flatMap((part) =>
        part.kind === "tool" &&
        (part.toolName === "launch_arv2_account_research" ||
          part.toolName === "launch_arv2_person_research") &&
        part.state === "output-available"
          ? [part.toolCallId]
          : [],
      ),
    );
    if (known === null) {
      // Same discipline as the discovery launch signal above: the transcript is fetched in a
      // client effect, so snapshotting before it lands would bank an EMPTY set and the replayed
      // backlog's own persisted launch part would read as new on every visit.
      if (chat.loading) return;
      knownResearchLaunchIds.current = new Set(ids);
      return;
    }
    const fresh = ids.filter((id) => !known.has(id));
    for (const id of ids) known.add(id);
    if (fresh.length) setResearchPrime((current) => current + 1);
  }, [chat.loading, chat.transcript]);
  const shell = useEditorShellController({
    editing: urlState.editing,
    inspectorSelection: urlState.inspectorSelection,
    panelOpen: urlState.panelOpen,
    projectId,
    surface: urlState.surface,
  });
  // Task 4 (scene live-streaming rung A) — THE EDITOR LOCK.
  //
  // Founder ruling: no mid-run manual editing, ever. Task 1 put the 409
  // (`document.agent_run_active`) on the six manual write routes, which is the
  // enforcement; this is the honest UX in front of it, so a control the platform
  // is going to refuse never looks live.
  //
  // It is derived HERE and nowhere else, because this is the only place that can
  // see all three facts the decision needs: the thread's turn stream (the chat
  // controller), the document the editor has open, and the thread that document
  // was born in. The rule itself is pure (`../model/agent-run-lock`) — this
  // component only transports it, exactly as it does the refresh counters and
  // the auto-open decision.
  //
  // Computed BEFORE the editing sessions, off the shell's active tab and the
  // page's id map rather than off `session.activeDocumentId`: the scene session
  // consumes the lock, so taking the document id back out of it would be a cycle.
  const feedArtifacts = artifacts ?? NO_ARTIFACTS;
  const activeArtifact = shell.activeArtifactId
    ? (feedArtifacts.find(
        (artifact) => artifact.id === shell.activeArtifactId,
      ) ?? null)
    : null;
  const agentRunLock = agentRunLockForThread({
    activeThreadId: chat.activeThreadId,
    // The THREE-valued leg fact, not the boolean beside it: "no frame has
    // mentioned a leg" is not "this thread has no leg", and treating it as one
    // unlocked the editor on every cold load into a run (fix round 1, I1).
    designLeg: chat.designLeg,
    documentId: shell.activeArtifactId
      ? (documentIds?.[shell.activeArtifactId] ?? null)
      : null,
    // The gallery card's own origin thread — the SAME binding `artifact-auto-open`
    // trusts to decide that a born document belongs to this conversation. Null
    // (a tab whose card is not in this feed) is fail-safe LOCKED, by the rule.
    documentThreadId: activeArtifact?.originThreadId ?? null,
    state: chat.agentRunLock,
    threadBusy: chat.threadBusy,
  });
  // Editing: consumed on the AD lane only. The website lane has the same
  // exposure and no scene editor, so widening the EDITING lock to it is a
  // separate decision with its own surfaces — not something to acquire by
  // accident here.
  const sceneLocked = agentRunLock.locked && shell.artifactKind === "ad";
  // Publishing: founder ruling 2026-10-13 — a person's publish waits while the
  // design agent works on the page, and the Share menu says so. This widens the
  // lock to the website lane (web and site) for PUBLISHING ONLY; editing on the
  // website lane is unchanged. The server refuses mid-run either way (409
  // `document.agent_run_active` on both publish routes); this is the honest UX
  // in front of it.
  const publishLocked =
    agentRunLock.locked && isWebsiteKind(shell.artifactKind);

  // Chat-flow slice 3: the SAME editing session the artifact route mounts
  // (documents/selection/writes/rich-text/theme), keyed only on this mount's
  // own active tab and the page's id map — the hook never sees a shell
  // controller, so the two routes stay independent mounts of one machine.
  // AD2.7: one session per LANE, each gated on this mount's own active tab
  // kind. React forbids a conditional hook, so both are always called and the
  // kind rides in as `enabled` — the disabled one touches no transport
  // (audit finding F3: an ad tab used to run the web theme/document fetches
  // and swallow their 409s).
  //
  // Slice 2 (R-A2): the comment box's "Send to chat" must go through the SAME
  // submit path the composer's own send button does — but that closure is
  // rebuilt on every render (it reads the live composer text, the live
  // annotation list, the live canvas selection), while the canvas binding has
  // to stay identity-stable or the iframe's effects would re-run on every
  // keystroke. So the canvas gets this stable dispatcher and the latest
  // closure lives in a ref, assigned in an effect below.
  //
  // The lane gate is the SAME one the chips use minus the document (which is
  // not known until the session exists, and which the canvas implies anyway —
  // there is no comment box without a rendered document): outside an open
  // design leg a `design_node` ref means nothing, so rather than send a turn
  // that silently drops its annotations, the button is simply absent.
  const annotationLaneOpen = chat.designLegOpen && shell.artifactKind === "web";
  const sendAnnotationRef = useRef<((note: string) => void) | null>(null);
  const dispatchSendAnnotation = useCallback((note: string) => {
    sendAnnotationRef.current?.(note);
  }, []);
  const session = useWebEditingSession({
    activeArtifactId: shell.activeArtifactId,
    documentIds,
    enabled: shell.artifactKind === "web",
    onSendAnnotation: annotationLaneOpen ? dispatchSendAnnotation : undefined,
  });
  const sceneSession = useSceneEditingSession({
    activeArtifactId: shell.activeArtifactId,
    agentRunLocked: sceneLocked,
    documentIds,
    enabled: shell.artifactKind === "ad",
  });
  // Exactly one lane can be enabled, so this is the active document either
  // way — the stage's canvas branch picks the surface by kind.
  const activeDocumentId =
    session.activeDocumentId ?? sceneSession.activeDocumentId;
  /**
   * Task 9 (scene live-streaming rung B): the live reveal.
   *
   * While the agent-run lock holds over an open ad, the streamed operation
   * batches task 8 cleared for application are drawn into the canvas on an
   * animation clock — the design appears to draw itself in, instead of the
   * user watching a still picture for five minutes and then a jump cut.
   *
   * Display state ONLY. The pump's seam is `applyStreamedOperations`, the live
   * engine apply with no repaint and no mirror-up; it never persists, never
   * enqueues and never touches history. Nothing here is durable — the agent's
   * own checkpoints are, and rung A reloads the canvas from them.
   */
  const applyStreamedToEngine = useCallback(
    (operations: Operation[]) =>
      sceneSession.canvasControls.current?.applyStreamedOperations(
        operations,
      ) ?? null,
    [sceneSession.canvasControls],
  );
  // The canvas's own "could a batch land right now" (D9 read-only answers no),
  // asked LIVE: the engine arrives after the first paint, and a pump that can
  // apply nothing must never be mistaken for a healthy one.
  const engineAvailableForScene = useCallback(
    () => sceneSession.canvasControls.current?.canApply() ?? false,
    [sceneSession.canvasControls],
  );
  const engineIdentityForScene = useCallback(
    () => sceneSession.canvasControls.current?.streamEngineIdentity?.() ?? null,
    [sceneSession.canvasControls],
  );
  const sceneReveal = useSceneLiveReveal({
    actions: chat.sceneStream.actions,
    apply: applyStreamedToEngine,
    engineAvailable: engineAvailableForScene,
    engineIdentity: engineIdentityForScene,
    documentId: sceneSession.activeDocumentId,
    locked: sceneLocked,
  });
  /**
   * Task 9 (fix 1): publish the reveal's health to the controller.
   *
   * The controller decides the checkpoint reload but cannot see this canvas, so
   * the two facts that decision needs meet here — its cursor verdict, and this
   * probe. Publishing `null` on teardown is what makes the default rung A's
   * shipped behaviour: unknown health always reloads.
   */
  const publishSceneRevealHealth = chat.publishSceneRevealHealth;
  useEffect(() => {
    publishSceneRevealHealth(sceneReveal.isClean);
    return () => publishSceneRevealHealth(null);
  }, [publishSceneRevealHealth, sceneReveal.isClean]);
  /**
   * Task 10 (scene live-streaming rung B): THE LATE JOIN.
   *
   * A tab that opens — or reloads — onto a document whose run is already in
   * flight loads the last committed version, and the stream is somewhere past
   * it. The canvas reports the version it loaded; the controller's fold turns
   * that into the ledger position the run says that version holds, so the
   * cursor starts where this canvas actually stands instead of at zero, the
   * frames the backlog already carries beyond it land at once, and the ones
   * after that draw themselves in. Nothing is persisted anywhere to make this
   * work: the durable version and the stream's own replayed backlog are the
   * whole mechanism, which is why a reload is the same path as a first open.
   *
   * Gated on the LOCK, because the seed only means anything while a run is
   * streaming this document — outside one, task 8's position-0 cursor is
   * already right. Keyed on the load GENERATION as well as the version, so a
   * rung-A reload that lands the same version is still a fresh join: it
   * replaced the picture the pump was drawing.
   */
  const seedSceneStream = chat.seedSceneStream;
  const joinedDocument = sceneLocked ? sceneSession.loadedDocument : null;
  const joinedDocumentId = joinedDocument?.documentId ?? null;
  const joinedVersion = joinedDocument?.version ?? null;
  const joinedGeneration = joinedDocument?.loadGeneration ?? null;
  /**
   * WHICH RUN the canvas is joining (fix round 1) — the thread's running turn.
   *
   * That fact rather than the newest turn among the streamed frames, for two
   * reasons. It exists on a COLD LOAD, before a single frame has arrived, which
   * is the whole situation a late join is: the durable turn read already says
   * which turn is running, and the lock's own floor (`threadBusy`) is derived
   * from the same queue, so the seed and the lock can never disagree about
   * which run is in flight. And it stays current through the stream, because
   * the queue is computed over the turns with the streamed state overrides
   * applied. The newest turn among replayed design frames would have been
   * exactly the wrong answer for the defect this fixes — that newest frame can
   * be the PREVIOUS run's checkpoint.
   *
   * Read through a ref, and deliberately NOT a dependency: the seed is keyed on
   * the LOAD. A run that starts while the tab sits open must not re-seed, or the
   * new run's first batch would be caught up on instead of drawn in — the frames
   * themselves carry that transition (the cursor's per-turn reset), and the pump
   * re-seats on it.
   */
  const runningTurnId = chat.runningTurn?.turnId ?? null;
  // A running turn OR a discovery holding the thread keeps the composer running.
  const runControl = composerRunControl(chat);
  /**
   * The second source, and the reason there are two (fix round 3): the durable
   * queue reads "running" from the TURN LIST, and a replayed `turn.accepted`
   * marks that same turn "queued" for the renders before the `turn.started`
   * behind it lands — a window in which `runningTurn` is null while a run is
   * plainly in flight. The lock's own fold is not fooled by it: it holds the
   * turns the stream has seen ACCEPTED OR STARTED and not yet seen settle. One
   * such turn is an unambiguous answer; two are not, and are left to the
   * durable one.
   */
  const observedRunTurnIds = chat.agentRunLock.activeTurnIds;
  const joinTurnId =
    runningTurnId ??
    (observedRunTurnIds.size === 1
      ? ([...observedRunTurnIds][0] ?? null)
      : null);
  /**
   * One seed per LOAD, and never one that cannot name the run.
   *
   * A seed carries the run whose ledger the loaded version is a position in, so
   * seeding with no run at all is not a weaker seed — it is a wrong one, and it
   * used to undo a cursor the stream had already carried forward. So a load
   * that lands before anything names the run WAITS, and this effect re-runs
   * when one does (`joinTurnId` is a dependency). The ref is what keeps that
   * dependency from re-seeding a load that has already joined: a run starting
   * while the tab sits open must not fast-forward its first batch.
   */
  const seededLoadRef = useRef<string | null>(null);
  useEffect(() => {
    if (joinedDocumentId === null || joinedVersion === null) return;
    const load = `${joinedDocumentId}@${joinedGeneration}@${joinedVersion}`;
    if (seededLoadRef.current === load) return;
    if (joinTurnId === null) return;
    seededLoadRef.current = load;
    seedSceneStream(joinedDocumentId, joinedVersion, joinTurnId);
  }, [
    joinTurnId,
    joinedDocumentId,
    joinedGeneration,
    joinedVersion,
    seedSceneStream,
  ]);
  const designReferencesEnabled =
    chat.designLegOpen &&
    shell.artifactKind === "ad" &&
    sceneSession.activeDocumentId !== null;
  const referenceAttachments = useDesignReferenceAttachments({
    enabled: designReferencesEnabled,
  });
  // The ordinary chat attachments (`.md`/`.txt`/images the turn carries). They
  // are independent of the design leg: ruling 4 only decides which of the two
  // hooks a dropped IMAGE belongs to while an ad leg is open.
  const chatAttachments = useChatAttachments({
    enabled: workspace.composerCapabilities.attachments,
  });
  /**
   * The composer's ONE attachment intake — the `+` picker and (task 14) the
   * drop target both land here, so a file takes the same route whichever
   * gesture delivered it.
   */
  const handleAttachmentFiles = (files: File[]) => {
    const routed = routeAttachmentFiles(files, designReferencesEnabled);
    if (routed.design.length > 0) referenceAttachments.onFiles(routed.design);
    if (routed.chat.length > 0) chatAttachments.onFiles(routed.chat);
  };
  /** One chip list, two owners: whichever hook holds the id removes it. */
  const handleAttachmentRemove = (attachmentId: string) => {
    const design = referenceAttachments.attachments.some(
      (attachment) => attachment.id === attachmentId,
    );
    if (design) referenceAttachments.remove(attachmentId);
    else chatAttachments.remove(attachmentId);
  };
  // Dropping a file anywhere on the chat pane lands in the SAME intake the `+`
  // picker uses, so a dropped image still follows ruling 4's design/chat route.
  // The gate is the button's gate, verbatim: a surface that will accept a file
  // from the picker accepts the same file from a drop.
  const drop = useFileDrop({
    enabled:
      designReferencesEnabled || workspace.composerCapabilities.attachments,
    onFiles: handleAttachmentFiles,
  });
  // Same gate as the reference images above: a `design_node` ref only means
  // anything beside the open design leg's document, and the backend refuses a
  // submission carrying one otherwise — a canvas selection made outside an
  // open leg (a gallery-opened ad, a closed leg) must stay a canvas fact, not
  // become a context ref that walls off every message in the thread.
  const editTargetsEnabled =
    chat.designLegOpen &&
    shell.artifactKind === "ad" &&
    sceneSession.activeDocumentId !== null;
  const targetChips = editTargetsEnabled
    ? editTargetChips(sceneSession.scene, sceneSession.selectedIds)
    : [];
  // Slice 2 (R-A2), the web half of the same rule: an annotation is a noted
  // `design_node` ref, so it rides a turn only beside the open design leg's
  // own document.
  const webAnnotationsEnabled =
    annotationLaneOpen && session.activeDocumentId !== null;
  const annotationChipList = webAnnotationsEnabled
    ? annotationChips(session.annotations.state.items)
    : [];

  // The clarification card (spec 2026-09-20 §2.5): a design document that
  // stopped to ask before spending. Whether anything is open is derived from
  // the transcript by a pure function — the last settled assistant turn's
  // `clarification` parts — so answering (which appends a user message) closes
  // the card with no server round-trip, and a reload brings it back.
  const clarification = useMemo(
    () => openClarification(chat.transcript),
    [chat.transcript],
  );

  const activeThread =
    chat.threads.find((thread) => thread.id === chat.activeThreadId) ?? null;
  const chatTitle = activeThread ? chat.threadLabelFor(activeThread) : "Untitled";

  // The R6 dock decisions live in ../model/chat-dock as pure functions (the
  // repo's test runner has no DOM harness, so the rule is tested there and
  // consumed — never restated — here). One guard beyond the source view:
  // editorVisible additionally requires an actual artifact kind, so a
  // ?surface=web&edit=1 URL with no artifact yet collapses to the conversation
  // instead of an empty chat body. The source never hit this because it
  // fabricated default tabs — which we deliberately do not.
  const dockState = {
    artifactKind: shell.artifactKind,
    editing: shell.editing,
    panelOpen: shell.panelOpen,
    surface: shell.surface,
  };
  const editorVisible = chatDockOpen(dockState);
  const dockContent = chatDockContent(dockState);

  // W4.8a law, per mount: rich-text is enabled under the SAME condition that
  // mounts THIS route's editing dock (the .chatBody web-inspector branch) over
  // a real web document. Outside it the canvas cancels any session the bridge
  // starts, so a double-click on the read-only render changes nothing.
  const webEditingActive =
    dockContent === "web-inspector" && session.activeDocumentId !== null;

  // The artifact route's own fallback (editor-surface.tsx): a live canvas
  // selection names the schema to render; with nothing selected the inspector
  // falls back to this mount's shell state (the ?selection= pane param). The
  // two lanes are mutually exclusive (one `enabled` each), so at most one of
  // the first two terms is ever non-null.
  const inspectorSelection =
    session.webSelection.selection?.schema.selection ??
    sceneSession.selection?.selection ??
    shell.inspectorSelection;

  // Chat-flow slice 5: the pane state writes back to the URL, so every state
  // the user reaches (rail open, surface, Edit, inspector schema) is a
  // shareable deep link — the closing half of the R2 vocabulary. The
  // serializer is pure (../model/chat-surface-params); this effect only
  // transports its output.
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const documentTabs = useProjectDocumentTabs({
    projectId, active: shell.panelOpen && (shell.surface === "gallery" || shell.surface === "plan"),
    initialPath: paneState.surface === "plan" ? searchParams.get("document") || "project/plan.md" : undefined,
    writeRevision: chat.planWriteRevision, writtenDocumentId: chat.writtenProjectDocumentId,
    onOpen: shell.openPlan, onEmpty: shell.openGallery,
  });
  const selectedDocumentPath = documentTabs.selectedPath;
  const {
    edit: editParam,
    selection: selectionParam,
    surface: surfaceParam,
  } = chatSurfacePaneParams({
    artifactKind: shell.artifactKind,
    editing: shell.editing,
    // The SAME schema the inspector is rendering — a live canvas selection
    // names its schema, else the shell's own. That is exactly what ?selection=
    // hydrates; the canvas NODE id is deliberately never serialized (it is
    // document-local and would not survive a share, and the shared vocabulary
    // has no artifact identity at all — a deep link restores the pane state,
    // not the open tab).
    inspectorSelection,
    panelOpen: shell.panelOpen,
    rawSurface: paneState.surface,
    surface: shell.surface,
  });
  // Genweb slice 3 (B5), founder requirements 1 + 6: the gallery feed and any
  // open canvas refresh exactly when a durable design-leg frame for THIS thread
  // says the document moved. Never a timer, never a poll — the two counters are
  // bumped by the chat controller from the stream, and the rule that decides
  // which frame bumps which is the pure `designRefreshForEvent`.
  //
  // The feed is server-fetched by the chats page (`loadGalleryFeed`, a
  // server-only repository), so `router.refresh()` IS the client's re-fetch of
  // it: the page re-runs and hands down fresh `artifacts`/`documentIds` props
  // with no client state lost — which is also what lets the auto-open below
  // notice the born document by comparing props, rather than remounting.
  const { canvasRevision, feedRevision } = chat.designRefresh;
  useEffect(() => {
    if (feedRevision === 0) return;
    router.refresh();
  }, [feedRevision, router]);
  const reloadWebCanvas = session.onWriteReload;
  const reloadSceneCanvas = sceneSession.onWriteReload;
  useEffect(() => {
    if (canvasRevision === 0) return;
    // The SAME seam a committed inspector write uses — one reload mechanism,
    // whether the version was advanced by hand or by the design agent. Both
    // lanes are bumped: the stage takes the SUM as its reload token, and the
    // frame that fired names a document, not a kind.
    reloadWebCanvas();
    reloadSceneCanvas();
  }, [canvasRevision, reloadSceneCanvas, reloadWebCanvas]);

  // The header's rename is a document write, so it goes through the design API
  // and the tab takes the title the backend STORED. The rename advances the
  // document version, so both canvases reload and the server-fetched feed is
  // re-read — nothing is left holding the pre-rename document.
  const setArtifactTitleFor = shell.setArtifactTitleFor;
  const onArtifactRenamed = useCallback(
    (artifactId: string, persisted: string) => {
      setArtifactTitleFor(artifactId, persisted);
      reloadWebCanvas();
      reloadSceneCanvas();
      router.refresh();
    },
    [reloadSceneCanvas, reloadWebCanvas, router, setArtifactTitleFor],
  );
  const renameArtifact = useArtifactRename({
    documentIds,
    onRenamed: onArtifactRenamed,
  });

  // Open a named design tab on each new/updated file from this chat. Baseline the
  // server-fetched feed at mount so replayed history cannot open old files.
  const knownArtifactIds = useRef<Set<string> | null>(null);
  const knownArtifactUpdates = useRef(new Map<string, string | undefined>());
  const openArtifact = shell.openArtifact;
  const activateArtifact = shell.activateArtifact;
  const openArtifacts = shell.openArtifacts;
  useEffect(() => {
    const known = knownArtifactIds.current;
    if (known === null) {
      // The mount snapshot. Taken on the first commit rather than during
      // render (no render-phase side effects), which is the same set: the
      // chats page awaits `loadGalleryFeed` server-side, so the first client
      // render already holds the complete feed.
      knownArtifactUpdates.current = new Map(feedArtifacts.map((artifact) => [artifact.id, artifact.updatedAt]));
      knownArtifactIds.current = new Set(
        feedArtifacts.map((artifact) => artifact.id),
      );
      return;
    }
    const opening = artifactsToAutoOpen({
      activeThreadId: chat.activeThreadId,
      artifacts: feedArtifacts,
      knownArtifactIds: known,
      knownUpdates: knownArtifactUpdates.current,
      // A tab change re-runs this effect too, harmlessly: by then every id
      // of the current feed is banked below, so nothing is left to open.
      openArtifactIds: new Set(openArtifacts.map((artifact) => artifact.id)),
    });
    // Bank everything this delivery carried — including the one being opened —
    // before acting on the decision. That is what makes a document open at
    // most once per update: a closed tab stays closed until another write, and a feed
    // refresh (the URL write-back below re-renders the page too) is inert.
    for (const artifact of feedArtifacts) { known.add(artifact.id); knownArtifactUpdates.current.set(artifact.id, artifact.updatedAt); }
    if (opening.length === 0) return;
    // One message can birth many documents on one leg, so EVERY new document
    // gets its own tab. The strip fills oldest-born first and the first one
    // born is the tab left in front — the user watches the leg from its start
    // rather than landing on whichever document happened to finish last.
    for (const artifact of opening) openArtifact(artifact);
    activateArtifact(opening[0].id);
  }, [activateArtifact, chat.activeThreadId, feedArtifacts, openArtifact, openArtifacts]);

  // The composer's Files and Microsites come from the same feeds the Gallery draws. The
  // document list is fetched here unconditionally (the tabs hook fetches only while a
  // panel is open) and re-read when this thread writes a document.
  const composerDocuments = useProjectDocuments(projectId, {
    active: true,
    refreshToken: chat.planWriteRevision,
  });
  const composerCatalog = useMemo(
    () =>
      buildComposerCatalog({
        documents: composerDocuments.documents,
        artifacts: feedArtifacts,
        entities: workspace.entities,
      }),
    [composerDocuments.documents, feedArtifacts, workspace.entities],
  );
  const { setCatalogEntities } = controller;
  useEffect(() => {
    setCatalogEntities(composerCatalog);
  }, [composerCatalog, setCatalogEntities]);

  // `?open=` (2026-09-15): land with one artifact tab open. Read once (the ref), resolved against
  // the server-fetched feed, and stripped by the write-back below.
  const openParamHandled = useRef(false);
  useEffect(() => {
    if (openParamHandled.current) return;
    openParamHandled.current = true;
    const opening = openArtifactFromParam({ openId: searchParams.get("open"), artifacts: feedArtifacts });
    if (opening) openArtifact(opening);
  }, [feedArtifacts, openArtifact, searchParams]);

  // The controller distinguishes live writes from late history replay using server cursors.
  // Founder ruling 2026-09-12: when the agent launches discovery, the rail opens the Target
  // accounts surface by itself. The rule is `../model/discovery-launch-signal`; this effect only
  // transports it, banking every tool call id it has seen so a replayed backlog opens nothing.
  const knownLaunchIds = useRef<Set<string> | null>(null);
  const openTargetAccounts = shell.openTargetAccounts;
  useEffect(() => {
    const known = knownLaunchIds.current;
    if (known === null) {
      // The mount snapshot WAITS for the conversation. Unlike the gallery feed above, the
      // transcript is not server-rendered: `useProjectChatController` starts at `messages = []`
      // with `loading = true` and fetches the conversation in a client effect. Snapshotting on
      // the first commit would bank an EMPTY set, so the durable backlog's own persisted
      // `launch_arv2_discovery` part (persisted parts carry their finished `output-available`
      // state) would read as new and hijack the rail on every visit to a thread that ever
      // launched discovery. Residual, accepted: a launch part that arrives later still — an
      // older page prepended by `loadOlderMessages` — opens the surface once.
      if (chat.loading) return;
      knownLaunchIds.current = new Set(completedToolCallIds(chat.transcript));
      return;
    }
    const opening = discoveryLaunchToOpen({ transcript: chat.transcript, knownToolCallIds: known });
    // Bank only COMPLETED parts. A tool part is delivered first as `input-streaming` /
    // `input-available` and flips to `output-available` when it lands; banking it on first sight
    // would make its completion read as already known, and the launch would never open the tab
    // (live walk, 2026-09-12).
    for (const id of completedToolCallIds(chat.transcript)) known.add(id);
    if (opening === null) return;
    openTargetAccounts();
    setDiscoveryPrime((current) => current + 1);
  }, [chat.loading, chat.transcript, openTargetAccounts]);

  useEffect(() => {
    // Compose over the LIVE query so params we do not own (?handoff=, anything
    // future) survive; only the pane keys are ours to rewrite.
    const query = new URLSearchParams(searchParams.toString());
    query.delete("surface");
    query.delete("edit");
    query.delete("selection");
    query.delete("document");
    // `?open=` is read once at mount and never written back: stripping it here canonicalizes the
    // URL to the ordinary `surface=web|ad` state the opened tab produces.
    query.delete("open");
    if (surfaceParam === "plan" && selectedDocumentPath) query.set("document", selectedDocumentPath);
    if (surfaceParam) query.set("surface", surfaceParam);
    if (editParam) query.set("edit", editParam);
    if (selectionParam) query.set("selection", selectionParam);
    const next = query.toString();
    // Loop guard: replace only on a real difference. This is also what makes
    // the write-back converge WITH the workspace controller's handoff cleanup
    // (same pathname, preserved params) instead of fighting it.
    if (next === searchParams.toString()) return;
    // replace, never push: pane toggles must not grow browser history.
    router.replace(`${pathname}${next ? `?${next}` : ""}`, { scroll: false });
  }, [editParam, pathname, router, searchParams, selectionParam, surfaceParam, selectedDocumentPath]);

  /**
   * The composer's ONE submit path — the composer's own send button and the
   * canvas comment box's "Send to chat" both land here, so a turn carries the
   * same context refs whichever gesture sent it.
   *
   * `justAdded` is the annotation "Send to chat" stored a moment ago: its
   * reducer dispatch has not rendered yet, so the annotation state visible in
   * this closure cannot see it, and the note the user is looking at would
   * otherwise miss the very turn it triggered.
   */
  const submitTurn = async (
    prompt: string,
    entityIds?: string[],
    justAdded?: WebAnnotation,
  ): Promise<boolean> => {
    // Snapshot references synchronously before any await. A queued turn owns these
    // exact asset ids even if uploads or selection change before the POST returns.
    const referenceSnapshot = designReferencesEnabled
      ? referenceAttachments.snapshotContextRefs()
      : [];
    if (
      referenceAttachments.attachments.length > 0 &&
      referenceSnapshot === null
    ) {
      return false;
    }
    // The chat attachments, snapshotted for the same reason and refused for the
    // same one: a turn carries the files that were ready when it was sent, and
    // an upload still in flight is not one of them.
    const attachmentSnapshot = chatAttachments.snapshot();
    if (chatAttachments.attachments.length > 0 && attachmentSnapshot === null) {
      return false;
    }
    // Snapshot ids before the first await inside the scene session.
    // A queued turn keeps this set even if the user changes the
    // canvas selection while optimistic writes finish or the POST runs.
    const editTargetSnapshot = editTargetsEnabled
      ? await sceneSession.snapshotEditTargets()
      : null;
    if (targetChips.length > 0 && editTargetSnapshot === null) {
      return false;
    }
    // Slice 2 (R-A2): the annotations, snapshotted for the same reason — the
    // turn owns the notes that were on screen when it was sent.
    const annotationItems = webAnnotationsEnabled
      ? [...session.annotations.state.items, ...(justAdded ? [justAdded] : [])]
      : [];
    const annotationSnapshot =
      webAnnotationsEnabled && session.activeDocumentId && annotationItems.length
        ? {
            documentId: session.activeDocumentId,
            documentVersion:
              session.webSelection.document?.currentVersion ?? null,
            items: annotationItems,
          }
        : null;
    const entityContextRefs = (entityIds ?? controller.selectedEntityIds)
      .map((id) =>
        controller.composerEntities.find((entity) => entity.id === id),
      )
      .filter((entity) => entity !== undefined)
      .map((entity) => ({
        objectId: entity.id,
        objectType: entity.type,
        version: entity.version ?? null,
      }));
    const contextRefs = [
      ...entityContextRefs,
      ...editTargetContextRefs(editTargetSnapshot),
      ...annotationContextRefs(annotationSnapshot),
      ...(referenceSnapshot ?? []),
    ];
    // The annotations can BE the message: a marketer who wrote three notes and
    // pressed send said everything in them, and the refs carry the words.
    const message =
      prompt.trim().length === 0 && annotationSnapshot !== null
        ? ANNOTATIONS_ONLY_MESSAGE
        : prompt;
    const accepted = await chat.submitMessage(message, {
      attachmentRefs: attachmentSnapshot ?? [],
      contextRefs,
      agentProfileId: workspace.composerCapabilities.agentProfileSelection
        ? (controller.selectedModel?.id ?? null)
        : null,
    });
    // R6 dismiss-on-send: a message the agent ACCEPTED closes the
    // editing dock and restores the conversation the user is now
    // talking in. A refused (`failed`) or empty/threadless
    // (`not_submitted`) submit leaves them mid-edit. The rule is
    // evaluated over the whole status union — before the early
    // return — so the pure decision in ../model/chat-dock is the
    // one that actually runs.
    if (chatDockDismissedBySubmission(accepted.status)) {
      shell.setEditing(false);
    }
    if (accepted.status !== "accepted") return false;
    referenceAttachments.clear();
    chatAttachments.clear();
    // R-A3: the annotations are now the turn's, so the chips and the badges in
    // the canvas go together. Only on an ACCEPTED submit — a refused one leaves
    // the marketer their notes.
    session.annotations.clear();
    controller.completeSubmissionContext(
      entityContextRefs.map((reference) => reference.objectId),
    );
    return true;
  };

  // The latest submit closure, for the stable dispatcher the canvas holds.
  // `add` returns the stored record (null only for a blank note, which the
  // popover's Send button already refuses), and the composer's own text rides
  // along — "Send to chat" is a send, not a second, separate channel.
  const sendAnnotation = (note: string) => {
    const stored = session.annotations.add(note);
    if (stored === null) return;
    void submitTurn(controller.prompt, controller.selectedEntityIds, stored).then(
      (accepted) => {
        if (accepted) controller.setPrompt("");
      },
    );
  };
  useEffect(() => {
    sendAnnotationRef.current = sendAnnotation;
  });

  return (
    <main
      className={`${styles.shell} ${shell.panelOpen ? styles.shellPanelOpen : ""} ${shell.artifactMaximized ? styles.shellArtifactMaximized : ""}`}
      data-artifact-id={shell.activeArtifactId ?? undefined}
      data-artifact-kind={shell.artifactKind ?? "none"}
      data-editing={editorVisible}
      data-project-id={projectId}
      data-selected-node={
        session.webSelection.selection?.node.id ??
        sceneSession.primaryNodeId ??
        undefined
      }
      data-selected-schema={
        session.webSelection.selection
          ? `${session.webSelection.selection.schema.selection}${session.webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : dockContent === "ad-inspector" && sceneSession.selection
            ? `${sceneSession.selection.selection}${sceneSession.selection.suppressAutoLayoutSection ? ":no-auto-layout" : ""}`
            : undefined
      }
    >
      <section className={styles.chatPane} {...drop.handlers}>
        <ChatShellHeader
          chatId={chat.activeThreadId ?? undefined}
          onArchive={() => {
            if (chat.activeThreadId) void chat.archiveThread(chat.activeThreadId);
          }}
          onRename={(title) => {
            if (chat.activeThreadId) void chat.renameThread(chat.activeThreadId, title);
          }}
          onToggleArtifactPanel={shell.toggleArtifactPanel}
          panelOpen={shell.panelOpen}
          projectId={projectId}
          title={chatTitle}
        />
        <div className={styles.chatBody}>
          {dockContent === "web-inspector" ? (
            <div className={styles.inspectorDock}>
              <WebInspector
                // Keyed on the SELECTED NODE only — never the document version.
                // A per-write version key remounted the whole inspector on
                // every edit (the founder-observed defect); the controller's
                // own state already reflects the user's edit, so re-hydration
                // belongs to selection changes alone.
                // The canvas key carries the theme's page surface, so the one time the
                // theme lands after mount the canvas inspector re-seeds from it
                // (the web lane hydrates at mount, not live).
                key={session.webSelection.selection?.node.id ?? `canvas:${session.canvasHydrated?.backgroundColor ?? ""}`}
                customComponentForm={session.customComponentForm}
                error={session.inspectorError}
                note={session.writes.note}
                addressing={session.addressing}
                // R-A6 (slice 3): the human's own text edits inside the selected
                // cloned band, each with its Clear (the session decides whether
                // the selection owns a list at all).
                cloneTextEdits={session.cloneTextEdits}
                hydrated={session.webSelection.selection?.hydrated ?? session.canvasHydrated}
                layers={session.layerRows}
                // W5.1 (§5): the mapper's fallback flag — embeds (item 32) and
                // the interactive components (item 33) land on the container
                // view and get Layout(-padding) only.
                layoutOnly={session.webSelection.selection?.schema.layoutOnly}
                onReplaceImage={session.onReplaceImage}
                onSelectLayer={session.onSelectLayer}
                onSelectionChange={shell.selectInspectorElement}
                // F5 task 19 (FLAGGED): the page/route controls, present only while
                // no node is selected (the session decides).
                pageSection={session.pageSection}
                richTextRange={session.richTextRange}
                selection={inspectorSelection}
                themeColors={session.themeColors}
              />
            </div>
          ) : null}
          {dockContent === "ad-inspector" ? (
            <div className={styles.inspectorDock}>
              <ImageInspector
                // Keyed on the SELECTED NODE only, exactly as the web branch
                // above. Values need no remount to resynchronize — every bound
                // field derives from live hydrated state (AD4.R); remounting
                // resets UI facts (open sections, drafts), which is right
                // exactly when the selection changes.
                key={sceneSession.primaryNodeId ?? "canvas"}
                addressing={sceneSession.addressing}
                arrange={sceneSession.arrange}
                assetLibrary={sceneSession.assetLibrary}
                error={sceneSession.inspectorError}
                fontOptions={sceneSession.fontOptions}
                hydrated={sceneSession.hydrated}
                imageAi={sceneSession.imageAi}
                // AD4.R-10 / GATE G-H (founder-ruled 2026-08-22): while an
                // agent turn is in flight on THIS thread, the human may not
                // operate the inspector — "we cannot let humans change any
                // value when the agents are at work with designing".
                //
                // TASK 4 (scene live-streaming rung A) narrows the source from
                // the bare `chat.threadBusy` to the agent-run lock above, which
                // is the SAME fact with the ruling's own two qualifications
                // finally applied: "with designing" (a design leg is open) and
                // on THIS document (its card was born in this thread). A
                // strategy turn in a thread whose design leg has closed no
                // longer freezes an unrelated ad — which is the ratified genweb
                // behaviour of interleaved edits BETWEEN design turns, not a
                // relaxation of the gate. `threadBusy` still floors it (see the
                // derivation), so a cold load into a live run is still locked.
                //
                // Nothing is written back: this is a READ of the chat
                // controller, so no chat-side behaviour — composer, sending,
                // gates, queueing, mid-turn steering — can move because of this
                // line, in either direction (the founder's chat-status-quo
                // addendum).
                inspectorDisabled={sceneLocked}
                layers={sceneSession.layerRows}
                note={sceneSession.note}
                onReplaceImage={sceneSession.onReplaceImage}
                onSelectLayer={sceneSession.onSelectLayer}
                onSelectionChange={shell.selectInspectorElement}
                onToggleLayer={sceneSession.onToggleLayer}
                pageless={sceneSession.pageless}
                palette={sceneSession.palette}
                selectedIds={sceneSession.selectedIds}
                selection={inspectorSelection}
                suppressAutoLayoutSection={
                  sceneSession.selection?.suppressAutoLayoutSection
                }
              />
            </div>
          ) : null}
          {dockContent === "conversation" ? (
            <div
              aria-label="Conversation"
              className={`${styles.conversationStage} flex min-h-0 flex-col`}
            >
              <ConversationContent
                chat={chat}
                contextEntities={controller.composerEntities}
                contextHandoffError={controller.contextHandoffError}
                onOpenPlan={(id) => void documentTabs.openById(id)}
              />
            </div>
          ) : null}
        </div>
        <div
          className={`${styles.composerDock} ${
            targetChips.length || annotationChipList.length
              ? styles.composerDockWithTargets
              : ""
          } ${research.card || chat.queueControl.paused ? styles.composerDockWithResearchCard : ""}`}
        >
          <div className={styles.composerFrame}>
            {research.card ? (
              <ResearchProgressCard
                card={research.card}
                headline={research.headline}
                line={research.line}
              />
            ) : null}
            {/* Slice 2 (R-A2): the annotations, in badge order, above the
                composer — the same bar the ad lane's edit targets use, so a
                chip means the same thing in both lanes: "this turn is about
                these". Removing one drops the badge in the canvas with it. */}
            {annotationChipList.length ? (
              <div aria-label="Annotations" className={styles.editTargetBar}>
                <span className={styles.editTargetLabel}>Annotations</span>
                <div className={styles.editTargetList}>
                  {annotationChipList.map((chip) => (
                    <span className={styles.editTargetChip} key={chip.n}>
                      <span className={styles.editTargetName}>
                        {chip.n} {chip.label}
                      </span>
                      <button
                        aria-label={`Remove annotation ${chip.n}`}
                        className={styles.editTargetRemove}
                        onClick={() => session.annotations.remove(chip.n)}
                        type="button"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {targetChips.length ? (
              <div aria-label="Edit targets" className={styles.editTargetBar}>
                <span className={styles.editTargetLabel}>Editing</span>
                <div className={styles.editTargetList}>
                  {targetChips.map((target) => (
                    <span className={styles.editTargetChip} key={target.nodeId}>
                      <span className={styles.editTargetName}>{target.label}</span>
                      <button
                        aria-label={`Remove ${target.label} edit target`}
                        className={styles.editTargetRemove}
                        onClick={() =>
                          sceneSession.onSelectLayer(target.nodeId, true)
                        }
                        type="button"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {chat.queueControl.paused && chat.queuedTurns.length > 0 ? (
              <div className={styles.queueControls}>
                <span>{chat.queuedTurns.length} {chat.queuedTurns.length === 1 ? "message" : "messages"} queued</span>
                <button type="button" disabled={chat.stopPending || chat.resumingQueue}
                  onClick={() => void chat.resumeQueuedTurns()}>Resume</button>
              </div>
            ) : null}
            {clarification !== null && chat.runningTurn === null ? (
              <ClarificationCard
                key={clarification.turnId}
                onSubmit={(text, contextRefs) => {
                  void chat.submitMessage(text, { contextRefs });
                }}
                parts={clarification.parts}
              />
            ) : null}
            <ProjectComposer
              running={runControl.running}
              stopping={chat.stopPending}
              onStop={runControl.onStop}
              attachmentAccept={
                designReferencesEnabled
                  ? `${DESIGN_REFERENCE_ACCEPT},${CHAT_ATTACHMENT_ACCEPT}`
                  : CHAT_ATTACHMENT_ACCEPT
              }
              attachmentError={
                (designReferencesEnabled ? referenceAttachments.error : null) ??
                chatAttachments.error
              }
              attachmentInputDisabled={
                designReferencesEnabled &&
                referenceAttachments.attachments.length >=
                  MAX_DESIGN_REFERENCE_ATTACHMENTS
              }
              attachmentLabel="Attach files"
              attachments={[
                ...(designReferencesEnabled
                  ? referenceAttachments.attachments
                  : []),
                ...chatAttachments.attachments,
              ]}
              // Never disabled while work is detached: the user keeps the wheel.
              disabled={chat.access !== null || chat.route !== null}
              dropActive={drop.active}
              entities={controller.composerEntities}
              modelPickerOpen={controller.modelPickerOpen}
              models={workspace.models}
              onAttachmentFiles={
                designReferencesEnabled ||
                workspace.composerCapabilities.attachments
                  ? handleAttachmentFiles
                  : undefined
              }
              onAttachmentRemove={
                designReferencesEnabled ||
                workspace.composerCapabilities.attachments
                  ? handleAttachmentRemove
                  : undefined
              }
              onEntityRemove={
                workspace.composerCapabilities.contextRefs
                  ? controller.removeEntity
                  : undefined
              }
              onEntitySelect={
                workspace.composerCapabilities.contextRefs
                  ? controller.selectEntity
                  : undefined
              }
              onModelPickerToggle={controller.toggleModelPicker}
              onModelSelect={controller.selectModel}
              onPromptChange={controller.setPrompt}
              onSubmit={(prompt, entityIds) => submitTurn(prompt, entityIds)}
              prompt={controller.prompt}
              sendDisabled={
                (designReferencesEnabled &&
                  referenceAttachments.submissionBlocked) ||
                chatAttachments.submissionBlocked
              }
              // Slice 2 (R-A2): chips on the bar are already a message — the
              // notes ride the refs — so Send works on an empty box and the
              // turn reads "See annotations."
              submittableWithoutPrompt={annotationChipList.length > 0}
              selectedEntities={controller.selectedEntities}
              selectedEntityIds={controller.selectedEntityIds}
              selectedModel={controller.selectedModel}
            />
          </div>
        </div>
      </section>
      <ArtifactStage
        annotations={session.canvasAnnotations}
        activeArtifactId={shell.activeArtifactId}
        activeDocumentId={activeDocumentId}
        // F5 task 18: the header's page switcher and the canvas read ONE
        // value — the web editing session's active page.
        activePageId={session.activePageId}
        onPageChange={session.setActivePageId}
        pages={session.pages}
        artifacts={feedArtifacts}
        artifactKind={shell.artifactKind}
        artifactMaximized={shell.artifactMaximized}
        artifactTitle={shell.artifactTitle}
        canvasControlsRef={session.canvasControls}
        canvasReloadToken={session.reloadNonce + sceneSession.reloadNonce}
        exportPreview={sceneSession.exportPreview}
        exportStatus={sceneSession.exportStatus}
        // The website pane's "agent is generating" motion (cofounder handoff
        // ad4f30bb). Both halves are the controller's own already-public facts:
        // a turn in flight on THIS thread, beside an OPEN design leg — the leg
        // is what makes the turn about the artifact in the pane, so a plain
        // research turn never blurs someone's page. A READ of the chat
        // controller and nothing more: no chat-side behaviour moves because of
        // it. The canvas decides when the blur LIFTS (its hold rule waits out
        // the refresh the turn wrote), so this is only the arming signal.
        generating={chat.threadBusy && chat.designLegOpen}
        onRequestExportPreview={sceneSession.requestExportPreview}
        onSceneChange={sceneSession.onSceneChange}
        // Clipboard Task 8: a picture dragged onto the canvas is uploaded and
        // inserted where it was dropped, through the session's own write path.
        onSceneDropImageFiles={sceneSession.onSceneDropImageFiles}
        onSceneFitZoom={sceneSession.onFitZoom}
        onSceneGestureZoom={sceneSession.onGestureZoom}
        onSceneHistoryChange={sceneSession.onHistoryChange}
        // AD4.C / Ruling C-3: a committed canvas gesture rides the SAME write
        // path the inspector's rows do — the session's `applyOps` (optimistic
        // engine apply → repaint → edit-queue persist), so a drag is one
        // atomic batch, one undo frame, and ⌘Z needs nothing new.
        onSceneAppliedOperations={sceneSession.writes.persistAppliedOps}
        onSceneOperations={sceneSession.writes.applyOps}
        onSceneSelect={sceneSession.onSelectCanvas}
        onSceneZoomChange={sceneSession.onZoomChange}
        sceneCanvasControlsRef={sceneSession.canvasControls}
        // Task 9: what the ad canvas draws while the reveal pump is streaming.
        // Null the rest of the time, and the canvas renders the document.
        sceneDisplayScene={sceneReveal.displayScene}
        // AD4.C / Ruling C-4 — GATE G-H, the canvas half of the same ruling
        // `inspectorDisabled` above implements, off the same fact: while the
        // design agent is at work on this document the human may not change
        // values, so drag and resize are off, the handles go with them, and no
        // caret opens. Task 4 adds the words: a press or double-click that WOULD
        // have edited reports back, and the note says why.
        //
        // View, zoom, pan and selection stay live throughout — looking is not
        // changing, which is the whole of what the ruling forbids.
        sceneGestureDisabled={sceneLocked}
        onSceneLockedEdit={sceneSession.onLockedEdit}
        publishLocked={publishLocked}
        // Rung C / §1.6: one document, one brand palette — the caret
        // session's colour control offers exactly what the inspector's do.
        scenePalette={sceneSession.palette}
        sceneSelectedNodeId={sceneSession.primaryNodeId}
        sceneZoomLabel={sceneSession.zoom}
        sceneZoomOverride={sceneSession.zoomOverride}
        editing={shell.editing}
        onActivateArtifact={shell.activateArtifact}
        onCanvasSelect={session.webSelection.onSelect}
        onCloseArtifact={shell.closeArtifact}
        onOpenGallery={shell.openGallery}
        onCloneTextCommit={session.onCloneTextCommit}
        onOpenTargetAccounts={shell.openTargetAccounts}
        documentTabs={documentTabs}
        canEditDocuments={canEditDocuments}
        panelOpen={shell.panelOpen}
        targetAccountsBusy={discovery.live}
        targetAccountsRefreshToken={discovery.tick + research.tick}
        onAddAccountsToChat={
          addToOpenChat.available && workspace.composerCapabilities.contextRefs
            ? addToOpenChat.add
            : undefined
        }
        onRichTextCommit={session.onRichTextCommit}
        onRichTextSessionChange={session.onRichTextSessionChange}
        richTextBusy={session.writes.busy}
        richTextEnabled={webEditingActive}
        richTextTheme={session.theme}
        onOpenGalleryArtifact={(artifact) => {
          // The card's own document type decides where it lands (the pure
          // ../model/gallery-card-target): an account-list card opens the
          // target-accounts surface; everything else opens an artifact tab.
          const target = galleryCardTarget({
            id: artifact.id,
            title: artifact.title,
            type: artifact.source?.type,
            documentKind: artifact.source?.documentKind,
            document: artifact.document,
          });
          if (target.surface === "plan") {
            documentTabs.openPath(target.documentPath);
            return;
          }
          if (target.surface === "target-accounts") {
            shell.openTargetAccounts();
            return;
          }
          shell.openArtifact(target.artifact);
        }}
        onRenameArtifact={(title) => {
          if (shell.activeArtifactId) {
            renameArtifact(shell.activeArtifactId, title);
          }
        }}
        // The tab strip's rename of a NON-active tab is unchanged local state
        // (it carries no document handle of its own here).
        onRenameArtifactFor={shell.setArtifactTitleFor}
        onToggleMaximized={shell.toggleArtifactMaximized}
        onTogglePanel={shell.toggleArtifactPanel}
        onToggleEditing={() => shell.setEditing(!shell.editing)}
        // Task 4: the Edit affordance itself. Entering edit mode is refused
        // while the lock holds — an editor whose every control is inert is not
        // an editor — but LEAVING it never is, or a lock engaging mid-edit would
        // trap the user in a dock they cannot close.
        editDisabled={sceneLocked && !shell.editing}
        // 2026-09-04 port: the motion follows the CANVAS lock (`sceneLocked`),
        // not the Edit pill's `editDisabled`, so it also runs when the lock
        // engages mid-edit (leaving edit mode is never refused, so
        // `editDisabled` is false there).
        agentWorking={sceneLocked}
        editDisabledReason={agentRunLock.note}
        openArtifacts={shell.openArtifacts}
        // Replace-image Task 6: the asset-library picker floats over the stage,
        // rendered by the surface (the stage is pass-through chrome). The Task-4
        // binding derives `isOpen` from the armed document, so switching
        // artifacts closes it by construction.
        overlay={
          sceneSession.assetLibrary?.isOpen ? (
            <AssetLibraryPanel
              library={sceneSession.assetLibrary}
              onUploadFile={sceneSession.onReplaceImage}
            />
          ) : null
        }
        projectTitle={workspace.title}
        projectId={projectId}
        // AD3.3: the header carries ONE pair of history-row disables, and the
        // artifact on screen decides which lane's stacks they describe — the
        // same kind switch that gates the two sessions above. Without it an ad
        // would read the (always-empty) web session's depths and its rows could
        // never be offered.
        redoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : session.redoDisabled
        }
        selectedCanvasNodeId={session.webSelection.selection?.node.id ?? null}
        surface={shell.surface}
        undoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : session.undoDisabled
        }
      />
    </main>
  );
}
