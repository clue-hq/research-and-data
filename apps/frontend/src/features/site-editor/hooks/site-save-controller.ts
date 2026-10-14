import type { SiteDocument } from "@clue/site-kit/site-document";
import { SiteRepositoryError, type SiteRepository } from "../data/site.repository";
import { SITE_UNDO_CAP } from "../model/site-wire";

/**
 * Lane C / C2: the site lane's save policy, the web lane's (`use-web-manual-edits.ts`) for
 * whole-site saves. A plain class so it is testable without a DOM; `useSiteSaves` mirrors
 * its state into React.
 *
 *  - One request in flight. Everything asked meanwhile waits in ONE queue and runs in the order
 *    asked (review finding S2b-4: two ⌘Z are two steps, and an undo asked before a later edit runs
 *    before it). Only back-to-back saves merge: every save carries the whole site, so the newer one
 *    already contains the older.
 *  - A history step that lands drops the saves queued behind it (they were built on the copy
 *    from before the step). A refusal clears the queue (its base is gone) and reloads.
 *  - 409 `edits.base_version_mismatch` → the web lane's exact note, the edit is dropped, reload.
 *  - 409 `document.agent_run_active` → the agent-run lock's own sentence, reload.
 *  - 422 → the validator's first message, reload (the canvas goes back to what is saved).
 *  - A transport failure keeps the edit: the next save carries the whole site again.
 *  - A history step reloads on success (the frame must show the stepped document); a save does
 *    not (the frame already shows what was saved).
 */
export const SITE_MOVED_ON_NOTE = "Document moved on — reloaded.";
export const SITE_SAVE_FAILED = "This edit could not be saved.";
export const SITE_VERSION_GONE = "That version is no longer available.";

export interface SiteSaveState {
  busy: boolean;
  note: string | null;
  error: string | null;
  baseVersion: number | null;
  undoDepth: number;
  redoDepth: number;
}

export const IDLE_SITE_SAVE_STATE: SiteSaveState = {
  busy: false,
  note: null,
  error: null,
  baseVersion: null,
  undoDepth: 0,
  redoDepth: 0,
};

type HistoryStep = { kind: "undo" } | { kind: "redo" } | { kind: "restore"; batchId: string };
type QueuedOperation = { kind: "save"; site: SiteDocument; intent?: string } | { kind: "step"; step: HistoryStep };

export interface SiteSaveControllerDeps {
  documentId: string;
  lockNote: string;
  onReload: () => void;
  onState: (state: SiteSaveState) => void;
  /** The copy the canvas shows is out of date until the reload this controller asks for arrives: a
   * history step landed (the server moved), or a save was refused (the copy holds the refused edit).
   * The working copy refuses canvas proposals until that reload is adopted (sync-fix review F1). */
  onSuperseded?: (why: "save" | HistoryStep["kind"]) => void;
  repository: Pick<SiteRepository, "save" | "undo" | "redo" | "restore">;
}

export class SiteSaveController {
  private state: SiteSaveState = IDLE_SITE_SAVE_STATE;
  private inFlight = false;
  private queue: QueuedOperation[] = [];
  private reloadWhenIdle = false;
  private disposed = false;

  constructor(private readonly deps: SiteSaveControllerDeps) {}

  get snapshot(): SiteSaveState {
    return this.state;
  }

  /** The version and stacks of the document as just loaded (first load and every reload). */
  adopt(loaded: { version: number; undoDepth: number; redoDepth: number }): void {
    this.update({ baseVersion: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth });
  }

  /** Nothing in flight and nothing queued. */
  isIdle(): boolean {
    return !this.inFlight && this.queue.length === 0;
  }

  /** Reload now when idle; otherwise once the queue drains (a refusal's own reload satisfies it).
   * The working copy asks for this when a load arrives mid-save: adopting it then could put an
   * older copy over edits still on their way to the server. */
  requestReloadWhenIdle(): void {
    if (this.isIdle()) {
      this.deps.onReload();
      return;
    }
    this.reloadWhenIdle = true;
  }

