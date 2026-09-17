"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { designBffConfig } from "@/features/design-editor/data/design-bff";
import {
  fetchWebPublishInfo,
  publishWebDocument,
  type WebPublishState,
} from "@/features/design-editor/engine/webDocuments";
import {
  publicLinkHost,
  slugifyArtifactTitle,
  type ArtifactAdvancedTab,
  type ArtifactPublishSettings,
  type ArtifactPublishStatus,
  type ArtifactShareExportFormat,
  type ArtifactShareView,
} from "../model/artifact-sharing";
import type { ChatShellArtifactKind } from "../model/chat-shell";

/** The share menu's per-document transient state, stamped with the document it
 * was captured for so a switched document never inherits it. */
interface ShareSession {
  forDocumentId: string | null;
  publishState: WebPublishState | null;
  publishStatus: ArtifactPublishStatus;
  statusMessage: string;
}

/** What a document with no share activity yet shows. Its `null` stamp matches
 * no web document, so a web artifact always starts empty; an ad (which has no
 * document and no publish backend) matches it and stays at these values. */
const EMPTY_SESSION: ShareSession = {
  forDocumentId: null,
  publishState: null,
  publishStatus: "draft",
  statusMessage: "",
};

export function useArtifactSharingController({
  kind,
  title,
  documentId,
}: {
  kind: ChatShellArtifactKind;
  title: string;
  /** The active web document, so the share menu reads and writes its real
   * publish state. Ads have no publish backend and pass nothing. */
  documentId?: string | null;
}) {
  const [advancedTab, setAdvancedTab] =
    useState<ArtifactAdvancedTab>("page");
  const [allowIndexing, setAllowIndexing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [customHtml, setCustomHtml] = useState("");
  const [description, setDescription] = useState("");
  const [editingSlug, setEditingSlug] = useState(false);
  const [lastExportFormat, setLastExportFormat] =
    useState<ArtifactShareExportFormat | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [session, setSession] = useState<ShareSession>(EMPTY_SESSION);
  const [regenerateDescriptionOnPublish, setRegenerateDescriptionOnPublish] =
    useState(false);
  const [shareTitle, setShareTitle] = useState(title);
  const [slug, setSlug] = useState(() => slugifyArtifactTitle(title));
  const [slugDraft, setSlugDraft] = useState(slug);
  const [view, setView] = useState<ArtifactShareView>("main");
  const menuRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Only a web artifact has a publish backend; an ad passes no document, so the
  // host segment stays empty and Publish stays inert.
  const webDocumentId = kind === "web" ? (documentId ?? null) : null;

  // A switched document must not inherit the previous one's publish state. The
  // session is STAMPED with the document it was captured for and DERIVED against
  // the current one, rather than reset synchronously in an effect
  // (react-hooks/set-state-in-effect) — the same idiom as
  // `useWebArtifactSelection` / `useCustomComponentArtifact`. A stale document's
  // leftovers are simply never served, and the first write after a switch starts
  // from the empty session. The slug is deliberately NOT part of this: the fetch
  // overwrites it from the backend when the new document is published, and an
  // unpublished one keeps its title-derived slug, exactly as before.
  const activeSession =
    session.forDocumentId === webDocumentId ? session : EMPTY_SESSION;
  const publishState = activeSession.publishState;
  const publishStatus = activeSession.publishStatus;
  const statusMessage = activeSession.statusMessage;

  const updateSession = useCallback(
    (
      patch:
        | Partial<Omit<ShareSession, "forDocumentId">>
        | ((live: ShareSession) => Partial<Omit<ShareSession, "forDocumentId">>),
    ) => {
      setSession((live) => {
        const base = live.forDocumentId === webDocumentId ? live : EMPTY_SESSION;
        return {
          ...base,
          forDocumentId: webDocumentId,
          ...(typeof patch === "function" ? patch(base) : patch),
        };
      });
    },
    [webDocumentId],
  );

  const setStatusMessage = useCallback(
    (message: string) => updateSession({ statusMessage: message }),
    [updateSession],
  );

  useEffect(() => {
    if (!menuOpen || !webDocumentId) return;
    let cancelled = false;
    void fetchWebPublishInfo(designBffConfig(), webDocumentId)
      .then((state) => {
        if (cancelled) return;
        updateSession({
          publishState: state,
          ...(state.published && state.slug ? { publishStatus: "published" as const } : {}),
        });
        if (state.published && state.slug) {
          setSlug(state.slug);
          setSlugDraft(state.slug);
        }
      })
      .catch(() => {
        // Leave the local state as it is; the publish action reports errors.
      });
    return () => {
      cancelled = true;
    };
  }, [menuOpen, updateSession, webDocumentId]);

  const shareHost = publicLinkHost(
    publishState?.customOrigin ?? publishState?.publicOrigin ?? null,
  );

  const shareUrl = useMemo(
    () =>
      publishState?.customUrl ??
      publishState?.url ??
      (publishState?.publicOrigin ? `${publishState.publicOrigin}/${slug}` : null),
    [publishState, slug],
  );

  const settings = useMemo<ArtifactPublishSettings>(
    () => ({
      allowIndexing,
      customHtml,
      description,
      regenerateDescriptionOnPublish,
      slug,
      title: shareTitle,
    }),
    [
      allowIndexing,
      customHtml,
      description,
      regenerateDescriptionOnPublish,
      shareTitle,
      slug,
    ],
  );

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    setEditingSlug(false);
    setView("main");
  }, []);

  useEffect(() => {
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) closeMenu();
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };

    document.addEventListener("pointerdown", dismissOnPointerDown);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown);
      document.removeEventListener("keydown", dismissOnEscape);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, [closeMenu]);

  const toggleMenu = useCallback(() => {
    setMenuOpen((current) => {
      if (current) {
        setEditingSlug(false);
        setView("main");
      }
      return !current;
    });
  }, []);

  const beginSlugEdit = useCallback(() => {
    setSlugDraft(slug);
    setEditingSlug(true);
  }, [slug]);

  const saveSlug = useCallback(() => {
    const nextSlug = slugifyArtifactTitle(slugDraft);
    setSlug(nextSlug);
    setSlugDraft(nextSlug);
    setEditingSlug(false);
    updateSession({ publishStatus: "draft", statusMessage: "Publishing link updated" });
  }, [slugDraft, updateSession]);

  const publishAsset = useCallback(() => {
    if (!webDocumentId) return; // ads have no publish backend; the button stays inert
    updateSession({ publishStatus: "publishing", statusMessage: "Publishing asset" });
    void publishWebDocument(designBffConfig(), webDocumentId, slug)
      .then((result) => {
        updateSession((live) => ({
          publishState: {
            published: true,
            slug: result.slug,
            url: result.url,
            customUrl: result.customUrl,
            publicOrigin: result.publicOrigin ?? live.publishState?.publicOrigin ?? null,
            customOrigin: result.customOrigin ?? live.publishState?.customOrigin ?? null,
            docVersion: result.docVersion,
            status: "active",
            previousAvailable: result.previousAvailable,
            updatedAt: live.publishState?.updatedAt ?? null,
            publishId: result.publishId,
            manifestDigest: result.manifestDigest,
            packageDigest: result.packageDigest,
            htmlDigest: result.htmlDigest,
          },
          publishStatus: "published",
          statusMessage: "Asset published",
        }));
        setSlug(result.slug);
        setSlugDraft(result.slug);
      })
      .catch((error: unknown) => {
        updateSession({
          publishStatus: "draft",
          statusMessage: error instanceof Error ? error.message : "Publishing failed",
        });
      });
  }, [slug, updateSession, webDocumentId]);

  const copyLink = useCallback(async () => {
    if (!shareUrl) {
      setStatusMessage("Publish to get a link");
      return;
    }
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      // The integration event remains available when clipboard permission is unavailable.
    }
    window.dispatchEvent(
      new CustomEvent("clue:artifact-share-link-copy", {
        detail: { kind, url: shareUrl },
      }),
    );
    setCopied(true);
    setStatusMessage("Link copied");
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopied(false), 1200);
  }, [kind, setStatusMessage, shareUrl]);

  const previewExternally = useCallback(() => {
    if (!shareUrl) {
      setStatusMessage("Publish to get a link");
      return;
    }
    window.dispatchEvent(
      new CustomEvent("clue:artifact-preview-request", {
        detail: { kind, url: shareUrl },
      }),
    );
    setStatusMessage("External preview requested");
  }, [kind, setStatusMessage, shareUrl]);

  const saveAdvancedSettings = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publishing-settings-update", {
        detail: { kind, settings },
      }),
    );
    updateSession({ publishStatus: "draft", statusMessage: "Publishing settings saved" });
    setView("main");
  }, [kind, settings, updateSession]);

  const requestDescriptionGeneration = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-description-generate-request", {
        detail: { kind, title: shareTitle },
      }),
    );
    setStatusMessage("Description generation requested");
  }, [kind, setStatusMessage, shareTitle]);

  const requestExport = useCallback(
    (format: ArtifactShareExportFormat) => {
      setLastExportFormat(format);
      setStatusMessage(`${format} export requested`);
      window.dispatchEvent(
        new CustomEvent("clue:artifact-export-request", {
          detail: { format, kind },
        }),
      );
    },
    [kind, setStatusMessage],
  );

  return {
    controller: {
      advancedTab,
      allowIndexing,
      beginSlugEdit,
      closeMenu,
      copied,
      copyLink,
      customHtml,
      description,
      editingSlug,
      lastExportFormat,
      menuOpen,
      previewExternally,
      publishAsset,
      publishStatus,
      regenerateDescriptionOnPublish,
      requestDescriptionGeneration,
      requestExport,
      saveAdvancedSettings,
      saveSlug,
      setAdvancedTab,
      setAllowIndexing,
      setCustomHtml,
      setDescription,
      setRegenerateDescriptionOnPublish,
      setShareTitle,
      setSlugDraft,
      setView,
      shareHost,
      shareTitle,
      shareUrl,
      slug,
      slugDraft,
      statusMessage,
      toggleMenu,
      view,
    },
    menuRef,
  };
}
