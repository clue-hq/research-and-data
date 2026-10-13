"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { designBffConfig } from "@/features/design-editor/data/design-bff";
import {
  createHttpWebPublishRepository,
  WebPublishError,
  type WebPublishRepository,
} from "@/features/design-editor/data/web-publish.repository";
import {
  slugifyArtifactTitle,
  type ArtifactAdvancedTab,
  type ArtifactPublishSettings,
  type ArtifactPublishStatus,
  type ArtifactShareView,
} from "../model/artifact-sharing";
import { AGENT_RUN_PUBLISH_NOTE } from "../model/agent-run-lock";
import { isWebsiteKind } from "../model/artifact-kind";
import type { ChatShellArtifactKind } from "../model/chat-shell";

/** What one publish attempt settled to.
 *
 * `url`/`pageUrls` are empty when the attempt failed, so a caller can render
 * the outcome without narrowing; `message` is always the line to show — the
 * server's refusal on a failure, "Published" on success.
 */
export interface ArtifactPublishOutcome {
  status: Extract<ArtifactPublishStatus, "draft" | "published">;
  url: string;
  pageUrls: Record<string, string>;
  message: string;
  /** True when the server refused because a design run is working on the
   * document (409 `document.agent_run_active`); `message` is then the
   * founder's publish note, never the refusal code. */
  agentWorking: boolean;
}

/** The design API's answer while a design run drives the document (Task 28,
 * founder 2026-10-13: a person's publish waits for the run to finish). */
function isAgentRunRefusal(error: unknown): boolean {
  return (
    error instanceof WebPublishError &&
    error.status === 409 &&
    error.code === "document.agent_run_active"
  );
}

/**
 * The addresses the share menu shows for a published site: the workspace's
 * custom hostname when it has an active one, else the Clue address.
 *
 * Both come from the server — the menu only picks between them. The custom
 * page map is used only when it carries entries, so a server (or workspace)
 * with no custom hostname keeps listing the Clue pages.
 */
export function shareAddresses({
  customPageUrls,
  customUrl,
  pageUrls,
  url,
}: {
  customPageUrls: Record<string, string>;
  customUrl: string | null;
  pageUrls: Record<string, string>;
  url: string | null;
}): { url: string; pageUrls: Record<string, string> } {
  return {
    pageUrls:
      Object.keys(customPageUrls).length > 0 ? customPageUrls : pageUrls,
    url: customUrl ?? url ?? "",
  };
}

/**
 * Publish through the seam and say what happened — the whole publish decision,
 * with no React in it, so it is tested directly.
 *
 * A refusal (a taken slug, a bad slug, an unreachable API) is an outcome, not a
 * throw: the menu goes back to `draft` and shows the server's own words — except
 * the agent-run refusal, which names a run and no words, so the menu says the
 * founder's note instead.
 */
export async function publishWithRepository(
  repository: WebPublishRepository,
  documentId: string,
  input: { slug: string; noindex: boolean },
): Promise<ArtifactPublishOutcome> {
  try {
    const result = await repository.publish(documentId, input);
    return {
      agentWorking: false,
      message: "Published",
      status: "published",
      ...shareAddresses(result),
    };
  } catch (error) {
    const agentWorking = isAgentRunRefusal(error);
    return {
      agentWorking,
      message: agentWorking
        ? AGENT_RUN_PUBLISH_NOTE
        : error instanceof Error
          ? error.message
          : "Publish failed",
      pageUrls: {},
      status: "draft",
      url: "",
    };
  }
}

/** One page of a published site, as the share menu lists it. */
export interface ArtifactPageLinkRow {
  /** What the row reads: the site root is "Home", every other route is itself. */
  label: string;
  route: string;
  url: string;
}

/**
 * Turn the server's route → URL map into the rows to list, site root first and
 * the rest alphabetical, so a multi-page site always reads in the same order.
 *
 * Pure, so the ordering is tested without a React harness. A single-entry map
 * still yields its one row — hiding the list for a one-page site is the
 * component's call, not this helper's.
 */
export function pageLinkRows(
  pageUrls: Record<string, string>,
): ArtifactPageLinkRow[] {
  return Object.entries(pageUrls)
    .sort(([left], [right]) => {
      if (left === right) return 0;
      if (left === "/") return -1;
      if (right === "/") return 1;
      return left.localeCompare(right);
    })
    .map(([route, url]) => ({
      label: route === "/" ? "Home" : route,
      route,
      url,
    }));
}

