import type { SiteDocument } from "@clue/site-kit/site-document";
import { SiteRepositoryError, type SiteRepository } from "../data/site.repository";
import { SITE_UNDO_CAP } from "../model/site-wire";

/**
 * Lane C / C2: the site lane's save policy, the web lane's (`use-web-manual-edits.ts`) for
 * whole-site saves. A plain class so it is testable without a DOM; `useSiteSaves` mirrors
 * its state into React.
 *
 *  - One request in flight. Later edits coalesce: only the NEWEST site is saved next, because
 *    every save carries the whole site, so the newest one already contains the others.
 *  - Undo / redo / restore queue behind a pending save (latest step wins).
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

export interface SiteSaveControllerDeps {
  documentId: string;
  lockNote: string;
  onReload: () => void;
  onState: (state: SiteSaveState) => void;
  repository: Pick<SiteRepository, "save" | "undo" | "redo" | "restore">;
}

export class SiteSaveController {
  private state: SiteSaveState = IDLE_SITE_SAVE_STATE;
  private inFlight = false;
  private pendingSave: { site: SiteDocument; intent?: string } | null = null;
  private pendingStep: HistoryStep | null = null;
  private disposed = false;

  constructor(private readonly deps: SiteSaveControllerDeps) {}

  get snapshot(): SiteSaveState {
    return this.state;
  }

  /** The version and stacks of the document as just loaded (first load and every reload). */
  adopt(loaded: { version: number; undoDepth: number; redoDepth: number }): void {
    this.update({ baseVersion: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth });
  }

  save(site: SiteDocument, intent?: string): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      this.pendingSave = { site, intent };
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

  dispose(): void {
    this.disposed = true;
  }

  private step(step: HistoryStep): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight || this.pendingSave) {
      this.pendingStep = step;
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
    if (this.pendingSave) {
      const next = this.pendingSave;
      this.pendingSave = null;
      void this.runSave(next.site, next.intent);
      return;
    }
    if (this.pendingStep) {
      const next = this.pendingStep;
      this.pendingStep = null;
      void this.runStep(next);
      return;
    }
    this.update({ busy: false });
  }

  private abandon(): void {
    this.inFlight = false;
    this.pendingSave = null;
    this.pendingStep = null;
  }

  private refused(cause: unknown, operation: "save" | HistoryStep["kind"]): void {
    const error = cause instanceof SiteRepositoryError ? cause : null;
    if (error?.status === 409 && (error.code === "undo.empty" || error.code === "redo.empty")) {
      this.update({ busy: false });
      this.deps.onReload();
      return;
    }
    if (error?.status === 409 && error.code === "edits.base_version_mismatch") {
      this.update({ busy: false, note: SITE_MOVED_ON_NOTE, error: null });
      this.deps.onReload();
      return;
    }
    if (error?.status === 409 && error.code === "document.agent_run_active") {
      this.update({ busy: false, note: this.deps.lockNote, error: null });
      this.deps.onReload();
      return;
    }
    if (error?.status === 422) {
      this.update({ busy: false, note: null, error: error.errors[0] ?? error.message });
      this.deps.onReload();
      return;
    }
    if (error?.status === 404 && operation === "restore") {
      this.update({ busy: false, note: null, error: SITE_VERSION_GONE });
      this.deps.onReload();
      return;
    }
    this.update({ busy: false, note: null, error: cause instanceof Error ? cause.message : SITE_SAVE_FAILED });
  }

  private update(patch: Partial<SiteSaveState>): void {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.deps.onState(this.state);
  }
}
