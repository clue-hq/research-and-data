"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  arrangeEnablement,
  arrangeShortcut,
  zOrderOperation,
  type ArrangeEnablement,
  type ZOrderAction,
} from "../adapter/scene-arrange";
import {
  alignNodesOperations,
  distributeNodesOperations,
  type AlignMode,
  type DistributeAxis,
} from "../engine/scene/alignDistribute";
import type { Operation, Scene } from "../engine/scene/contracts";
import {
  groupEdit,
  mintGroupId,
  ungroupEdit,
  type StructuredEdit,
} from "../engine/scene/structuredEdits";

/**
 * AD4.B step 4 (§1.5 Arrange): the session's arrange binding — the ad-side
 * sibling of `use-scene-replace-image.ts` / `use-scene-image-ai.ts`, and the
 * same shape for the same reason (AD4.A's precedent: components may not reach
 * the engine or the transport, so the SESSION composes a handler hook and hands
 * the panel the resulting callbacks).
 *
 * ── TWO TRANSPORTS, BECAUSE THE ENGINE HAS TWO ───────────────────────────
 * Z-order, align and distribute are `Operation`s: they go through
 * `writes.applyOps` in ONE call each, which is one optimistic apply and ONE
 * UNDO FRAME (`alignDistribute.ts:159-164` states that requirement for the
 * align/distribute batch, and the same rule makes a z-order step atomic).
 *
 * Group and ungroup are NOT operations. They are `StructuredEdit`s
 * (`structuredEdits.ts:147-161`) whose expansion into canonical operations is
 * the ENGINE's, so the client is not the authority on it — re-deriving "which
 * inserts and moves make a group" here would be the fabrication this lane's
 * optimistic path exists to avoid. They therefore travel `writes.applyEdit`,
 * which is the shipped undo/redo path's own control flow (single flight, drain
 * the write queue, POST, re-base the queue on the returned version, adopt by
 * reloading) pointed at `POST /documents/{id}/edits` instead of `/undo`. See
 * `use-scene-manual-edits.ts` for the whole posture; nothing new was invented.
 *
 * ── WHAT DECIDES, AND WHAT MERELY DISPATCHES ─────────────────────────────
 * Every eligibility rule and every operation is the engine's or the pure
 * adapter's (`adapter/scene-arrange.ts`, which composes the engine's own
 * `canAlignNodes`/`canDistributeNodes`/`canGroupNodes`/`canUngroupNode` and
 * builds the z-order `move_node` through `moveNodeToParent`). This file owns
 * only the sequencing and the keymap — and the keymap's rules are pure too
 * (`arrangeShortcut`), so what is left here is genuinely untestable-by-design
 * React plumbing rather than logic hiding in a hook.
 *
 * ── THE SELECTION SOURCE ─────────────────────────────────────────────────
 * `selectedIds` is the session's additive selection, which today is fed by the
 * LAYER PANEL alone (`nextSceneSelection`; the canvas's `onSelect` carries no
 * modifier — facts §7a). Multi-node arrange is therefore reachable by shift/⌘
 * clicking layer rows. Additive canvas selection is another lane's scope and is
 * deliberately not added here.
 */

export interface SceneArrangeBinding {
  /** What the section's fourteen buttons may do for this selection. */
  enablement: ArrangeEnablement;
  /** Bring to front / forward / backward / Send to back, on the PRIMARY node. */
  zOrder: (action: ZOrderAction) => void;
  /** The six alignment modes — the selected nodes align to EACH OTHER (the
   * engine computes the targets from their own boxes), never to the page. */
  align: (mode: AlignMode) => void;
  distribute: (axis: DistributeAxis) => void;
  group: () => void;
  ungroup: () => void;
}

export interface SceneArrangeDeps {
  /** The manual-edits controller's structured-edit step (group / ungroup). */
  applyEdit: (edit: StructuredEdit) => void;
  /** The manual-edits controller's one operation write path. */
  applyOps: (operations: Operation[], intent?: string) => boolean;
  /** Is the write path armed and the engine live? Asked before the operation
   * batches, whose two silent refusals would otherwise say nothing at all. */
  canApply: () => boolean;
  /** Clears both inline slots — a new arrange supersedes what the last said. */
  clearMessages: () => void;
  /** What the buttons are offering, so a keypress can never fire an action the
   * panel refuses. */
  enablement: ArrangeEnablement;
  scene: Scene | null;
  selectedIds: readonly string[];
}

/** The intent label, for signature parity with the write path's other callers.
 * It stops at `applyOps`, which documents why the queue takes none. */
const ARRANGE_INTENT = "arrange";

/**
 * The shared half of the three OPERATION actions: gate, build, apply ONCE.
 *
 * Every action is a NON-EVENT when it is not enabled: no dispatch, no message,
 * nothing cleared. The buttons are already disabled off the same `enablement`,
 * so reaching one of these guards means the keymap or a stale render tried
 * something the panel was not offering — and the honest answer to that is
 * silence, not an error line about a button the user could not press.
 */
