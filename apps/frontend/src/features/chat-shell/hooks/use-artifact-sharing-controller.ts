"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  slugifyArtifactTitle,
  type ArtifactAdvancedTab,
  type ArtifactPublishSettings,
  type ArtifactPublishStatus,
  type ArtifactShareExportFormat,
  type ArtifactShareView,
} from "../model/artifact-sharing";
import type { ChatShellArtifactKind } from "../model/chat-shell";

const SHARE_HOST = "share.cluehq.ai";

export function useArtifactSharingController({
  kind,
  title,
}: {
  kind: ChatShellArtifactKind;
  title: string;
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
  const [publishStatus, setPublishStatus] =
    useState<ArtifactPublishStatus>("draft");
  const [regenerateDescriptionOnPublish, setRegenerateDescriptionOnPublish] =
    useState(false);
  const [shareTitle, setShareTitle] = useState(title);
  const [slug, setSlug] = useState(() => slugifyArtifactTitle(title));
  const [slugDraft, setSlugDraft] = useState(slug);
  const [statusMessage, setStatusMessage] = useState("");
  const [view, setView] = useState<ArtifactShareView>("main");
  const menuRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const publishTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const shareUrl = useMemo(() => `https://${SHARE_HOST}/${slug}`, [slug]);

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
      if (publishTimerRef.current) clearTimeout(publishTimerRef.current);
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
    setPublishStatus("draft");
    setStatusMessage("Publishing link updated");
  }, [slugDraft]);

  const publishAsset = useCallback(() => {
    setPublishStatus("publishing");
    setStatusMessage("Publishing asset");
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publish-request", {
        detail: { kind, settings },
      }),
    );
    if (publishTimerRef.current) clearTimeout(publishTimerRef.current);
    publishTimerRef.current = setTimeout(() => {
      setPublishStatus("published");
      setStatusMessage("Asset published");
    }, 650);
  }, [kind, settings]);

  const copyLink = useCallback(async () => {
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
  }, [kind, shareUrl]);

  const previewExternally = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-preview-request", {
        detail: { kind, url: shareUrl },
      }),
    );
    setStatusMessage("External preview requested");
  }, [kind, shareUrl]);

  const saveAdvancedSettings = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publishing-settings-update", {
        detail: { kind, settings },
      }),
    );
    setPublishStatus("draft");
    setStatusMessage("Publishing settings saved");
    setView("main");
  }, [kind, settings]);

  const requestDescriptionGeneration = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-description-generate-request", {
        detail: { kind, title: shareTitle },
      }),
    );
    setStatusMessage("Description generation requested");
  }, [kind, shareTitle]);

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
    [kind],
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
      shareHost: SHARE_HOST,
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