  save(site: SiteDocument, intent?: string): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      const last = this.queue.at(-1);
      if (last?.kind === "save") this.queue[this.queue.length - 1] = { kind: "save", site, intent };
      else this.queue.push({ kind: "save", site, intent });
      return;
    }
    void this.runSave(site, intent);
  }

  undo(): void {
    this.step({ kind: "undo" });
  }

  redo(): void {
    this.step({ kind: "redo" });
  }

  restore(batchId: string): void {
    this.step({ kind: "restore", batchId });
  }

  /** The inline error line, for adjacent write paths that fail before any save (an upload). */
  reportError(message: string): void {
    this.update({ note: null, error: message });
  }

  clearMessages(): void {
    this.update({ note: null, error: null });
  }

  /** Mark the controller live. React's StrictMode runs an effect's cleanup and then the effect
   * again on the same render's objects, so the lifetime is attach/dispose, not create/dispose. */
  attach(): void {
    this.disposed = false;
  }

  dispose(): void {
    this.disposed = true;
  }

  private step(step: HistoryStep): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      this.queue.push({ kind: "step", step });
      return;
    }
    void this.runStep(step);
  }

  private async runSave(site: SiteDocument, intent?: string): Promise<void> {
    const baseVersion = this.state.baseVersion;
    if (baseVersion === null) return;
    this.begin();
    try {
      const result = await this.deps.repository.save(this.deps.documentId, { site, baseVersion, intent });
      this.update({
        baseVersion: result.version,
        undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP),
        redoDepth: 0,
      });
      this.finish();
    } catch (cause) {
      this.abandon();
      this.refused(cause, "save");
    }
  }

  private async runStep(step: HistoryStep): Promise<void> {
    const baseVersion = this.state.baseVersion;
    if (baseVersion === null) return;
    this.begin();
    try {
      const { repository, documentId } = this.deps;
      const result =
        step.kind === "undo"
          ? await repository.undo(documentId, baseVersion)
          : step.kind === "redo"
            ? await repository.redo(documentId, baseVersion)
            : await repository.restore(documentId, step.batchId, baseVersion);
      const depths =
        step.kind === "undo"
          ? { undoDepth: Math.max(this.state.undoDepth - 1, 0), redoDepth: this.state.redoDepth + 1 }
          : step.kind === "redo"
            ? { undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP), redoDepth: Math.max(this.state.redoDepth - 1, 0) }
            : { undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP), redoDepth: 0 };
      this.update({ baseVersion: result.version, ...depths });
      // Saves queued while the step ran were built on the copy from BEFORE it: running them now
      // would put that older copy back over the step. They are dropped; the step's reload pushes
      // the stepped copy to the canvas, which drops its unsent typing the same way.
      this.queue = this.queue.filter((operation) => operation.kind === "step");
      this.deps.onSuperseded?.(step.kind);
      this.finish();
      this.deps.onReload();
    } catch (cause) {
      this.abandon();
      this.refused(cause, step.kind);
    }
  }

  private begin(): void {
    this.inFlight = true;
    this.update({ busy: true, note: null, error: null });
  }

  private finish(): void {
    this.inFlight = false;
    const next = this.queue.shift();
    if (next?.kind === "save") {
      void this.runSave(next.site, next.intent);
      return;
    }
    if (next?.kind === "step") {
      void this.runStep(next.step);
      return;
    }
    this.update({ busy: false });
    if (this.reloadWhenIdle) {
      this.reloadWhenIdle = false;
      this.deps.onReload();
    }
  }

  private abandon(): void {
    this.inFlight = false;
    this.queue = [];
  }

  /** A refusal that reloads: the copy is superseded, and the reload also serves a deferred one. */
  private refusedAndReload(operation: "save" | HistoryStep["kind"], patch: Partial<SiteSaveState>): void {
    this.reloadWhenIdle = false;
    this.deps.onSuperseded?.(operation);
    this.update(patch);
    this.deps.onReload();
  }

  private refused(cause: unknown, operation: "save" | HistoryStep["kind"]): void {
    const error = cause instanceof SiteRepositoryError ? cause : null;
    if (error?.status === 409 && (error.code === "undo.empty" || error.code === "redo.empty")) {
      this.refusedAndReload(operation, { busy: false });
      return;
    }
    if (error?.status === 409 && error.code === "edits.base_version_mismatch") {
      this.refusedAndReload(operation, { busy: false, note: SITE_MOVED_ON_NOTE, error: null });
      return;
    }
    if (error?.status === 409 && error.code === "document.agent_run_active") {
      this.refusedAndReload(operation, { busy: false, note: this.deps.lockNote, error: null });
      return;
    }
    if (error?.status === 422) {
      this.refusedAndReload(operation, { busy: false, note: null, error: error.errors[0] ?? error.message });
      return;
    }
    if (error?.status === 404 && operation === "restore") {
      this.refusedAndReload(operation, { busy: false, note: null, error: SITE_VERSION_GONE });
      return;
    }
    // A transport failure keeps the edit (the next save carries the whole site again) and does not
    // reload on its own, so a reload deferred behind this save still has to happen (review F3).
    this.update({ busy: false, note: null, error: cause instanceof Error ? cause.message : SITE_SAVE_FAILED });
    if (this.reloadWhenIdle) {
      this.reloadWhenIdle = false;
      this.deps.onReload();
    }
  }

  private update(patch: Partial<SiteSaveState>): void {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.deps.onState(this.state);
  }
}
