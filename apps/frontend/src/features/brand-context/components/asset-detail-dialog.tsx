import { Dialog } from "@base-ui/react/dialog";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { AssetContextDetails } from "./asset-context-details";
import { BrandContextIcon } from "./brand-context-icon";
import styles from "./brand-context.module.css";

export function AssetDetailDialog({ controller }: { controller: BrandContextController }) {
  const asset = controller.selectedAsset;
  if (!asset || !controller.assetDraft) return null;
  const library = controller.assetLibrary;
  const edits = library.editStates[asset.id];
  const pending = Boolean(edits && Object.keys(edits.patch).length);
  const finishEditing = () => {
    controller.flushAssetDraft();
    controller.setAssetEditingField(null);
  };
  return <Dialog.Root open onOpenChange={open => { if (!open) void controller.closeAsset(); }}>
    <Dialog.Portal>
      <Dialog.Backdrop className={styles.dialogBackdrop} />
      <Dialog.Popup aria-label={`${asset.name} details`} className={`${styles.assetDialog} clue-panel-enter`}>
        <div className={styles.assetDialogPreview} style={asset.visual.kind === "gradient" ? {background: `linear-gradient(135deg, ${asset.visual.colors.join(", ")})`} : undefined}>
          {asset.visual.kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img alt={asset.name} data-vector={asset.type === "SVG" || undefined} src={asset.visual.imagePath} />
          ) : null}
        </div>
        <div className={styles.assetDialogDetails}>
          <header className={styles.assetDetailsHeader}>
            <Dialog.Title>Details</Dialog.Title>
            <span className={styles.assetSaveStatus} role="status" aria-live="polite">
              {edits?.error ? "Not saved" : pending || edits?.saving ? "Saving…" : edits?.saved ? "Saved" : ""}
            </span>
            <Dialog.Close aria-label="Close asset details" className={styles.iconButton}>
              <BrandContextIcon name="close" size={16} />
            </Dialog.Close>
          </header>
          {edits?.error ? <div className={styles.assetSaveError} role="alert">
            <p>Couldn’t save your changes. {edits.error}</p>
            <button className={styles.secondaryButton} type="button" onClick={() => void library.edits.flush(asset.id)}>Retry</button>
          </div> : null}
          <div className={styles.assetDetailsBody}>
            {(["name", "description"] as const).map(field => {
              const label = field === "name" ? "Title" : "Description";
              const id = `asset-${field}`;
              const editing = controller.assetEditingField === field;
              return <div className={styles.assetDetailField} key={field}>
                <div className={styles.detailFieldLabel}>
                  {editing ? <label htmlFor={id}>{label}</label> : <h3>{label}</h3>}
                  {library.canWrite ? <button aria-label={`Edit ${label.toLowerCase()}`} className={styles.fieldEditButton} onClick={() => controller.setAssetEditingField(field)} type="button"><BrandContextIcon name="edit" size={14} /></button> : null}
                </div>
                {editing ? field === "name" ? <input autoFocus id={id} maxLength={120} value={controller.assetDraft![field]}
                  onChange={event => controller.setAssetDraft(field, event.target.value)} onBlur={finishEditing}
                  onKeyDown={event => {if (event.key === "Enter") {event.preventDefault(); finishEditing();}}} />
                  : <textarea autoFocus id={id} maxLength={12000} rows={6} value={controller.assetDraft![field]}
                    onChange={event => controller.setAssetDraft(field, event.target.value)} onBlur={finishEditing} />
                  : <p>{controller.assetDraft![field] || (field === "name" ? "Untitled asset" : "No description yet.")}</p>}
              </div>;
            })}
            <AssetContextDetails asset={asset} controller={controller} />
            <dl className={styles.assetFacts}>
              <div><dt>Size</dt><dd>{asset.sizeLabel}</dd></div>
              <div><dt>Dimensions</dt><dd>{asset.dimensions}</dd></div>
            </dl>
          </div>
        </div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}
