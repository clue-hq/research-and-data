"use client";

import React, { useCallback, useEffect, useState } from "react";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchWebPublishInfo,
  publishWebDocument,
  rollbackWebPublish,
  suggestPublishSlug,
  unpublishWebSite,
  type WebPublishState
} from "@/engine/webDocuments";

/**
 * The topbar "Publish" modal. Loads the document's publish state on open, then
 * shows one of two faces:
 *   • not published → a slug input (prefilled with a client-side suggestion) +
 *     Publish; 422/409 rejections surface the server message inline.
 *   • published → the live URL (clickable + Copy), a status line, and the
 *     Republish / Roll back / Unpublish actions.
 * Every action refetches the state so the face + button availability stay
 * honest. Fetch shaping lives in webDocuments.ts; this only binds fields.
 */

interface WebPublishDialogProps {
  documentId: string;
  title: string;
  onClose: () => void;
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Something went wrong.";
}

export function WebPublishDialog({
  documentId,
  title,
  onClose
}: WebPublishDialogProps): React.ReactElement {
  const apiBaseUrl = editorApiBaseUrl();
  const [info, setInfo] = useState<WebPublishState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slugInput, setSlugInput] = useState("");
  const [copied, setCopied] = useState(false);

  // Load the publish state on open. Only prefill the slug input when the
  // document is not yet published — a published doc republishes its own slug.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchWebPublishInfo({ apiBaseUrl }, documentId)
      .then((next) => {
        if (cancelled) return;
        setInfo(next);
        if (!next.published) {
          setSlugInput(suggestPublishSlug(title, documentId));
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, documentId, title]);

  // Close on Escape.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Run a mutation, then refetch the state so the dialog face stays current.
  const runAction = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await action();
        const next = await fetchWebPublishInfo({ apiBaseUrl }, documentId);
        setInfo(next);
        if (!next.published) {
          setSlugInput((current) => current || suggestPublishSlug(title, documentId));
        }
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, documentId, title]
  );

  const onPublish = () =>
    runAction(() => publishWebDocument({ apiBaseUrl }, documentId, slugInput.trim()));
  const onRepublish = () => {
    if (info?.slug) runAction(() => publishWebDocument({ apiBaseUrl }, documentId, info.slug!));
  };
  const onUnpublish = () => {
    if (info?.slug) runAction(() => unpublishWebSite({ apiBaseUrl }, info.slug!));
  };
  const onRollback = () => {
    if (info?.slug) runAction(() => rollbackWebPublish({ apiBaseUrl }, info.slug!));
  };

  const absoluteUrl = info?.url ? new URL(info.url, apiBaseUrl).toString() : null;

  const onCopy = async () => {
    if (!absoluteUrl) return;
    try {
      await navigator.clipboard.writeText(absoluteUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the URL is still shown as a link */
    }
  };

  const renderBody = (): React.ReactElement => {
    if (loading) {
      return <p className="web-modal-hint">Loading publish status…</p>;
    }
    if (info?.published) {
      const statusLine =
        info.status === "unpublished"
          ? "Unpublished"
          : `Published · v${info.docVersion ?? "?"}`;
      return (
        <div className="web-modal-body">
          <div className="web-publish-live">
            <span className="web-publish-status">{statusLine}</span>
            {absoluteUrl ? (
              <a
                className="web-publish-url"
                href={absoluteUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {absoluteUrl}
              </a>
            ) : null}
          </div>
          <div className="web-modal-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onCopy}
              disabled={!absoluteUrl}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRepublish}
              disabled={busy}
            >
              Republish
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRollback}
              disabled={busy || !info.previousAvailable}
            >
              Roll back
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onUnpublish}
              disabled={busy}
            >
              Unpublish
            </button>
          </div>
        </div>
      );
    }
    return (
      <div className="web-modal-body">
        <label className="web-modal-field">
          <span className="web-modal-field-label">Address</span>
          <input
            type="text"
            value={slugInput}
            onChange={(event) => setSlugInput(event.target.value)}
            placeholder="my-site"
            spellCheck={false}
            autoFocus
          />
        </label>
        <p className="web-modal-hint">Lowercase letters, numbers, and hyphens. 3–64 characters.</p>
        <div className="web-modal-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onPublish}
            disabled={busy || slugInput.trim().length === 0}
          >
            {busy ? "Publishing…" : "Publish"}
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="web-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="web-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Publish website"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="web-modal-head">
          <span className="web-modal-title">Publish</span>
          <button
            type="button"
            className="web-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        {renderBody()}
        {error ? (
          <p className="web-modal-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