/** The host shown in front of the slug in the link field — read off the URL the
 * server gave us, never a constant of ours. Empty until there is one. */
function shareHostOf(shareUrl: string): string {
  if (!shareUrl) return "";
  try {
    return new URL(shareUrl).host;
  } catch {
    return "";
  }
}

export function useArtifactSharingController({
  documentId,
  kind,
  publishLocked = false,
  repository,
  title,
}: {
  /** The design document behind the artifact. Absent while the stage has no
   * document yet — publishing is then unavailable rather than faked. */
  documentId?: string | null;
  kind: ChatShellArtifactKind;
  /** Task 28 (founder 2026-10-13): a design run is working on this page, so a
   * publish now would ship it half-edited. Publish is inert and the menu says
   * why. Absent leaves publishing as it is; the server refuses mid-run either
   * way. */
  publishLocked?: boolean;
  /** Injected in tests and fixture mode; the real BFF-backed seam otherwise. */
  repository?: WebPublishRepository;
  title: string;
}) {
  const [advancedTab, setAdvancedTab] =
    useState<ArtifactAdvancedTab>("page");
  // R-F1: an ordinary site indexes. The server ORs the document's durable ABM
  // `noindex`, so leaving this on can never un-noindex an ABM account page.
  const [allowIndexing, setAllowIndexing] = useState(true);
  const [copied, setCopied] = useState(false);
  // FLAGGED F5: designed field, no backend contract yet
  const [customHtml, setCustomHtml] = useState("");
  // FLAGGED F5: designed field, no backend contract yet
  const [description, setDescription] = useState("");
  const [editingSlug, setEditingSlug] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pageUrls, setPageUrls] = useState<Record<string, string>>({});
  const [publishStatus, setPublishStatus] =
    useState<ArtifactPublishStatus>("draft");
  // A publish the server refused because the agent was working — a run this
  // surface had not seen yet when the button was pressed. It says the same
  // note as the lock until the next attempt, the menu closing, or the lock
  // itself moving (engaging takes over the note; releasing means that run is
  // over), so a finished run never leaves a stale "wait" line behind.
  const [refusedByAgentRun, setRefusedByAgentRun] = useState(false);
  const [lastPublishLocked, setLastPublishLocked] = useState(publishLocked);
  if (lastPublishLocked !== publishLocked) {
    setLastPublishLocked(publishLocked);
    setRefusedByAgentRun(false);
  }
  // FLAGGED F5: designed field, no backend contract yet
  const [regenerateDescriptionOnPublish, setRegenerateDescriptionOnPublish] =
    useState(false);
  const [shareTitle, setShareTitle] = useState(title);
  const [shareUrl, setShareUrl] = useState("");
  const [slug, setSlug] = useState(() => slugifyArtifactTitle(title));
  const [slugDirty, setSlugDirty] = useState(false);
  const [slugDraft, setSlugDraft] = useState(slug);
  const [statusMessage, setStatusMessage] = useState("");
  const [view, setView] = useState<ArtifactShareView>("main");
  const menuRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const httpRepositoryRef = useRef<WebPublishRepository | null>(null);

  /** The seam, built lazily: `designBffConfig()` reads `window`, so it may only
   * run in an event handler or an effect — never during a server render. */
  const resolveRepository = useCallback(() => {
    if (repository) return repository;
    httpRepositoryRef.current ??= createHttpWebPublishRepository(
      designBffConfig(),
    );
    return httpRepositoryRef.current;
  }, [repository]);

  const publishable = isWebsiteKind(kind) && Boolean(documentId);

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
    setRefusedByAgentRun(false);
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

  /** Opening the menu reads the document's real publish state, so the menu
   * shows what the site is actually doing right now — including a publish made
   * from somewhere else (the agent's own publish, another tab, the editor). */
  useEffect(() => {
    if (!menuOpen || !publishable || !documentId) return;
    let cancelled = false;
    void (async () => {
      try {
        const state = await resolveRepository().state(documentId);
        if (cancelled) return;
        if (state.published && state.status === "active") {
          setPublishStatus("published");
          if (state.slug) {
            setSlug(state.slug);
            setSlugDraft(state.slug);
          }
          const addresses = shareAddresses(state);
          setShareUrl(addresses.url);
          setPageUrls(addresses.pageUrls);
          setSlugDirty(false);
        } else {
          setPublishStatus("draft");
          setShareUrl("");
          setPageUrls({});
        }
      } catch (error) {
        if (cancelled) return;
        setStatusMessage(
          error instanceof Error ? error.message : "Publish status unavailable",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, menuOpen, publishable, resolveRepository]);

  const toggleMenu = useCallback(() => {
    setMenuOpen((current) => {
      if (current) {
        setEditingSlug(false);
        setRefusedByAgentRun(false);
        setView("main");
      }
      return !current;
    });
  }, []);

  const beginSlugEdit = useCallback(() => {
    setSlugDraft(slug);
    setEditingSlug(true);
  }, [slug]);

  /** A new slug is a pending change, not an unpublishing: the site stays up at
   * its current address until the marketer republishes. */
  const saveSlug = useCallback(() => {
    const nextSlug = slugifyArtifactTitle(slugDraft);
    setSlug(nextSlug);
    setSlugDraft(nextSlug);
    setEditingSlug(false);
    setSlugDirty(true);
    setStatusMessage("Publishing link updated");
  }, [slugDraft]);

  const publishAsset = useCallback(async () => {
    // The button is disabled while the agent works; this keeps any other way
    // of calling it from sending a publish the server would refuse anyway.
    if (publishLocked) return;
    if (!isWebsiteKind(kind)) {
      // Scene publishing has no backend contract; the menu says so rather than
      // reporting a success that never happened.
      setStatusMessage("Publishing is available for websites");
      return;
    }
    if (!documentId) {
      setStatusMessage("No document to publish yet");
      return;
    }
    setPublishStatus("publishing");
    setStatusMessage("Publishing asset");
    setRefusedByAgentRun(false);
    const outcome = await publishWithRepository(
      resolveRepository(),
      documentId,
      { noindex: !allowIndexing, slug },
    );
    setPublishStatus(outcome.status);
    setStatusMessage(outcome.message);
    setRefusedByAgentRun(outcome.agentWorking);
    if (outcome.status !== "published") return;
    setShareUrl(outcome.url);
    setPageUrls(outcome.pageUrls);
    setSlugDirty(false);
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publish-request", {
        detail: { kind, settings },
      }),
    );
  }, [
    allowIndexing,
    documentId,
    kind,
    publishLocked,
    resolveRepository,
    settings,
    slug,
  ]);

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

  /** Open the live page itself. There is nothing to preview until the site is
   * actually on the air, so an unpublished document is told to publish rather
   * than handed an empty tab. */
  const previewExternally = useCallback(() => {
    if (isWebsiteKind(kind)) {
      if (!shareUrl) {
        setStatusMessage("Publish first to preview the live page");
        return;
      }
      window.open(shareUrl, "_blank", "noopener,noreferrer");
      setStatusMessage("Opened in a new tab");
    } else {
      setStatusMessage("External preview requested");
    }
    window.dispatchEvent(
      new CustomEvent("clue:artifact-preview-request", {
        detail: { kind, url: shareUrl },
      }),
    );
  }, [kind, shareUrl]);

  /** Saved settings apply at the NEXT publish — the live site is untouched, so
   * this marks pending changes instead of pretending the site went to draft. */
  const saveAdvancedSettings = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publishing-settings-update", {
        detail: { kind, settings },
      }),
    );
    setSlugDirty(true);
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
      menuOpen,
      pageUrls,
      previewExternally,
      publishAsset,
      publishLocked,
      /** The line under the Publish button while it waits for the agent, or
       * `null`. One sentence for both reasons it can wait. */
      publishLockNote:
        publishLocked || refusedByAgentRun ? AGENT_RUN_PUBLISH_NOTE : null,
      publishStatus,
      regenerateDescriptionOnPublish,
      requestDescriptionGeneration,
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
      shareHost: shareHostOf(shareUrl),
      shareTitle,
      shareUrl,
      slug,
      slugDirty,
      slugDraft,
      statusMessage,
      toggleMenu,
      view,
    },
    menuRef,
  };
}