function commitArrange(
  deps: SceneArrangeDeps,
  build: (scene: Scene, selectedIds: readonly string[]) => Operation[],
): void {
  // `canApply` is asked up front because two of `applyOps`'s three refusals say
  // NOTHING (not armed; the engine is D9 read-only) — the same reason the
  // Replace-image flow asks it.
  if (!deps.scene || !deps.canApply()) {
    return;
  }
  const operations = build(deps.scene, deps.selectedIds);
  // An arrange that moves nothing is not a write. `alignNodesOperations` and
  // `distributeNodesOperations` return only the nodes that actually move (and
  // skip any with no resolvable page-space box), so an already-aligned
  // selection legitimately produces none.
  if (operations.length === 0) {
    return;
  }
  deps.clearMessages();
  // ONE call: one optimistic apply, one queued batch, ONE undo frame.
  deps.applyOps(operations, ARRANGE_INTENT);
}

/** §1.5: group the selection into a fresh container. */
function runGroup(deps: SceneArrangeDeps): void {
  if (!deps.enablement.group || !deps.scene) {
    return;
  }
  deps.clearMessages();
  // The id is minted CLIENT-SIDE on purpose (the engine rejects a `group_id`
  // that already exists), so the edit replays deterministically — `mintGroupId`'s
  // own contract, and the MVP editor's posture verbatim.
  deps.applyEdit(
    groupEdit([...deps.selectedIds], mintGroupId(deps.scene), "Group"),
  );
}

/** §1.5: dissolve the selected container into its parent. */
function runUngroup(deps: SceneArrangeDeps): void {
  const nodeId = deps.selectedIds[0];
  if (!deps.enablement.ungroup || !nodeId) {
    return;
  }
  deps.clearMessages();
  // `allow_layout` stays FALSE, the MVP editor's default: ungrouping an
  // auto-layout container destroys its layout semantics, so the engine demands
  // the override explicitly and its refusal — in its own words — is the honest
  // answer until a surface exists to ask for it.
  deps.applyEdit(ungroupEdit(nodeId));
}

export function useSceneArrange(
  options: Omit<SceneArrangeDeps, "enablement"> & {
    /** The active design document; the ⌘G/⇧⌘G effect arms on it, exactly as
     * the ⌘Z pair does (`use-scene-inspector-writes.ts:360`). */
    documentId: string | null;
  },
): SceneArrangeBinding {
  const {
    applyEdit,
    applyOps,
    canApply,
    clearMessages,
    documentId,
    scene,
    selectedIds,
  } = options;

  const enablement = useMemo(
    () => arrangeEnablement(scene, selectedIds),
    [scene, selectedIds],
  );

  // Latest-value ref so every callback below — and the window listener — keeps
  // one identity while always reading current state. Written in a passive
  // effect, never at render time (this repo's react-hooks rule; the adaptation
  // every hook on this lane made).
  const depsRef = useRef<SceneArrangeDeps>({
    applyEdit,
    applyOps,
    canApply,
    clearMessages,
    enablement,
    scene,
    selectedIds,
  });
  useEffect(() => {
    depsRef.current = {
      applyEdit,
      applyOps,
      canApply,
      clearMessages,
      enablement,
      scene,
      selectedIds,
    };
  });

  const align = useCallback((mode: AlignMode) => {
    const deps = depsRef.current;
    if (!deps.enablement.align) return;
    commitArrange(deps, (live, ids) =>
      alignNodesOperations(live, [...ids], mode),
    );
  }, []);

  const distribute = useCallback((axis: DistributeAxis) => {
    const deps = depsRef.current;
    if (!deps.enablement.distribute) return;
    commitArrange(deps, (live, ids) =>
      distributeNodesOperations(live, [...ids], axis),
    );
  }, []);

  const zOrder = useCallback((action: ZOrderAction) => {
    const deps = depsRef.current;
    // The PRIMARY node alone — z-order is a single node's position in its own
    // sibling stack, and the enablement flags above are computed for it.
    const primary = deps.selectedIds[0];
    if (!primary || !deps.enablement.zOrder[action]) return;
    commitArrange(deps, (live) => {
      const operation = zOrderOperation(live, primary, action);
      return operation ? [operation] : [];
    });
  }, []);

  const group = useCallback(() => runGroup(depsRef.current), []);
  const ungroup = useCallback(() => runUngroup(depsRef.current), []);

  // ⌘G / ⇧⌘G. Same placement rule as ⌘Z/⇧⌘Z: armed on the document, torn down
  // with it, and skipping the same typing targets so a focused inspector field
  // keeps whatever its own ⌘G does. `preventDefault` fires ONLY for a shortcut
  // this lane handles — the browser's Find Again must survive every other ⌘G on
  // the window, including one aimed at an action the panel is refusing.
  useEffect(() => {
    if (!documentId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const intent = arrangeShortcut(event, event.target as HTMLElement | null);
      if (!intent) return;
      const deps = depsRef.current;
      if (!deps.enablement[intent]) return;
      event.preventDefault();
      if (intent === "group") runGroup(deps);
      else runUngroup(deps);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [documentId]);

  return useMemo(
    () => ({ align, distribute, enablement, group, ungroup, zOrder }),
    [align, distribute, enablement, group, ungroup, zOrder],
  );
}
