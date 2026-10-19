import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import {
  REMOVE_BACKGROUND_INSTRUCTION,
  sceneGeneratedAssetLabel,
  type SceneImageAiBinding,
} from "@/features/design-editor/adapter/scene-image-ai";
import { DESIGN_PUBLIC_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import type { EditAssetRequest, GenerateAssetRequest } from "@/features/design-editor/engine/scene/assetLibrary";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";

/**
 * Lane C / C6: the site lane's image decisions. The shape is the ad lane's
 * (`use-scene-image-ai.ts`): refuse before you spend, re-check the document after the await, a
 * generation lands at once while an edit is a staged candidate, and a candidate is placed on the
 * field it was made for or nowhere.
 *
 * Every image target names its site (review finding S2b-1: an upload finishing after a tab switch
 * was placed on the other account's site), and AI work is kept per field — its site, component and
 * prop — so one field's waiting candidate or running request never blocks or shows on another
 * (review finding S2b-5).
 */
export const IMAGE_PLACEHOLDER_SRC = "/icons/chat-shell/inspector/web/image-preview.png";
export const SITE_IMAGE_NOT_SAVED = "That image has no stored file yet.";
/** An image finished (an upload, a generation) after the marketer had moved to another site. */
export const SITE_IMAGE_NOT_PLACED_MOVED =
  "The picture is saved in your asset library, but it was not placed: you had moved to another site.";
const ASSET_STORE_URL = /^\/asset-store\/([0-9a-f]{64})$/;

/** One image field: a prop path on a component (a page section or the shell's header/footer) of
 * one site. */
export interface SiteImageTarget {
  componentId: string;
  /** The site the field belongs to: an image is only ever placed on this site. */
  documentId: string;
  prop: string;
  target: string;
}

export function sameImageTarget(left: SiteImageTarget, right: SiteImageTarget): boolean {
  return (
    left.documentId === right.documentId &&
    left.target === right.target &&
    left.componentId === right.componentId &&
    left.prop === right.prop
  );
}

/** The key AI work is kept under: one entry per field of one site. */
export function imageFieldKey(target: SiteImageTarget): string {
  return JSON.stringify([target.documentId, target.target, target.componentId, target.prop]);
}

/** Whether the selection shows any image field, a list item's own fields included. */
export function fieldsHaveImage(fields: readonly FieldDescription[]): boolean {
  return fields.some((field) => field.kind === "image" || fieldsHaveImage(field.item ?? []));
}

/** Contract 1: an image in a site is `/asset-store/<sha256>` of a blob of this workspace. */
export function assetStoreUrlOf(record: Pick<AssetRecord, "media">): string | null {
  const digest = record.media?.digest;
  if (!digest || !/^sha-?256$/i.test(digest.algorithm) || !/^[0-9a-f]{64}$/.test(digest.value)) return null;
  return `/asset-store/${digest.value}`;
}

/** The app shows a site image through its own headerless passthrough; anything else is the
 * inspector's stock preview (never a foreign url in the app). */
export function appAssetSrc(url: string): string {
  return ASSET_STORE_URL.test(url) ? `${DESIGN_PUBLIC_BFF_PREFIX}${url}` : IMAGE_PLACEHOLDER_SRC;
}

/** The registry asset behind a site url, when it is ready to be edited. */
export function assetIdForUrl(records: readonly AssetRecord[], url: string): string | null {
  const match = ASSET_STORE_URL.exec(url);
  if (!match) return null;
  return records.find((candidate) => candidate.status === "ready" && candidate.media?.digest?.value === match[1])?.id ?? null;
}

/** One field's AI work: a request on its way, an edited picture waiting to be accepted, a notice. */
export interface SiteImageFieldAi {
  busy: "editing" | "generating" | null;
  candidate: AssetRecord | null;
  savedNotice: string | null;
}

export interface SiteImageAiState {
  fields: Readonly<Record<string, SiteImageFieldAi>>;
}

const IDLE_FIELD: SiteImageFieldAi = { busy: null, candidate: null, savedNotice: null };
export const EMPTY_SITE_IMAGE_AI: SiteImageAiState = { fields: {} };

export function imageFieldAi(state: SiteImageAiState, target: SiteImageTarget): SiteImageFieldAi {
  return state.fields[imageFieldKey(target)] ?? IDLE_FIELD;
}

export interface SiteImageAiDeps {
  clearMessages: () => void;
  currentUrl: (target: SiteImageTarget) => string;
  documentId: string | null;
  edit: (request: EditAssetRequest) => Promise<AssetRecord>;
  generate: (request: GenerateAssetRequest) => Promise<AssetRecord>;
  onError: (message: string) => void;
  place: (target: SiteImageTarget, url: string) => boolean;
  publish: (state: SiteImageAiState) => void;
  sourceAssetId: (url: string) => string | null;
  writable: () => boolean;
}

export interface SiteImageAiRunner {
  accept: (target: SiteImageTarget) => boolean;
  edit: (target: SiteImageTarget, instruction: string, transparentBackground?: boolean) => Promise<void>;
  generate: (target: SiteImageTarget, prompt: string) => Promise<void>;
  reject: (target: SiteImageTarget) => void;
  saveAsNew: (target: SiteImageTarget) => boolean;
}

const failureOf = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function createSiteImageAiRunner(readDeps: () => SiteImageAiDeps): SiteImageAiRunner {
  let state = EMPTY_SITE_IMAGE_AI;
  const set = (target: SiteImageTarget, patch: Partial<SiteImageFieldAi>) => {
    state = { fields: { ...state.fields, [imageFieldKey(target)]: { ...imageFieldAi(state, target), ...patch } } };
    readDeps().publish(state);
  };
  const field = (target: SiteImageTarget) => imageFieldAi(state, target);
  /** Before spending: the field's own site is the one open and writable, and the field is free. */
  const mayStart = (target: SiteImageTarget, deps: SiteImageAiDeps) =>
    field(target).busy === null && deps.documentId === target.documentId && deps.writable();
  return {
    accept(target) {
      const staged = field(target).candidate;
      const deps = readDeps();
      if (!staged || deps.documentId !== target.documentId || !deps.writable()) return false;
      const url = assetStoreUrlOf(staged);
      if (!url) {
        deps.onError(SITE_IMAGE_NOT_SAVED);
        return false;
      }
      deps.clearMessages();
      if (!deps.place(target, url)) return false;
      set(target, { candidate: null, savedNotice: null });
      return true;
    },
    async edit(target, instruction, transparentBackground) {
      const trimmed = instruction.trim();
      const before = readDeps();
      // One edit at a time on a field: a second one waits until its candidate is decided.
      if (!trimmed || !mayStart(target, before) || field(target).candidate) return;
      const source = before.sourceAssetId(before.currentUrl(target));
      if (!source) return;
      before.clearMessages();
      set(target, { busy: "editing", savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.edit({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed, sourceAssetId: source, transparentBackground });
      } catch (cause) {
        set(target, { busy: null });
        before.onError(failureOf(cause));
        return;
      }
      // Staged on its own field of its own site, even if the marketer has moved on meanwhile: it
      // waits there for them to accept or reject it.
      set(target, { busy: null, candidate: record });
    },
    async generate(target, prompt) {
      const trimmed = prompt.trim();
      const before = readDeps();
      if (!trimmed || !mayStart(target, before)) return;
      before.clearMessages();
      set(target, { busy: "generating", savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.generate({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed });
      } catch (cause) {
        set(target, { busy: null });
        before.onError(failureOf(cause));
        return;
      }
      set(target, { busy: null });
      const after = readDeps();
      // A paid picture is never placed on a site the marketer is no longer looking at; it is in the
      // library, and they are told.
      if (after.documentId !== target.documentId) {
        after.onError(SITE_IMAGE_NOT_PLACED_MOVED);
        return;
      }
      if (!after.writable()) return;
      const url = assetStoreUrlOf(record);
      if (!url) {
        after.onError(SITE_IMAGE_NOT_SAVED);
        return;
      }
      after.place(target, url);
    },
    reject(target) {
      set(target, { candidate: null, savedNotice: null });
    },
    saveAsNew(target) {
      const staged = field(target).candidate;
      if (!staged) return false;
      set(target, { candidate: null, savedNotice: `Saved ${staged.label || staged.id} to the asset library.` });
      return true;
    },
  };
}

/** The ad lane's generate rows, driven for one site image field. */
export function siteImageAiBinding({
  ai,
  canEdit,
  runner,
  target,
  url,
}: {
  ai: SiteImageAiState;
  canEdit: boolean;
  runner: SiteImageAiRunner;
  target: SiteImageTarget;
  url: string;
}): SceneImageAiBinding {
  const { busy, candidate, savedNotice } = imageFieldAi(ai, target);
  const candidateUrl = candidate ? assetStoreUrlOf(candidate) : null;
  return {
    beforeSrc: url ? appAssetSrc(url) : null,
    candidate: candidate
      ? { label: candidate.label || candidate.id, previewSrc: candidateUrl ? appAssetSrc(candidateUrl) : null }
      : null,
    canEdit,
    editing: busy === "editing",
    generating: busy === "generating",
    hasImage: url !== "",
    onAccept: () => runner.accept(target),
    onEdit: (instruction) => void runner.edit(target, instruction),
    onGenerate: (prompt) => void runner.generate(target, prompt),
    onRejectCandidate: () => runner.reject(target),
    onRemoveBackground: () => void runner.edit(target, REMOVE_BACKGROUND_INSTRUCTION, true),
    onSaveCandidateAsNew: () => runner.saveAsNew(target),
    savedNotice,
    statusLine: null,
  };
}
