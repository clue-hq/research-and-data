import type { EditorMode } from "@clue/site-kit/editor-protocol";
import { pageFor, sectionDigests } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

/** Contract 4: a section link lives ten minutes; anything older than eight is refetched first. */
export const SECTION_LINK_REFRESH_MS = 8 * 60_000;

/** What an init depends on: the frame's boot, the document and its agent sections. */
export function siteInitKey(documentId: string, site: SiteDocument, frameBoot: number): string {
  return `${frameBoot}|${documentId}|${sectionDigests(site).join(",")}`;
}

export type FrameSync = { kind: "init" } | { kind: "replace"; rev: number } | { kind: "none" };

/** What the frame needs next. It is kept in step by the working copy's REVISION, which moves on every
 * change the app makes (a load with new content, a refused save's revert, a dock edit), never by the
 * server's version: a refused save leaves the version as it was, and the canvas must still go back
 * (review finding K1-4). */
export function frameSyncFor(input: {
  frameReady: boolean;
  initKey: string;
  sentInitKey: string | null;
  sentRev: number | null;
  rev: number;
}): FrameSync {
  if (!input.frameReady) return { kind: "none" };
  if (input.initKey !== input.sentInitKey) return { kind: "init" };
  if (input.rev !== input.sentRev) return { kind: "replace", rev: input.rev };
  return { kind: "none" };
}

export function linksFresh(loadedAt: number, now: number, linkCount: number): boolean {
  return linkCount === 0 || now - loadedAt < SECTION_LINK_REFRESH_MS;
}

/** Ruling: the agent-run lock applies to sites — while it holds, the canvas is a preview. */
export function siteFrameMode({ editing, locked }: { editing: boolean; locked: boolean }): EditorMode {
  return editing && !locked ? "edit" : "preview";
}

/** The app is the only side that saves, and it saves frame edits only in edit mode, unlocked. */
export function acceptsFrameEdits({ editing, locked }: { editing: boolean; locked: boolean }): boolean {
  return editing && !locked;
}

export function initialRoute(site: SiteDocument, wanted: string | null): string {
  return wanted && pageFor(site, wanted) ? wanted : "/";
}
