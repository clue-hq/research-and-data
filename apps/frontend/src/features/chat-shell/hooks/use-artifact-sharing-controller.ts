"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { designBffConfig } from "@/features/design-editor/data/design-bff";
import {
  createHttpWebPublishRepository,
  type PublishKind,
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
  /** The document version now live (K6-2); null on a failure or when the
   * server does not say. */
  docVersion: number | null;
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
      docVersion: result.docVersion,
      message: "Published",
      status: "published",
      ...shareAddresses(result),
    };
  } catch (error) {
    const agentWorking = isAgentRunRefusal(error);
    return {
      agentWorking,
      docVersion: null,
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

/** What the site editor says when Publish asks it to finish the edits on their
 * way (K6-2): all landed, or the reason one did not. */
export type PublishReadiness =
  | { ok: true; version: number | null }
  | { ok: false; message: string };

/** The line the menu shows when a publish stops because an edit was not saved:
 * publishing then would ship the version before that edit. */
export function unsavedEditNote(reason: string): string {
  return `Not published: your latest edit was not saved (${reason.replace(/\.$/, "")}).`;
}

/** The line the menu shows when the indexing choice could not be stored, so the
 * publish does not go out with a setting the next reload would forget. */
export function indexingNotSavedNote(reason: string): string {
  return `Not published: the indexing setting was not saved (${reason.replace(/\.$/, "")}).`;
}

/** K6-2: the live site is behind the document — the document's version (the
 * server's, or the open editor's own, whichever is newer) is newer than the one
 * published. Unknown versions never claim a change. */
export function hasChangesSincePublish({
  currentVersion,
  editorVersion,
  publishedVersion,
}: {
  currentVersion: number | null;
  editorVersion: number | null;
  publishedVersion: number | null;
}): boolean {
  if (publishedVersion === null) return false;
  const known = [currentVersion, editorVersion].filter((value): value is number => value !== null);
  return known.length > 0 && Math.max(...known) > publishedVersion;
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
  beforePublish,
  documentId,
  documentVersion = null,
  kind,
  publishLocked = false,
  repository,
  title,
}: {
  /** K6-2: the site editor's wait for the edits on their way (typing the frame
   * has not sent, then the saves). Publish waits for it, so what goes live is
   * what the marketer sees, and stops with the reason when an edit did not save.
   * Absent publishes at once. */
  beforePublish?: (documentId: string) => Promise<PublishReadiness>;
  /** The design document behind the artifact. Absent while the stage has no
   * document yet — publishing is then unavailable rather than faked. */
  documentId?: string | null;
  /** K6-2: the version the open editor last saved or loaded, so an edit made
   * while the menu is open counts as a change since publishing. */
  documentVersion?: number | null;
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
  // R-F1: an ordinary site indexes. K6-3: once the publish state is read, this
  // starts from the document's durable `noindex` (an account page is born with
  // it), and a change here is stored on the document at the next publish.
  // K6-3: the document's durable noindex as last read or stored; null until then.
  const [durableNoindex, setDurableNoindex] = useState<boolean | null>(null);
  // The marketer's own tick or untick, until it is stored: a re-read (the menu
  // opening again) never puts the server's value back over it.
  const [indexingChoice, setIndexingChoice] = useState<boolean | null>(null);
  const allowIndexing = indexingChoice ?? (durableNoindex === null ? true : !durableNoindex);
  // K6-2: the version the live site was published from, and the document's
  // version as the server last said; null until known.
  const [publishedVersion, setPublishedVersion] = useState<number | null>(null);
  const [serverVersion, setServerVersion] = useState<number | null>(null);
  // K6-2: why the last publish stopped before publishing (an edit not saved).
  const [publishFailureNote, setPublishFailureNote] = useState<string | null>(null);
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
  // Review finding K6-1: one Share menu serves every artifact tab, so everything above belongs to the
  // document on screen. A different document starts from its own defaults (its address from its own
  // title), never the last one's address, link or publish result. React's adjust-state-on-prop
  // pattern (a render-time comparison), never a setState inside an effect.
  const [stateFor, setStateFor] = useState(documentId ?? null);
  if (stateFor !== (documentId ?? null)) {
    const fresh = slugifyArtifactTitle(title);
    setStateFor(documentId ?? null);
    setAdvancedTab("page");
    setIndexingChoice(null);
    setDurableNoindex(null);
    setPublishedVersion(null);
    setServerVersion(null);
    setPublishFailureNote(null);
    setCopied(false);
    setCustomHtml("");
    setDescription("");
    setEditingSlug(false);
    setMenuOpen(false);
    setPageUrls({});
    setPublishStatus("draft");
    setRefusedByAgentRun(false);
    setRegenerateDescriptionOnPublish(false);
    setShareTitle(title);
    setShareUrl("");
    setSlug(fresh);
    setSlugDirty(false);
    setSlugDraft(fresh);
    setStatusMessage("");
    setView("main");
  }
  // The document on screen now, for a publish that returns after the marketer has switched tabs.
  const documentRef = useRef(documentId);
  useEffect(() => {
    documentRef.current = documentId;
  });
  const menuRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const httpRepositoriesRef = useRef<Partial<Record<PublishKind, WebPublishRepository>>>({});

  /** The seam, built lazily: `designBffConfig()` reads `window`, so it may only
   * run in an event handler or an effect — never during a server render. A site
   * publishes through its own routes (the web routes refuse it), so there is
   * one seam per kind. */
  const resolveRepository = useCallback(() => {
    if (repository) return repository;
    const publishKind: PublishKind = kind === "site" ? "site" : "web";
    httpRepositoriesRef.current[publishKind] ??= createHttpWebPublishRepository(
      designBffConfig(),
      publishKind,
    );
    return httpRepositoriesRef.current[publishKind];
  }, [kind, repository]);

  const publishable = isWebsiteKind(kind) && Boolean(documentId);

  const setAllowIndexing = useCallback((allow: boolean) => setIndexingChoice(allow), []);

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
    setPublishFailureNote(null);
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
        setDurableNoindex(Boolean(state.noindex));
        setServerVersion(state.currentVersion ?? null);
        if (state.published && state.status === "active") {
          setPublishedVersion(state.docVersion);
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
          setPublishedVersion(null);
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
        setPublishFailureNote(null);
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
    const wasPublished = publishStatus === "published";
    // Stopping before the publish leaves the live site as it was, and says why.
    const stop = (note: string) => {
      setPublishStatus(wasPublished ? "published" : "draft");
      setStatusMessage(note);
      setPublishFailureNote(note);
    };
    setPublishStatus("publishing");
    setStatusMessage("Publishing asset");
    setRefusedByAgentRun(false);
    setPublishFailureNote(null);
    const seam = resolveRepository();
    // K6-2: the edits on their way land first, so the version published is the one on screen.
    if (beforePublish) {
      const ready = await beforePublish(documentId);
      if (documentRef.current !== documentId) return;
      if (!ready.ok) {
        stop(unsavedEditNote(ready.message));
        return;
      }
      if (ready.version !== null) {
        const saved = ready.version;
        setServerVersion((known) => Math.max(known ?? saved, saved));
      }
    }
    // K6-3: a changed indexing choice is stored on the document first — the explicit act that
    // keeps it across reloads (and the only one that can make an account page indexable). With the
    // stored value unknown, only noindex is stored; the server ORs the stored flag either way.
    const noindex = !allowIndexing;
    if (durableNoindex === null ? noindex : durableNoindex !== noindex) {
      try {
        const stored = await seam.setNoindex(documentId, noindex);
        if (documentRef.current !== documentId) return;
        setDurableNoindex(stored);
        setIndexingChoice(null);
      } catch (error) {
        if (documentRef.current !== documentId) return;
        stop(indexingNotSavedNote(error instanceof Error ? error.message : "Request failed"));
        return;
      }
    }
    const outcome = await publishWithRepository(seam, documentId, { noindex, slug });
    // The publish happened (or not) for ITS document; if the marketer has switched tabs meanwhile,
    // it says nothing here. Opening that site's menu again reads its real state.
    if (documentRef.current !== documentId) return;
    // A refused REpublish leaves the site live at its last version.
    setPublishStatus(outcome.status === "published" || !wasPublished ? outcome.status : "published");
    setStatusMessage(outcome.message);
    setRefusedByAgentRun(outcome.agentWorking);
    if (outcome.status !== "published") return;
    setShareUrl(outcome.url);
    setPageUrls(outcome.pageUrls);
    setSlugDirty(false);
    if (outcome.docVersion !== null) {
      const live = outcome.docVersion;
      setPublishedVersion(live);
      setServerVersion((known) => Math.max(known ?? live, live));
    }
    window.dispatchEvent(
      new CustomEvent("clue:artifact-publish-request", {
        detail: { kind, settings },
      }),
    );
  }, [
    allowIndexing,
    beforePublish,
    documentId,
    durableNoindex,
    kind,
    publishLocked,
    publishStatus,
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
      /** K6-2: the live site is behind the document — the menu says so and offers Republish. */
      changesSincePublish:
        publishStatus === "published" &&
        hasChangesSincePublish({ currentVersion: serverVersion, editorVersion: documentVersion, publishedVersion }),
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
      /** K6-2/K6-3: why the last publish stopped before publishing, or `null`. */
      publishFailureNote,
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
