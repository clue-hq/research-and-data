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

/** What the saves on their way came to (K6-2): every one landed, at `version`; or one did not, and
 * `message` says why (the same words the inspector shows). */
export type SiteSettled = { ok: true; version: number | null } | { ok: false; message: string };

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
  /** Callers of `settled()` waiting for the queue to drain, each with the mark it counts from. */
  private waiters: { resolve: (outcome: SiteSettled) => void; since: number }[] = [];
  /** Every refused or failed write so far, counted, and the reason of the latest. */
  private failures = 0;
  private lastFailure: string | null = null;
  /** A transport failure keeps the edit in the working copy, not on the server: until a later write
   * lands, the server does not hold what the marketer sees. */
  private unsavedFailure: string | null = null;

  constructor(private readonly deps: SiteSaveControllerDeps) {}

  get snapshot(): SiteSaveState {
    return this.state;
  }

  /** The version and stacks of the document as just loaded (first load and every reload). */
  adopt(loaded: { version: number; undoDepth: number; redoDepth: number }): void {
    // The canvas now shows the copy just read from the server: nothing on screen is unsaved.
    this.unsavedFailure = null;
    this.update({ baseVersion: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth });
  }

  /** Nothing in flight and nothing queued. */
  isIdle(): boolean {
    return !this.inFlight && this.queue.length === 0;
  }

  /** K6-2: where `settled()` counts failures from. A caller that must first wait for something else
   * (the frame's unsent typing) takes the mark when it starts waiting, so a save refused in between
   * still counts. */
  mark(): number {
    return this.failures;
  }

  /** K6-2: resolves once nothing is in flight or queued (a publish waits for this, so what it ships
   * is what the marketer sees). It fails with the reason when a write was refused or did not reach
   * the server after `since` (default: now), and while an edit kept after a transport failure is
   * still unsaved. */
  settled(since: number = this.failures): Promise<SiteSettled> {
    if (this.isIdle()) return Promise.resolve(this.idleOutcome(since));
    return new Promise((resolve) => this.waiters.push({ resolve, since }));
  }

  /** Reload now when idle; otherwise once the queue drains (a refusal's own reload satisfies it).
   * The working copy asks for this when a load arrives mid-save: adopting it then could put an
   * older copy over edits still on their way to the server. */
  requestReloadWhenIdle(): void {
    if (this.isIdle()) {
      this.notifyReload();
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
   * again on the same render's objects, so the lifetime is attach/dispose, not create/dispose.
   * A controller is also kept for a document you left and attached again when you come back
   * (sync-fix review F4). */
  attach(): void {
    this.disposed = false;
  }

  /** Detach: no new writes are accepted, but what is already in flight or queued still goes to the
   * server (it is the marketer's work). A detached controller tells nobody: its state, reloads and
   * superseded notices concern the working copy of a document no longer shown, and the next visit
   * reads the document afresh. */
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
      this.unsavedFailure = null;
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
      // The step reloads the canvas from the server, so an edit kept after a failure is gone too.
      this.unsavedFailure = null;
      this.update({ baseVersion: result.version, ...depths });
      // Saves queued while the step ran were built on the copy from BEFORE it: running them now
      // would put that older copy back over the step. They are dropped; the step's reload pushes
      // the stepped copy to the canvas, which drops its unsent typing the same way.
      this.queue = this.queue.filter((operation) => operation.kind === "step");
      this.notifySuperseded(step.kind);
      this.finish();
      this.notifyReload();
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
      this.notifyReload();
    }
    this.settleWaiters();
  }

  private abandon(): void {
    this.inFlight = false;
    this.queue = [];
  }

  /** A refusal that reloads: the copy is superseded, and the reload also serves a deferred one. The
   * reload replaces the copy with what the server holds, so nothing is left unsaved. */
  private refusedAndReload(operation: "save" | HistoryStep["kind"], patch: Partial<SiteSaveState>): void {
    this.reloadWhenIdle = false;
    this.unsavedFailure = null;
    this.notifySuperseded(operation);
    this.update(patch);
    this.notifyReload();
  }

  private refused(cause: unknown, operation: "save" | HistoryStep["kind"]): void {
    this.refusedWithoutSettling(cause, operation);
    // Every refusal empties the queue, so the controller is idle: the waiters hear why.
    this.failures += 1;
    this.lastFailure = this.state.error ?? this.state.note ?? SITE_SAVE_FAILED;
    this.settleWaiters();
  }

  private idleOutcome(since: number): SiteSettled {
    const message = (this.failures > since ? this.lastFailure : null) ?? this.unsavedFailure;
    return message === null ? { ok: true, version: this.state.baseVersion } : { ok: false, message };
  }

  private settleWaiters(): void {
    if (!this.isIdle()) return;
    const waiters = this.waiters;
    this.waiters = [];
    for (const waiter of waiters) waiter.resolve(this.idleOutcome(waiter.since));
  }

  private refusedWithoutSettling(cause: unknown, operation: "save" | HistoryStep["kind"]): void {
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
    const message = cause instanceof Error ? cause.message : SITE_SAVE_FAILED;
    this.unsavedFailure = message;
    this.update({ busy: false, note: null, error: message });
    if (this.reloadWhenIdle) {
      this.reloadWhenIdle = false;
      this.notifyReload();
    }
  }

  private notifyReload(): void {
    if (!this.disposed) this.deps.onReload();
  }

  private notifySuperseded(why: "save" | HistoryStep["kind"]): void {
    if (!this.disposed) this.deps.onSuperseded?.(why);
  }

  private update(patch: Partial<SiteSaveState>): void {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.deps.onState(this.state);
  }
}
