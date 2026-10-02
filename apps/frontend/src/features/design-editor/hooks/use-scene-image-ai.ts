"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  REMOVE_BACKGROUND_INSTRUCTION,
  sceneGeneratedAssetLabel,
  sceneGenerationResolution,
  sceneImageBeforeSrc,
  sceneImageCandidateView,
  sceneImageEditSource,
  sceneImageStatusLine,
  type SceneImageAiBinding,
} from "../adapter/scene-image-ai";
import {
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "../adapter/scene-apply";
import { designBffConfig } from "../data/design-bff";
import {
  editAsset,
  generateAsset,
  type EditAssetRequest,
  type GenerateAssetRequest,
} from "../engine/scene/assetLibrary";
import type { AssetRecord, Node, Operation, Scene } from "../engine/scene/contracts";
import type { SceneWriteGate } from "./use-scene-manual-edits";

/**
 * AD4.A step 3 (§1.3 row 2): the ad lane's image AI suite — generate from a
 * prompt, edit with an instruction, remove the background, and review the
 * candidate an edit produces. The orchestration only; every DECISION is the
 * adapter's (`scene-image-ai.ts` for the request shaping and the gates,
 * `scene-apply.ts::sceneImagePlacementOperations` for the document change) and
 * every transport is the engine's own client (`assetLibrary.ts`).
 *
 * THE SHAPE IS `use-scene-replace-image.ts`'s, deliberately. Both flows mint an
 * asset and then place it, so both must answer the same three questions the
 * same way: refuse before you spend, re-read the selection after the await, and
 * put failure in the inspector's ONE existing error slot. The differences are
 * stated where they occur.
 *
 * THE TWO FLOWS ARE NOT SYMMETRIC, and that is upstream's design, not an
 * accident: **generate swaps into the node immediately** while **edit stages a
 * candidate and touches nothing** until the user accepts. A regenerate is the
 * user asking for a new picture and getting one; an edit is a proposal about
 * the picture they already have, and the Before/After review is the point.
 *
 * WHY THE STATE LIVES HERE RATHER THAN IN THE PANEL. The inspector is remounted
 * per selection (`key={nodeId}`), so a candidate held in the component would be
 * thrown away by a selection change landing mid-review — a paid model call
 * silently discarded, which is the fourth discipline exactly. A result someone paid for
 * must outlive the panel showing it. Held here it does; it is STAMPED with the
 * document and node it was made from, so a selection change hides it instead
 * (and `accept` refuses outright), which is the rule that matters most in this
 * slice: a candidate must never be accepted onto a different node than the one
 * it was made from.
 *
 * AD4.R-8: reload-remounts are gone. The panel used to remount whenever a
 * reloaded document arrived too, so a CAS conflict landing mid-review was the
 * sharp edge this hook was written against; now every bound field derives from
 * live hydrated state and a reload remounts nothing. The reasoning above is
 * unchanged and the hazard is strictly smaller — a mid-review reload no longer
 * disturbs the candidate at all.
 *
 * REFUSALS RESOLVE, they do not reject — the one deliberate divergence from the
 * upload hook, whose rejection is what puts `InspectorImageUpload`'s local
 * preview back. Nothing here has a local display to revert, every reachable
 * refusal already has its button disabled, and a rejecting `void promise` in an
 * onClick is an unhandled rejection. Failures the user should read about still
 * reach the error slot; §4's refusals stay silent, as they are everywhere else
 * on this lane.
 */

/** The candidate an edit produced, stamped with what it was made FROM. Both
 * halves of the stamp are load-bearing: node ids are per-document and the seed
 * script reuses names, so a document id alone would not tell two ads apart. */
export interface SceneImageCandidate {
  forDocumentId: string;
  forNodeId: string;
  record: AssetRecord;
}

/** What a Save-as-new confirmed — STAMPED exactly like the candidate it
 * describes. A notice is a statement about one picture on one node, so it must
 * be derived against the current selection rather than returned unconditionally:
 * unstamped, "Saved … to the asset library." followed the user onto the next
 * image and described something that had never happened there. */
export interface SceneImageSavedNotice {
  forDocumentId: string;
  forNodeId: string;
  message: string;
}

export interface SceneImageAiState {
  candidate: SceneImageCandidate | null;
  editing: boolean;
  generating: boolean;
  savedNotice: SceneImageSavedNotice | null;
}

export interface SceneImageAiDeps {
  /** The manual-edits controller's one write path (optimistic apply → CAS
   * queue). `false` means the batch did not land. */
  applyOps: (operations: Operation[], intent?: string) => boolean;
  /** May a write land — armed, engine live, and (task 4) not locked behind a
   * running design turn? Asked BEFORE every spend, because a refusal after one
   * strands a minted asset. The whole gate rather than a boolean, so the ONE
   * refusal that has words can use them (fix round 1, I3). */
  writeGate: () => SceneWriteGate;
  /** Clears both inline slots. A new attempt supersedes what the last said. */
  clearMessages: () => void;
  /** The document a candidate would belong to. */
  documentId: string | null;
  edit: (request: EditAssetRequest) => Promise<AssetRecord>;
  generate: (request: GenerateAssetRequest) => Promise<AssetRecord>;
  /** The session's PRIMARY selection, resolved against the live scene. */
  node: Node | null;
  /** Sets the inspector's existing inline error line. */
  onError: (message: string) => void;
  /** Task 4 (I3): sets the inspector's existing inline NOTE line — where a
   * refusal that is a STATE (the agent-run lock) belongs. No new UI. */
  onNote: (message: string) => void;
  /** Hands the new snapshot to React. */
  publish: (state: SceneImageAiState) => void;
  /** The live scene — the asset registry the edit gate reads. */
  scene: Scene | null;
}

export interface SceneImageAiRunner {
  /** `true` only when the candidate actually landed (or was genuinely already
   * the document's picture). Every refusal returns `false` — the panel needs to
   * know, because a refusal must touch NOTHING, including the instruction draft
   * the user typed. */
  accept: () => boolean;
  edit: (instruction: string) => Promise<void>;
  generate: (prompt: string) => Promise<void>;
  reject: () => void;
  removeBackground: () => Promise<void>;
  /** `true` when a candidate was actually confirmed; `false` when there was
   * none to confirm. Same reason as `accept`. */
  saveAsNew: () => boolean;
}

/** Intent labels, for signature parity with the write path's other callers.
 * They stop at `applyOps`, which documents why the queue takes none. */
/**
 * Task 4 fix round 1 (I3): ask the write gate, and let the ONE refusal that has
 * words say them.
 *
 * Returns whether the caller may proceed. The two silent refusals stay silent —
 * a dead engine has the canvas's own G-D banner and "not armed" is a state no
 * user can see — but the agent-run lock reaches the inspector's note line, so a
 * Generate click while the design agent is working stops being a dead button.
 */
function refuseUnlessWritable(deps: SceneImageAiDeps): boolean {
  const gate = deps.writeGate();
  if (gate.allowed) return true;
  if (gate.note !== null) deps.onNote(gate.note);
  return false;
}

const GENERATE_INTENT = "inspector: generate image";
const ACCEPT_INTENT = "inspector: accept edited image";

const EMPTY: SceneImageAiState = {
  candidate: null,
  editing: false,
  generating: false,
  savedNotice: null,
};

function failureMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/**
 * The pure runner behind the hook — a closure whose only state is the suite's
 * own, so it is testable without React (the `createSceneReplaceImageHandler`
 * precedent). `readDeps` is read at call time AND AGAIN after every await, so
 * the runner keeps one identity while always seeing the current selection.
 *
 * THE SECOND READ IS NOT DEFENSIVE PADDING. A generation takes seconds, and
 * `applyOps` writes to whatever document is armed at the moment it is called —
 * so a selection that moved between the click and the response would land the
 * picture on a node the user is no longer looking at. It also re-asks §4's
 * lock, which can be turned on from the panel header while the model is
 * working.
 *
 * AND IT COMPARES THE DOCUMENT, NOT JUST THE NODE. Node ids are per-document
 * and the seed script writes template slugs (`image_hero`), so two ads
 * routinely carry the same id — a tab switch mid-generation passed a node-only
 * guard and wrote a real version, and a real undo step, into an ad the user
 * never touched. Every post-await gate on this lane asks both halves.
 */
export function createSceneImageAiRunner(
  readDeps: () => SceneImageAiDeps,
): SceneImageAiRunner {
  let state = EMPTY;
  const set = (patch: Partial<SceneImageAiState>) => {
    state = { ...state, ...patch };
    readDeps().publish(state);
  };

  const generate = async (prompt: string): Promise<void> => {
    // A second run while one is in flight is refused rather than queued: the
    // two would race onto the same node and the loser's picture could win.
    if (state.generating || state.editing) {
      return;
    }
    const trimmed = prompt.trim();
    if (!trimmed) {
      return;
    }
    const before = readDeps();
    const target = before.node;
    const documentId = before.documentId;
    // Not an image selection, or §4's lock, or nothing armed — REFUSED BEFORE
    // THE SPEND. A generation that mints an asset the editor cannot place is a
    // half write: a registry row nothing references, paid for.
    if (!target || !documentId || !sceneImageReplacementTarget(target)) {
      return;
    }
    if (!refuseUnlessWritable(before)) {
      return;
    }
    // A new attempt supersedes what the last one said. Cleared HERE rather than
    // at entry so a click the gate refuses remains the complete non-event every
    // other §4 refusal on this lane is, messages included.
    before.clearMessages();
    // A generate supersedes a save notice the same way an edit does: it
    // describes a picture this node is about to stop carrying.
    set({ generating: true, savedNotice: null });
    let record: AssetRecord;
    try {
      record = await before.generate({
        ...sceneGenerationResolution(target),
        label: sceneGeneratedAssetLabel(trimmed),
        prompt: trimmed,
      });
    } catch (cause) {
      // The API's own diagnostic, in the inspector's existing slot.
      before.onError(failureMessage(cause));
      return;
    } finally {
      set({ generating: false });
    }

    const after = readDeps();
    // BOTH HALVES: the same node id in a DIFFERENT document is a different
    // node (the header above says why), so the document is compared too.
    if (
      !after.node ||
      after.node.id !== target.id ||
      after.documentId !== documentId
    ) {
      return;
    }
    // The adapter re-asks §4's lock and answers "is this a write at all" — the
    // generation cache can hand back the very asset the node already carries.
    const operations = sceneImagePlacementOperations(after.node, record);
    if (!operations) {
      return;
    }
    after.applyOps(operations, GENERATE_INTENT);
  };

  const runEdit = async (
    instruction: string,
    transparentBackground?: boolean,
  ): Promise<void> => {
    if (state.generating || state.editing) {
      return;
    }
    // Upstream refuses a second edit while one is staged, and so does this: the
    // review is a question, and a new proposal would silently replace the one
    // the user has not answered yet.
    if (state.candidate) {
      return;
    }
    const trimmed = instruction.trim();
    if (!trimmed) {
      return;
    }
    const before = readDeps();
    const target = before.node;
    if (!target || !before.scene || !before.documentId) {
      return;
    }
    // Image, unlocked, and with a READY asset to edit — `sceneImageEditSource`
    // is the same gate that decides whether the block renders at all, asked
    // again here because the block is live for as long as it is on screen.
    const source = sceneImageEditSource(target, before.scene);
    // Armed too: an edit whose candidate could never be accepted is the same
    // half write a generation would be, one click later.
    if (!source || !refuseUnlessWritable(before)) {
      return;
    }
    before.clearMessages();
    set({ editing: true, savedNotice: null });
    let record: AssetRecord;
    try {
      record = await before.edit({
        label: sceneGeneratedAssetLabel(trimmed),
        prompt: trimmed,
        sourceAssetId: source,
        transparentBackground,
      });
    } catch (cause) {
      before.onError(failureMessage(cause));
      return;
    } finally {
      set({ editing: false });
    }
    // STAGED, never applied: the node is untouched until Accept. It is stamped
    // rather than discarded when the selection moved during the call — a paid
    // result is not thrown away, it is simply invisible until its own node is
    // selected again, and `accept` is what refuses to place it anywhere else.
    set({
      candidate: {
        forDocumentId: before.documentId,
        forNodeId: target.id,
        record,
      },
    });
  };

  return {
    accept: () => {
      const staged = state.candidate;
      if (!staged) {
        return false;
      }
      const deps = readDeps();
      // THE RULE THIS SLICE EXISTS TO KEEP: a candidate is placed on the node it
      // was made from, or nowhere.
      if (
        !deps.node ||
        deps.node.id !== staged.forNodeId ||
        deps.documentId !== staged.forDocumentId
      ) {
        return false;
      }
      // §4 and the armed check are asked BEFORE anything is cleared, because a
      // refused write must not update the panel's record of the document — the
      // candidate stays staged so the user can unlock and try again.
      if (
        !sceneImageReplacementTarget(deps.node) ||
        !refuseUnlessWritable(deps)
      ) {
        return false;
      }
      deps.clearMessages();
      const operations = sceneImagePlacementOperations(deps.node, staged.record);
      // `null` here is the no-op case (the edit handed back the asset the node
      // already carries): the document really does hold that picture, so the
      // review is genuinely over.
      if (operations && !deps.applyOps(operations, ACCEPT_INTENT)) {
        return false;
      }
      set({ candidate: null, savedNotice: null });
      return true;
    },
    edit: (instruction: string) => runEdit(instruction),
    generate,
    // Zero scene mutations. The candidate asset stays registered server-side —
    // abandoned, referenced by nothing — exactly as upstream leaves it.
    reject: () => set({ candidate: null, savedNotice: null }),
    removeBackground: () => runEdit(REMOVE_BACKGROUND_INSTRUCTION, true),
    // Also zero scene mutations: the API registered the asset when it generated
    // it, so this only confirms and dismisses the review. Upstream's sentence,
    // verbatim — the workspace asset library it names is real (`GET /assets`),
    // the platform simply has no screen for it yet.
    saveAsNew: () => {
      const staged = state.candidate;
      if (!staged) {
        return false;
      }
      set({
        candidate: null,
        savedNotice: {
          forDocumentId: staged.forDocumentId,
          forNodeId: staged.forNodeId,
          message: `Saved ${staged.record.label || staged.record.id} to the asset library.`,
        },
      });
      return true;
    },
  };
}

export function useSceneImageAi(options: {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  clearMessages: () => void;
  documentId: string | null;
  /** Injectable for tests; the platform's BFF transports by default. */
  edit?: (request: EditAssetRequest) => Promise<AssetRecord>;
  generate?: (request: GenerateAssetRequest) => Promise<AssetRecord>;
  node: Node | null;
  onError: (message: string) => void;
  onNote: (message: string) => void;
  scene: Scene | null;
  writeGate: () => SceneWriteGate;
}): SceneImageAiBinding {
  const {
    applyOps,
    clearMessages,
    documentId,
    edit = editSceneAsset,
    generate = generateSceneAsset,
    node,
    onError,
    onNote,
    scene,
    writeGate,
  } = options;
  const [state, setState] = useState<SceneImageAiState>(EMPTY);
  // A stable publisher rather than the raw setter, so the latest-value effect
  // below carries no `setState` identifier — this repo's react-hooks rule reads
  // one inside a dependency-less effect as an update loop, and this assignment
  // is neither a call nor a render-time write.
  const publish = useCallback((next: SceneImageAiState) => {
    setState(next);
  }, []);
  // Latest-value ref so the runner keeps one identity while always reading
  // current props (written in a passive effect, per this repo's react-hooks
  // rules — the same adaptation every other hook on this lane made).
  const depsRef = useRef<SceneImageAiDeps>({
    applyOps,
    clearMessages,
    documentId,
    edit,
    generate,
    node,
    onError,
    onNote,
    publish,
    scene,
    writeGate,
  });
  useEffect(() => {
    depsRef.current = {
      applyOps,
      clearMessages,
      documentId,
      edit,
      generate,
      node,
      onError,
      onNote,
      publish,
      scene,
      writeGate,
    };
  });

  // Built on first use rather than during render: the runner closes over the
  // deps ref, and this repo's react-hooks rules forbid handing a ref to a
  // function at render time. One runner per mount keeps the staged candidate.
  const runnerRef = useRef<SceneImageAiRunner | null>(null);
  const runner = useCallback(() => {
    runnerRef.current ??= createSceneImageAiRunner(() => depsRef.current);
    return runnerRef.current;
  }, []);

  const onAccept = useCallback(() => runner().accept(), [runner]);
  const onEdit = useCallback(
    (instruction: string) => void runner().edit(instruction),
    [runner],
  );
  const onGenerate = useCallback(
    (prompt: string) => void runner().generate(prompt),
    [runner],
  );
  const onRejectCandidate = useCallback(() => runner().reject(), [runner]);
  const onRemoveBackground = useCallback(
    () => void runner().removeBackground(),
    [runner],
  );
  const onSaveCandidateAsNew = useCallback(() => runner().saveAsNew(), [runner]);

  // The candidate is DERIVED against the current selection rather than pruned
  // when it changes — the discipline the session already applies to its scene,
  // its selection and its palette. A transient loading gap therefore cannot
  // discard a paid result, and coming back to the node restores the review.
  const forThisNode = (stamped: { forDocumentId: string; forNodeId: string }) =>
    stamped.forDocumentId === documentId && stamped.forNodeId === node?.id;
  const staged =
    state.candidate && forThisNode(state.candidate) ? state.candidate.record : null;
  const savedNotice =
    state.savedNotice && forThisNode(state.savedNotice)
      ? state.savedNotice.message
      : null;

  const beforeSrc = node && scene ? sceneImageBeforeSrc(node, scene) : null;
  const editSource = node && scene ? sceneImageEditSource(node, scene) : null;
  const statusLine = node && scene ? sceneImageStatusLine(node, scene) : null;

  return useMemo(
    () => ({
      beforeSrc,
      candidate: staged ? sceneImageCandidateView(staged) : null,
      canEdit: Boolean(editSource),
      editing: state.editing,
      generating: state.generating,
      hasImage: Boolean(node?.kind.kind === "image" && node.kind.asset_id),
      onAccept,
      onEdit,
      onGenerate,
      onRejectCandidate,
      onRemoveBackground,
      onSaveCandidateAsNew,
      savedNotice,
      statusLine,
    }),
    [
      beforeSrc,
      editSource,
      node,
      onAccept,
      onEdit,
      onGenerate,
      onRejectCandidate,
      onRemoveBackground,
      onSaveCandidateAsNew,
      savedNotice,
      staged,
      state.editing,
      state.generating,
      statusLine,
    ],
  );
}

/**
 * The two transports the hook binds by default, exported so the tests can drive
 * the very functions production uses rather than a look-alike.
 *
 * Both are the engine's own client (`assetLibrary.ts`, a verbatim upstream
 * port — never re-implemented), routed through `designBffConfig()`: the page
 * origin as the base plus a `fetchImpl` that re-mounts every engine URL under
 * the AUTHENTICATED `/api/clue/design` proxy, which stamps the workspace header
 * server-side. Never the headerless `design-public` passthrough — that one
 * serves public asset BYTES and the upstream route refuses a workspace header.
 *
 * One route (`POST /assets/generate`) carries both: an edit is the same call
 * with a `source_asset_id`, and remove-background is an edit with a fixed
 * prompt. The client also supplies the `provider` field the API 422s without.
 */
export async function generateSceneAsset(
  request: GenerateAssetRequest,
): Promise<AssetRecord> {
  const config = designBffConfig();
  const result = await generateAsset(config.apiBaseUrl, request, config.fetchImpl);
  return result.asset;
}

export async function editSceneAsset(
  request: EditAssetRequest,
): Promise<AssetRecord> {
  const config = designBffConfig();
  const result = await editAsset(config.apiBaseUrl, request, config.fetchImpl);
  return result.asset;
}
