"use client";

import React, { useCallback, useEffect, useState } from "react";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchAssets,
  publicAssetBytesUrl,
  publicAssetThumbnailUrl,
  uploadAsset
} from "@/engine/assetLibrary";
import type { AssetRecord } from "@/engine/contracts";

/**
 * The replace/insert-image drawer: a Library tab (the workspace asset list,
 * filtered to image-kind records) and an Upload tab (the multipart POST
 * /assets endpoint). Both settle on an {@link AssetRecord}, handed back to the
 * shell via {@link WebAssetDrawerProps.onPick} — the shell decides whether the
 * pick becomes a replace_asset op (Replace) or an insert_node op (Insert), and
 * whether an upsert_asset must precede it. Pure UI: it never touches the web
 * document.
 */

interface WebAssetDrawerProps {
  /** "insert" adds a new image node; "replace" swaps the selected image's
   * asset; "background" assigns a section/container background — copy only
   * (the shell owns the operation batch). */
  mode: "insert" | "replace" | "background";
  onPick: (record: AssetRecord) => void;
  onClose: () => void;
}

/** The asset kinds the drawer surfaces — anything image-shaped. */
const IMAGE_KINDS = new Set(["raster_image", "logo", "vector"]);

/** The best public preview URL for a record: full bytes when the digest is
 * known (immutable + cache-friendly), else the thumbnail digest; null when
 * neither exists — a registry URL would 401 from an <img>. */
function thumbnailUrl(apiBaseUrl: string, record: AssetRecord): string | null {
  return (
    publicAssetBytesUrl(apiBaseUrl, record) ?? publicAssetThumbnailUrl(apiBaseUrl, record)
  );
}

type DrawerTab = "library" | "upload";

export function WebAssetDrawer({ mode, onPick, onClose }: WebAssetDrawerProps): React.ReactElement {
  const [tab, setTab] = useState<DrawerTab>("library");
  const [assets, setAssets] = useState<AssetRecord[]>([]);
  const [listStatus, setListStatus] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const loadLibrary = useCallback(() => {
    let cancelled = false;
    setListStatus("loading");
    setListError(null);
    fetchAssets(editorApiBaseUrl(), { limit: 100 })
      .then((records) => {
        if (cancelled) return;
        setAssets(records.filter((record) => IMAGE_KINDS.has(record.kind)));
        setListStatus("ready");
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setListError(cause instanceof Error ? cause.message : "The library could not be loaded.");
        setListStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => loadLibrary(), [loadLibrary]);

  const onFile = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) {
        return;
      }
      setUploadBusy(true);
      setUploadError(null);
      uploadAsset(editorApiBaseUrl(), file, { kind: "raster_image" })
        .then((result) => {
          setUploadBusy(false);
          onPick(result.asset);
        })
        .catch((cause: unknown) => {
          setUploadBusy(false);
          setUploadError(cause instanceof Error ? cause.message : "Upload failed.");
        });
    },
    [onPick]
  );

  const apiBaseUrl = editorApiBaseUrl();
  const title =
    mode === "insert"
      ? "Insert image"
      : mode === "replace"
        ? "Replace image"
        : "Choose background image";

  return (
    <div className="web-drawer" role="dialog" aria-label={title}>
      <header className="web-drawer-head">
        <span className="web-drawer-title">{title}</span>
        <button
          type="button"
          className="web-drawer-close"
          onClick={onClose}
          aria-label="Close image drawer"
        >
          ×
        </button>
      </header>
      <div className="web-drawer-tabs" role="tablist" aria-label="Image source">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "library"}
          className={`web-rail-tab${tab === "library" ? " is-selected" : ""}`}
          onClick={() => setTab("library")}
        >
          Library
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "upload"}
          className={`web-rail-tab${tab === "upload" ? " is-selected" : ""}`}
          onClick={() => setTab("upload")}
        >
          Upload
        </button>
      </div>

      {tab === "library" ? (
        <div className="web-drawer-body">
          {listStatus === "loading" ? (
            <p className="web-empty-hint">Loading library…</p>
          ) : listStatus === "error" ? (
            <p className="web-insp-error" role="alert">
              {listError}
            </p>
          ) : assets.length === 0 ? (
            <p className="web-empty-hint">No images in the library yet — upload one.</p>
          ) : (
            <div className="web-asset-grid" role="list">
              {assets.map((record) => (
                <button
                  key={record.id}
                  type="button"
                  role="listitem"
                  className="web-asset-tile"
                  title={record.label}
                  onClick={() => onPick(record)}
                >
                  <img
                    src={thumbnailUrl(apiBaseUrl, record) ?? undefined}
                    alt={record.label}
                    loading="lazy"
                  />
                  <span className="web-asset-label">{record.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="web-drawer-body">
          <label className="btn btn-secondary btn-sm web-drawer-upload">
            {uploadBusy ? "Uploading…" : "Choose a file"}
            <input
              type="file"
              accept="image/*"
              disabled={uploadBusy}
              onChange={onFile}
              hidden
            />
          </label>
          <p className="web-empty-hint">
            {mode === "background"
              ? "A picked or uploaded image becomes the selected element’s background."
              : "A picked or uploaded image is placed on the canvas."}
          </p>
          {uploadError ? (
            <p className="web-insp-error" role="alert">
              {uploadError}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
