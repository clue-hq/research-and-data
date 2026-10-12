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
 */
export const IMAGE_PLACEHOLDER_SRC = "/icons/chat-shell/inspector/web/image-preview.png";
export const SITE_IMAGE_NOT_SAVED = "That image has no stored file yet.";
const ASSET_STORE_URL = /^\/asset-store\/([0-9a-f]{64})$/;

/** One image field: a prop path on a component (a page section or the shell's header/footer). */
export interface SiteImageTarget {
  componentId: string;
  prop: string;
  target: string;
}

export function sameImageTarget(left: SiteImageTarget, right: SiteImageTarget): boolean {
  return left.target === right.target && left.componentId === right.componentId && left.prop === right.prop;
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

export interface SiteImageAiState {
  candidate: { documentId: string; record: AssetRecord; target: SiteImageTarget } | null;
  editing: boolean;
  generating: boolean;
  savedNotice: { documentId: string; message: string; target: SiteImageTarget } | null;
}

export const EMPTY_SITE_IMAGE_AI: SiteImageAiState = { candidate: null, editing: false, generating: false, savedNotice: null };

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
  reject: () => void;
  saveAsNew: () => boolean;
}

const failureOf = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function createSiteImageAiRunner(readDeps: () => SiteImageAiDeps): SiteImageAiRunner {
  let state = EMPTY_SITE_IMAGE_AI;
  const set = (patch: Partial<SiteImageAiState>) => {
    state = { ...state, ...patch };
    readDeps().publish(state);
  };
  return {
    accept(target) {
      const staged = state.candidate;
      const deps = readDeps();
      if (!staged || !sameImageTarget(staged.target, target) || deps.documentId !== staged.documentId || !deps.writable()) {
        return false;
      }
      const url = assetStoreUrlOf(staged.record);
      if (!url) {
        deps.onError(SITE_IMAGE_NOT_SAVED);
        return false;
      }
      deps.clearMessages();
      if (!deps.place(target, url)) return false;
      set({ candidate: null, savedNotice: null });
      return true;
    },
    async edit(target, instruction, transparentBackground) {
      const trimmed = instruction.trim();
      const before = readDeps();
      if (state.generating || state.editing || state.candidate || !trimmed || !before.documentId || !before.writable()) return;
      const source = before.sourceAssetId(before.currentUrl(target));
      if (!source) return;
      const documentId = before.documentId;
      before.clearMessages();
      set({ editing: true, savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.edit({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed, sourceAssetId: source, transparentBackground });
      } catch (cause) {
        before.onError(failureOf(cause));
        return;
      } finally {
        set({ editing: false });
      }
      set({ candidate: { documentId, record, target } });
    },
    async generate(target, prompt) {
      const trimmed = prompt.trim();
      const before = readDeps();
      if (state.generating || state.editing || !trimmed || !before.documentId || !before.writable()) return;
      const documentId = before.documentId;
      before.clearMessages();
      set({ generating: true, savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.generate({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed });
      } catch (cause) {
        before.onError(failureOf(cause));
        return;
      } finally {
        set({ generating: false });
      }
      const after = readDeps();
      // A paid picture is never placed on a document the user is no longer looking at.
      if (after.documentId !== documentId || !after.writable()) return;
      const url = assetStoreUrlOf(record);
      if (!url) {
        after.onError(SITE_IMAGE_NOT_SAVED);
        return;
      }
      after.place(target, url);
    },
    reject() {
      set({ candidate: null, savedNotice: null });
    },
    saveAsNew() {
      const staged = state.candidate;
      if (!staged) return false;
      set({
        candidate: null,
        savedNotice: {
          documentId: staged.documentId,
          message: `Saved ${staged.record.label || staged.record.id} to the asset library.`,
          target: staged.target,
        },
      });
      return true;
    },
  };
}

/** The ad lane's generate rows, driven for one site image field. */
export function siteImageAiBinding({
  ai,
  canEdit,
  documentId,
  runner,
  target,
  url,
}: {
  ai: SiteImageAiState;
  canEdit: boolean;
  documentId: string | null;
  runner: SiteImageAiRunner;
  target: SiteImageTarget;
  url: string;
}): SceneImageAiBinding {
  const candidate =
    ai.candidate && ai.candidate.documentId === documentId && sameImageTarget(ai.candidate.target, target) ? ai.candidate : null;
  const notice =
    ai.savedNotice && ai.savedNotice.documentId === documentId && sameImageTarget(ai.savedNotice.target, target)
      ? ai.savedNotice.message
      : null;
  const candidateUrl = candidate ? assetStoreUrlOf(candidate.record) : null;
  return {
    beforeSrc: url ? appAssetSrc(url) : null,
    candidate: candidate
      ? { label: candidate.record.label || candidate.record.id, previewSrc: candidateUrl ? appAssetSrc(candidateUrl) : null }
      : null,
    canEdit,
    editing: ai.editing,
    generating: ai.generating,
    hasImage: url !== "",
    onAccept: () => runner.accept(target),
    onEdit: (instruction) => void runner.edit(target, instruction),
    onGenerate: (prompt) => void runner.generate(target, prompt),
    onRejectCandidate: () => runner.reject(),
    onRemoveBackground: () => void runner.edit(target, REMOVE_BACKGROUND_INSTRUCTION, true),
    onSaveCandidateAsNew: () => runner.saveAsNew(),
    savedNotice: notice,
    statusLine: null,
  };
}
