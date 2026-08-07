import { useCallback, useEffect, useRef, useState } from "react";
import { Images, Upload } from "lucide-react";

import type { AssetPlacement, AssetRecord, NodeId, Operation } from "../engine/contracts";
import {
  assetThumbnailUrl,
  buildNodePlacementOperations,
  fetchAssets,
  uploadAsset
} from "../engine/assetLibrary";

/**
 * Workspace asset browser (Phase E slice E7): upload, search, and place
 * library assets. Placement emits canonical operations through the
 * editor's normal apply path; this panel owns no design semantics.
 */
export function AssetBrowserPanel({
  apiBaseUrl,
  selectedNodeId,
  selectedNodePlacement = null,
  refreshToken,
  onOperations
}: {
  apiBaseUrl: string;
  selectedNodeId: NodeId | null;
  /** Existing placement on the selected node — carried forward on Replace so fit /
   * focal / slot binding survive swapping the image, instead of resetting to {}. */
  selectedNodePlacement?: AssetPlacement | null;
  /** Data-refresh signal: bumping the token refetches the library (a kept
   * image edit registered a new asset). */
  refreshToken?: number;
  onOperations: (operations: Operation[]) => void;
}) {
  const [assets, setAssets] = useState<AssetRecord[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      setAssets(
        await fetchAssets(apiBaseUrl, {
          q: query || undefined,
          kind: kind || undefined,
          limit: 50
        })
      );
      setError(null);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : String(fetchError));
    }
  }, [apiBaseUrl, kind, query]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken]);

  const handleUpload = useCallback(
    async (file: File) => {
      setBusy(true);
      setNotice(null);
      try {
        const result = await uploadAsset(apiBaseUrl, file, {
          label: file.name,
          uploadedBy: "editor"
        });
        setNotice(
          result.deduplicated
            ? `Uploaded ${result.asset.label} (existing bytes reused)`
            : `Uploaded ${result.asset.label}`
        );
        setError(null);
        await refresh();
      } catch (uploadError) {
        setError(uploadError instanceof Error ? uploadError.message : String(uploadError));
      } finally {
        setBusy(false);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }
    },
    [apiBaseUrl, refresh]
  );

  const placeAsset = useCallback(
    (record: AssetRecord) => {
      if (!selectedNodeId) {
        setError("Select a node before placing an asset.");
        return;
      }
      onOperations(buildNodePlacementOperations(record, selectedNodeId, selectedNodePlacement ?? {}));
      setNotice(`Placed ${record.label} into ${selectedNodeId}`);
      setError(null);
    },
    [onOperations, selectedNodeId, selectedNodePlacement]
  );

  return (
    <section className="inspector-section" data-testid="asset-browser-panel">
      <div className="section-heading">
        <Images aria-hidden size={15} />
        Asset library
      </div>
      <div className="asset-browser-controls">
        <input
          type="search"
          placeholder="Search assets"
          aria-label="Search assets"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          aria-label="Filter by kind"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="">All kinds</option>
          <option value="raster_image">Images</option>
          <option value="vector">Vectors</option>
          <option value="logo">Logos</option>
        </select>
        <label className="asset-upload-control">
          <Upload aria-hidden size={14} />
          {busy ? "Uploading…" : "Upload image"}
          <input
            ref={fileInputRef}
            type="file"
            aria-label="Upload asset"
            accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void handleUpload(file);
              }
            }}
          />
        </label>
      </div>
      {error ? <p className="muted asset-browser-error">{error}</p> : null}
      {notice ? <p className="muted asset-browser-notice">{notice}</p> : null}
      {assets.length === 0 && !error ? (
        <p className="muted">No assets in the library yet.</p>
      ) : (
        <ul className="asset-browser-list">
          {assets.map((record) => (
            <li key={record.id} data-testid={`asset-${record.id}`}>
              <img
                src={assetThumbnailUrl(apiBaseUrl, record.id)}
                alt={record.label}
                width={36}
                height={36}
                loading="lazy"
              />
              <div className="asset-browser-meta">
                <code>{record.label}</code>
                <small>
                  {record.kind}
                  {record.media?.mime_type ? ` · ${record.media.mime_type}` : ""}
                </small>
              </div>
              <button
                type="button"
                disabled={!selectedNodeId}
                title={
                  selectedNodeId
                    ? `Place into ${selectedNodeId}`
                    : "Select a node to place this asset"
                }
                onClick={() => placeAsset(record)}
              >
                Place
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
