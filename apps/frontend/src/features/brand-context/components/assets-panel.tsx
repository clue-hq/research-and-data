import { SelectField } from "@/components/ui/select-field";
export { AssetDetailDialog } from "./asset-detail-dialog";
import { CreativeTypeSchema, UsageRoleSchema, AssetSourceSchema, assetLabel } from "../model/asset-context";
import type { FocusEvent, KeyboardEvent } from "react";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandAsset, BrandAssetSortKey } from "../model/brand-context";
import { BrandContextIcon } from "./brand-context-icon";
import styles from "./brand-context.module.css";

function AssetVisual({ asset }: { asset: BrandAsset }) {
  if (asset.visual.kind === "image") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img alt="" loading="lazy" className={styles.assetImage} src={asset.visual.imagePath} />
    );
  }

  const background = `linear-gradient(135deg, ${asset.visual.colors.join(", ")})`;
  return <div className={styles.assetGradient} style={{ background }} />;
}

function closeWhenFocusLeaves(
  event: FocusEvent<HTMLDivElement>,
  close: () => void,
) {
  const nextTarget = event.relatedTarget;
  if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) close();
}

function AssetNameEditor({
  asset,
  controller,
  className,
}: {
  asset: BrandAsset;
  className?: string;
  controller: BrandContextController;
}) {
  if (controller.assetRenameId !== asset.id) {
    return <span className={className}>{asset.name}</span>;
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") controller.commitAssetRename();
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      controller.cancelAssetRename();
    }
  }

  return (
    <input
      aria-label={`Rename ${asset.name}`}
      autoFocus
      className={`${styles.assetRenameInput} ${className ?? ""}`}
      onBlur={controller.commitAssetRename}
      onChange={(event) => controller.setAssetRenameValue(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={onKeyDown}
      value={controller.assetRenameValue}
    />
  );
}

function AssetActions({
  asset,
  controller,
}: {
  asset: BrandAsset;
  controller: BrandContextController;
}) {
  const open = controller.assetMenuId === asset.id;

  return (
    <div
      className={`${styles.assetActions} ${open ? styles.assetActionsOpen : ""}`}
      onBlur={(event) => closeWhenFocusLeaves(event, controller.closeAssetMenu)}
    >
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Actions for ${asset.name}`}
        className={styles.assetMenuTrigger}
        onClick={(event) => {
          event.stopPropagation();
          controller.toggleAssetMenu(asset.id);
        }}
        type="button"
      >
        <BrandContextIcon name="more" size={12} />
      </button>
      {open ? (
        <div aria-label={`Actions for ${asset.name}`} className={styles.assetActionMenu} role="menu">
          <button onClick={() => controller.beginAssetRename(asset.id)} role="menuitem" type="button">
            <BrandContextIcon name="rename" size={14} />
            Rename
          </button>
          <button onClick={() => controller.editAssetDetails(asset.id)} role="menuitem" type="button">
            <BrandContextIcon name="settings" size={14} />
            Edit details
          </button>
          <button className={styles.assetActionDanger} onClick={() => controller.deleteAsset(asset.id)} role="menuitem" type="button">
            <BrandContextIcon name="trash" size={14} />
            Delete
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AssetSortHeader({
  controller,
  label,
  sortKey,
}: {
  controller: BrandContextController;
  label: string;
  sortKey: BrandAssetSortKey;
}) {
  const active = controller.assetSortKey === sortKey;

  return (
    <span
      aria-sort={active ? controller.assetSortDirection : "none"}
      className={active ? styles.assetSortHeaderActive : undefined}
      role="columnheader"
    >
      <button
        aria-label={`Sort by ${label}`}
        className={styles.assetSortButton}
        onClick={() => controller.setAssetSort(sortKey)}
        type="button"
      >
        {label}
        <BrandContextIcon
          className={active && controller.assetSortDirection === "ascending" ? styles.assetSortAscending : ""}
          name={active ? "sortActive" : "sort"}
          size={12}
        />
      </button>
    </span>
  );
}

export function AssetsHeader({
  controller,
}: {
  controller: BrandContextController;
}) {
  return (
    <header className={styles.assetPageHeader}>
      <div className={styles.assetPageTitleRow}>
        <h1>Assets</h1>
        <div className={styles.headerActions}>
          <button className={styles.primaryButton} type="button" disabled={!controller.assetLibrary.canWrite} onClick={() => controller.assetLibrary.setOpen(true)}>Upload assets{controller.assetLibrary.uploads.length ? ` (${controller.assetLibrary.uploads.length})` : ""}</button>
        </div>
      </div>
      <div className={styles.assetToolbar}>
        <label className={styles.searchField}>
          <BrandContextIcon name="search" size={12} />
          <input
            aria-label="Search assets"
            onChange={(event) => controller.setAssetQuery(event.target.value)}
            placeholder="Search"
            value={controller.assetQuery}
          />
        </label>
        <div className={styles.assetToolbarRight}>
          <div className={styles.assetToolbarFilters}>
            <label className={styles.assetFilterField}>Type
              <SelectField ariaLabel="Filter by creative type" value={controller.creativeTypeFilter}
                onValueChange={controller.setCreativeTypeFilter}
                options={[{value: "all", label: "All types"}, ...CreativeTypeSchema.options.map(value => ({value, label: assetLabel(value)}))]} />
            </label>
            <label className={styles.assetFilterField}>Used as
              <SelectField ariaLabel="Filter by usage" value={controller.usageFilter}
                onValueChange={controller.setUsageFilter}
                options={[{value: "all", label: "Any usage"}, ...UsageRoleSchema.options.map(value => ({value, label: assetLabel(value)}))]} />
            </label>
            <label className={styles.assetFilterField}>Source
              <SelectField ariaLabel="Filter by source" value={controller.sourceFilter}
                onValueChange={controller.setSourceFilter}
                options={[{value: "all", label: "All sources"}, ...AssetSourceSchema.options.map(value => ({value, label: assetLabel(value)}))]} />
            </label>
          </div>
          <div aria-label="Asset view" className={styles.iconSegmentedControl}>
            <button aria-label="Grid view" aria-pressed={controller.assetView === "grid"} className={controller.assetView === "grid" ? styles.iconSegmentActive : ""} onClick={() => controller.setAssetView("grid")} type="button">
              <BrandContextIcon name="grid" size={12} />
            </button>
            <button aria-label="List view" aria-pressed={controller.assetView === "list"} className={controller.assetView === "list" ? styles.iconSegmentActive : ""} onClick={() => controller.setAssetView("list")} type="button">
              <BrandContextIcon name="list" size={12} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

export function AssetsPanel({ controller }: { controller: BrandContextController }) {
  return (
    <div className={`${styles.assetsPanel} ${controller.assetView === "list" ? styles.assetsPanelList : styles.assetsPanelGrid}`}>
      {controller.assetView === "grid" ? (
        <div className={styles.assetGrid}>
          {controller.filteredAssets.map((asset) => (
            <article className={`${styles.assetCard} ${controller.assetMenuId === asset.id ? styles.assetCardMenuOpen : ""}`} key={asset.id}>
              <button aria-label={`Open ${asset.name}`} className={styles.assetCardOpen} onClick={() => controller.openAsset(asset.id)} type="button">
                <span className={styles.assetCardPreview}>
                  <AssetVisual asset={asset} />
                  {asset.origin === "kit" ? <span className={styles.assetCardBadge}>Brand</span> : null}
                </span>
              </button>
              <div className={styles.assetCardMeta}>
                <div><AssetNameEditor asset={asset} controller={controller} /><small className={styles.assetAnalysisStatus}>{assetLabel(asset.context?.creative_type ?? "unknown")} · {assetLabel(asset.context?.status ?? "stale")}</small></div>
                <AssetActions asset={asset} controller={controller} />
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className={styles.assetTable} role="table">
          <div className={styles.assetTableHeader} role="row">
            <div className={styles.assetTableColumns}>
              {controller.assetSortOptions.map((option) => (
                <AssetSortHeader
                  controller={controller}
                  key={option.value}
                  label={option.label}
                  sortKey={option.value}
                />
              ))}
            </div>
            <span aria-hidden="true" />
          </div>
          {controller.filteredAssets.map((asset) => (
            <div className={`${styles.assetTableRow} ${controller.assetMenuId === asset.id ? styles.assetTableRowMenuOpen : ""}`} key={asset.id} role="row">
              {controller.assetRenameId === asset.id ? (
                <div className={styles.assetTableRowMain}>
                  <span className={styles.assetNameCell} role="cell">
                    <span className={styles.assetThumb}><AssetVisual asset={asset} /></span>
                    <AssetNameEditor asset={asset} controller={controller} />
                  </span>
                  <span role="cell">{asset.type}</span>
                  <span role="cell">{asset.sizeLabel}</span>
                  <span role="cell">{asset.createdLabel}</span>
                </div>
              ) : (
                <button aria-label={`Open ${asset.name}`} className={styles.assetTableRowMain} onClick={() => controller.openAsset(asset.id)} type="button">
                  <span className={styles.assetNameCell} role="cell">
                    <span className={styles.assetThumb}><AssetVisual asset={asset} /></span>
                    <AssetNameEditor asset={asset} controller={controller} />
                  </span>
                  <span role="cell">{asset.type}</span>
                  <span role="cell">{asset.sizeLabel}</span>
                  <span role="cell">{asset.createdLabel}</span>
                </button>
              )}
              <div className={styles.assetTableActionCell} role="cell">
                <AssetActions asset={asset} controller={controller} />
              </div>
            </div>
          ))}
        </div>
      )}
      {!controller.filteredAssets.length ? <div className={styles.assetEmptyState}>No assets match this view.</div> : null}
    </div>
  );
}
