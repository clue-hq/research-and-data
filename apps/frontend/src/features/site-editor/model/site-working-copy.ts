import { canonicalJson } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

/**
 * The app's working copy of the open site: the only copy in the browser that decides what is saved
 * (the sync fix, 2026-10-14; review findings K1-4, K3-3, K3-5, S2b-3).
 *
 *     server (truth) ──load/save──► working copy ──push──► frame (Puck draws it)
 *                                        ▲                      │
 *                                        └──── proposed edit ───┘
 *
 * The revision counter moves on every change the APP makes to the copy — a load adopted with new
 * content, a dock edit, an image placed — and each such change is pushed to the frame with its
 * revision. A canvas edit the frame proposes names the revision it started from; one made over an
 * older revision is refused (the frame is about to receive the newer copy and drops its unsent
 * typing, exactly once). A proposal accepted does not move the revision: the frame already shows it.
 * Revisions come from one counter per instance and never repeat, across documents too.
 *
 * Superseded (sync-fix review F1): once a history step lands or a save is refused, the copy is out of
 * date until the reload arrives. Proposals and app edits made in that window are refused (they would
 * re-apply what was undone, or resend what was refused), and the reload, when adopted, always moves
 * the revision so the frame drops whatever it typed meanwhile.
 */
export interface WorkingCopy {
  documentId: string;
  site: SiteDocument;
  rev: number;
}

export type ProposalVerdict = "accepted" | "stale" | "unchanged";
export type LoadDecision = "adopt" | "stale" | "defer";

/**
 * May a load replace the working copy?
 *  - the first load (nothing written yet) is adopted;
 *  - a load older than the version the save queue already wrote was read before our own save landed:
 *    adopting it would put the older copy back (S2b-3), so it is ignored;
 *  - while saves or history steps are still on their way, a load is deferred (the caller asks for a
 *    reload once the queue drains), because adopting it could undo edits the server has not seen;
 *  - otherwise it is adopted (our own write echoed back, or someone else's newer one).
 */
export function loadDecision(input: { loadedVersion: number; knownVersion: number | null; idle: boolean }): LoadDecision {
  if (input.knownVersion === null) return "adopt";
  if (input.loadedVersion < input.knownVersion) return "stale";
  if (!input.idle) return "defer";
  return "adopt";
}

export class SiteWorkingCopy {
  private copy: WorkingCopy | null = null;
  private nextRev = 1;
  private superseded = false;
  private readonly listeners = new Set<() => void>();

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly get = (): WorkingCopy | null => this.copy;

  /** A load the decision allowed. True when the content changed (the revision moved: push it). */
  adoptLoad(documentId: string, site: SiteDocument): boolean {
    const current = this.copy;
    const resync = this.superseded;
    this.superseded = false;
    if (!resync && current && current.documentId === documentId && canonicalJson(current.site) === canonicalJson(site)) return false;
    this.copy = { documentId, rev: this.nextRev++, site };
    this.emit();
    return true;
  }

  /** A canvas edit from the frame, made over revision `baseRev`. */
  propose(documentId: string, site: SiteDocument, baseRev: number): ProposalVerdict {
    const current = this.copy;
    if (this.superseded || !current || current.documentId !== documentId || current.rev !== baseRev) return "stale";
    if (canonicalJson(current.site) === canonicalJson(site)) return "unchanged";
    this.copy = { ...current, site };
    this.emit();
    return "accepted";
  }

  /** A change the app makes itself (a dock edit, an image placed). Returns the new revision. */
  edit(documentId: string, site: SiteDocument): number | null {
    const current = this.copy;
    if (this.superseded || !current || current.documentId !== documentId) return null;
    this.copy = { documentId, rev: this.nextRev++, site };
    this.emit();
    return this.copy.rev;
  }

  /** A history step landed or a save was refused: out of date until the next adopted load. */
  supersede(): void {
    this.superseded = true;
  }

  forget(): void {
    this.superseded = false;
    if (!this.copy) return;
    this.copy = null;
    this.emit();
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}
