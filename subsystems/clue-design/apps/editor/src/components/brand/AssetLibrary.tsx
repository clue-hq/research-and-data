"use client";

import { useEffect, useMemo, useState } from "react";

import {
  type AssetDescription,
  fetchDescriptions,
  fetchLibraryAssets
} from "@/engine/brandLibrary";
import type { AssetRecord } from "@/engine/contracts";
import { AssetLightbox } from "./AssetLightbox";
import { AssetPreviewImage } from "./AssetPreviewImage";
import {
  type LibraryItem,
  buildLibraryItems,
  computeTagFacets,
  filterLibraryItems,
  formatBytes
} from "./libraryModel";

type ViewMode = "grid" | "table";

/**
 * Ploy's asset-library anatomy in the Cursor skin: a tag-facet sidebar (with
 * counts), a search field, a grid/table view toggle, and a detail lightbox.
 * Values are read-only in v1; the only mutation is the description PUT from the
 * lightbox, which merges back into local state.
 */
export function AssetLibrary({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [records, setRecords] = useState<AssetRecord[]>([]);
  const [descriptions, setDescriptions] = useState<Record<string, AssetDescription>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<ViewMode>("grid");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const assets = await fetchLibraryAssets({ apiBaseUrl });
        if (cancelled) {
          return;
        }
        setRecords(assets);
        const descs = await fetchDescriptions(
          { apiBaseUrl },
          assets.map((asset) => asset.id)
        );
        if (!cancelled) {
          setDescriptions(descs);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load assets.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  const items = useMemo(
    () => buildLibraryItems(records, descriptions),
    [records, descriptions]
  );
  const facets = useMemo(() => computeTagFacets(items), [items]);
  const filtered = useMemo(
    () => filterLibraryItems(items, activeTag, query),
    [items, activeTag, query]
  );
  const openItem = useMemo(
    () => items.find((item) => item.record.id === openId) ?? null,
    [items, openId]
  );

  function onDescriptionSaved(assetId: string, description: AssetDescription) {
    setDescriptions((prev) => ({ ...prev, [assetId]: description }));
  }

  return (
    <div className="lib-shell">
      <aside className="lib-sidebar">
        <button
          type="button"
          className={`chip lib-facet${activeTag === null ? " is-selected" : ""}`}
          onClick={() => setActiveTag(null)}
        >
          All assets<span className="lib-facet-count mono">{items.length}</span>
        </button>
        {facets.map((facet) => (
          <button
            type="button"
            key={facet.tag}
            className={`chip lib-facet${activeTag === facet.tag ? " is-selected" : ""}`}
            onClick={() => setActiveTag((prev) => (prev === facet.tag ? null : facet.tag))}
          >
            {facet.tag}
            <span className="lib-facet-count mono">{facet.count}</span>
          </button>
        ))}
      </aside>

      <section className="lib-content">
        <div className="lib-toolbar">
          <label className="field lib-search">
            <span className="field-label">Search</span>
            <input
              type="search"
              placeholder="Name or title"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="lib-view-toggle" role="group" aria-label="View">
            <button
              type="button"
              className={`btn btn-quiet btn-sm${view === "grid" ? " is-selected" : ""}`}
              aria-pressed={view === "grid"}
              onClick={() => setView("grid")}
            >
              Grid
            </button>
            <button
              type="button"
              className={`btn btn-quiet btn-sm${view === "table" ? " is-selected" : ""}`}
              aria-pressed={view === "table"}
              onClick={() => setView("table")}
            >
              Table
            </button>
          </div>
        </div>

        {loading ? <p className="caption">Loading assets…</p> : null}
        {error ? <span className="status-pill is-error">{error}</span> : null}
        {!loading && !error && filtered.length === 0 ? (
          <p className="caption">No assets match.</p>
        ) : null}

        {view === "grid" ? (
          <div className="grid-cards">
            {filtered.map((item) => (
              <LibraryGridCard
                key={item.record.id}
                apiBaseUrl={apiBaseUrl}
                item={item}
                onOpen={() => setOpenId(item.record.id)}
              />
            ))}
          </div>
        ) : (
          <LibraryTable
            apiBaseUrl={apiBaseUrl}
            items={filtered}
            onOpen={(id) => setOpenId(id)}
          />
        )}
      </section>

      {openItem ? (
        <AssetLightbox
          apiBaseUrl={apiBaseUrl}
          item={openItem}
          onClose={() => setOpenId(null)}
          onDescriptionSaved={onDescriptionSaved}
        />
      ) : null}
    </div>
  );
}

function LibraryGridCard({
  apiBaseUrl,
  item,
  onOpen
}: {
  apiBaseUrl: string;
  item: LibraryItem;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className="lib-card"
      data-testid={`lib-asset-${item.record.id}`}
      onClick={onOpen}
    >
      <span className="asset-thumb">
        <AssetPreviewImage
          apiBaseUrl={apiBaseUrl}
          assetId={item.record.id}
          alt={item.title}
        />
      </span>
      <span className="lib-card-title body">{item.title}</span>
      <span className="chip is-uppercase">{item.kind}</span>
    </button>
  );
}

function LibraryTable({
  apiBaseUrl,
  items,
  onOpen
}: {
  apiBaseUrl: string;
  items: LibraryItem[];
  onOpen: (id: string) => void;
}) {
  return (
    <table className="brand-table lib-table">
      <thead>
        <tr>
          <th />
          <th>Name</th>
          <th>Kind</th>
          <th>Size</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.record.id}
            data-testid={`lib-row-${item.record.id}`}
            className="lib-table-row"
            onClick={() => onOpen(item.record.id)}
          >
            <td className="lib-table-thumb">
              <span className="lib-table-thumb-cell">
                <AssetPreviewImage
                  apiBaseUrl={apiBaseUrl}
                  assetId={item.record.id}
                  alt={item.title}
                />
              </span>
            </td>
            <td>{item.title}</td>
            <td>{item.kind}</td>
            <td className="mono">{formatBytes(item.byteLength) ?? "—"}</td>
            <td className="mono">{item.createdAt ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
