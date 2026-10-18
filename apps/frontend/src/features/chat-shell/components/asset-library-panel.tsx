"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { LogoSearchState, SceneAssetLibraryBinding } from "@/features/design-editor/hooks/use-scene-asset-library";
import type { AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";
import { InspectorSelect } from "./inspector-primitives";
import {
  ASSET_LIBRARY_CATEGORIES,
  logoResultCaption,
  logoSearchHeading,
  nextFocusIndex,
  shouldCloseOnKey,
  shouldCloseOnPointer,
  splitLibrarySections,
} from "./asset-library-panel.logic";
import styles from "./chat-shell.module.css";

/**
 * The asset-library picker (spec option 2): a floating panel anchored beside the inspector over the
 * artifact stage. Props-only — no transport and no engine (the components rule); every rule it
 * follows lives in `asset-library-panel.logic.ts` with its tests, and every action is the Task-4
 * binding's (`pick` applies immediately, `refresh` retries, `close` closes).
 */

const COLUMNS = 4;

export function AssetLibraryPanel({ library, onUploadFile }: {
  library: SceneAssetLibraryBinding;
  onUploadFile?: (file: File) => void | Promise<void>;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const { brand, workspace } = splitLibrarySections(library.items);
  const ordered = [...brand, ...workspace];
  // `InspectorSelect` is a label-only select (`options: readonly string[]`), so the chip speaks the
  // category LABELS and this pair of lookups over the tested table translates — no second copy of
  // the category list, and no change to a shared primitive every other inspector row uses.
  const categoryLabel =
    ASSET_LIBRARY_CATEGORIES.find((option) => option.value === library.category)?.label ??
    ASSET_LIBRARY_CATEGORIES[0].label;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (shouldCloseOnKey(event.key, event.target)) library.close(); };
    const onPointer = (event: PointerEvent) => { if (shouldCloseOnPointer(event.target, panelRef.current)) library.close(); };
    window.addEventListener("keydown", onKey);
    window.document.addEventListener("pointerdown", onPointer, true);
    return () => { window.removeEventListener("keydown", onKey); window.document.removeEventListener("pointerdown", onPointer, true); };
  }, [library]);

  const tile = (item: AssetLibraryItem, index: number) => (
    <button
      aria-label={`${item.record.label}${item.inUse ? " (in use)" : ""}`}
      aria-pressed={item.inUse}
      className={`${styles.assetLibraryTile} ${item.inUse ? styles.assetLibraryTileInUse : ""}`}
      key={item.record.id}
      onClick={() => library.pick(item.record.id)}
      onFocus={() => setFocusIndex(index)}
      onKeyDown={(event) => {
        const next = nextFocusIndex(index, event.key, ordered.length, COLUMNS);
        if (next === null) return;
        event.preventDefault();
        (panelRef.current?.querySelectorAll<HTMLButtonElement>(`.${styles.assetLibraryTile}`)[next])?.focus();
      }}
      tabIndex={index === focusIndex ? 0 : -1}
      type="button"
    >
      <Image alt="" fill sizes="72px" src={library.thumbnailUrl(item.record)} unoptimized />
      {item.pinned ? <span className={styles.assetLibraryBadge}>Brand</span> : null}
      {item.inUse ? <span className={styles.assetLibraryBadgeDark}>In use</span> : null}
      <span className={styles.assetLibraryTileName}>{item.record.label}</span>
    </button>
  );

  const logoSearch = library.logoSearch;
  const logoTile = (logo: LogoSearchState["results"][number]) => {
    const caption = logoResultCaption(logo);
    const saving = logoSearch.savingAssetId === logo.asset_id;
    return (
      <button
        aria-label={`${caption.title}, ${caption.source}${saving ? " (adding…)" : ""}`}
        className={styles.logoSearchTile}
        disabled={logoSearch.savingAssetId !== null}
        key={logo.asset_id}
        onClick={() => library.pickLogo(logo.asset_id)}
        type="button"
      >
        <span className={`${styles.logoSearchPreview} ${logo.background === "dark" ? styles.logoSearchPreviewDark : ""}`}>
          <Image alt="" fill sizes="96px" src={logo.preview} unoptimized />
        </span>
        <span className={styles.logoSearchCaption}>
          {saving ? "Adding…" : caption.title}
          <span className={styles.logoSearchSource}>{caption.source}</span>
        </span>
      </button>
    );
  };

  return (
    <div aria-label="Asset library" className={styles.assetLibraryPanel} ref={panelRef} role="dialog">
      <div className={styles.assetLibraryHeader}>
        <span>Asset library</span>
        <button aria-label="Close asset library" className={styles.assetLibraryClose} onClick={library.close} type="button">✕</button>
      </div>
      <div className={styles.assetLibraryTabs} role="tablist">
        <button aria-selected={library.tab === "library"} className={styles.assetLibraryTab} onClick={() => library.setTab("library")} role="tab" type="button">Library</button>
        <button aria-selected={library.tab === "logo-search"} className={styles.assetLibraryTab} onClick={() => library.setTab("logo-search")} role="tab" type="button">Logo search</button>
      </div>
      {library.tab === "logo-search" ? (
        <>
          <form
            className={styles.assetLibraryTools}
            onSubmit={(event) => { event.preventDefault(); library.searchLogos(); }}
          >
            <input
              aria-label="Company website"
              autoFocus
              className={styles.assetLibrarySearch}
              onChange={(event) => library.setLogoQuery(event.target.value)}
              placeholder="Company website, like stripe.com"
              value={logoSearch.query}
            />
            <button
              className={styles.logoSearchButton}
              disabled={logoSearch.status === "searching" || logoSearch.query.trim() === ""}
              type="submit"
            >
              Search
            </button>
          </form>
          {logoSearch.error ? <div className={styles.assetLibraryError} role="alert">{logoSearch.error}</div> : null}
          <div className={styles.assetLibraryBody}>
            {logoSearch.status === "searching" ? (
              <p className={styles.logoSearchState} role="status">Searching for logos… this can take up to 20 seconds.</p>
            ) : null}
            {logoSearch.status === "done" && logoSearch.results.length === 0 ? (
              <p className={styles.logoSearchState} role="status">
                We couldn&rsquo;t confirm a logo for {logoSearch.searchedFor}.<br />
                Try the company&rsquo;s main website, or upload the file.
              </p>
            ) : null}
            {logoSearch.status === "done" && logoSearch.results.length > 0 ? (
              <>
                <div className={styles.assetLibrarySection}>{logoSearchHeading(logoSearch.name, logoSearch.results.length)}</div>
                <div className={styles.logoSearchGrid}>{logoSearch.results.map(logoTile)}</div>
              </>
            ) : null}
          </div>
        </>
      ) : (
        <>
          <div className={styles.assetLibraryTools}>
            <input aria-label="Search assets" className={styles.assetLibrarySearch} onChange={(event) => library.setQuery(event.target.value)} placeholder="Search" value={library.query} />
            {/* The shared select's control is `width: 100%`, so it is given a fixed
                share of the toolbar rather than the whole row — the search box
                keeps its `flex: 1`. */}
            <div className={styles.assetLibraryCategory}>
              <InspectorSelect
                label="Filter assets by type"
                onChange={(label) => {
                  const chosen = ASSET_LIBRARY_CATEGORIES.find((option) => option.label === label);
                  if (chosen) library.setCategory(chosen.value);
                }}
                options={ASSET_LIBRARY_CATEGORIES.map((option) => option.label)}
                value={categoryLabel}
              />
            </div>
          </div>
          {library.error ? (
            <div className={styles.assetLibraryError} role="alert">{library.error} <button className={styles.assetLibraryRetry} onClick={library.refresh} type="button">Retry</button></div>
          ) : null}
          <div className={styles.assetLibraryBody}>
            {brand.length > 0 ? <><div className={styles.assetLibrarySection}>Brand kit</div><div className={styles.assetLibraryGrid}>{brand.map((item, i) => tile(item, i))}</div></> : null}
            <div className={styles.assetLibrarySection}>Workspace{library.loading ? " · loading…" : ""}</div>
            <div className={styles.assetLibraryGrid}>{workspace.map((item, i) => tile(item, brand.length + i))}</div>
            {!library.loading && ordered.length === 0 ? <p className={styles.assetLibraryEmpty}>No images match.</p> : null}
          </div>
        </>
      )}
      <div className={styles.assetLibraryFooter}>
        <button className={styles.assetLibraryUpload} onClick={() => fileRef.current?.click()} type="button">Upload from computer</button>
        <input accept="image/png,image/jpeg,image/webp,image/svg+xml" className={styles.visuallyHiddenInput}
          onChange={(event) => { const file = event.target.files?.[0]; if (file && onUploadFile) void Promise.resolve(onUploadFile(file)).then(() => library.refresh(), () => undefined); event.target.value = ""; }}
          ref={fileRef} type="file" />
      </div>
    </div>
  );
}
