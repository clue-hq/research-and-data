import { useEffect, useRef } from "react";
import { Dialog } from "@base-ui/react/dialog";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { ASSET_UPLOAD_ACCEPT, CreativeTypeSchema, UsageRoleSchema, assetLabel, type CreativeType, type UsageRole } from "../model/asset-context";
import styles from "./brand-context.module.css";

function UploadPreview({file}: {file: File}) {
  const image = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    if (image.current) image.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);
  // eslint-disable-next-line @next/next/no-img-element
  return <img ref={image} alt="" className={styles.uploadPreview} />;
}

export function AssetUploadDialog({controller}: {controller: BrandContextController}) {
  const library = controller.assetLibrary;
  return <Dialog.Root open={library.open} onOpenChange={library.setOpen}>
    <Dialog.Portal>
      <Dialog.Backdrop className={styles.dialogBackdrop} />
      <Dialog.Popup className={styles.uploadDialog}>
        <div className={styles.dialogTitleRow}>
          <Dialog.Title>Upload assets</Dialog.Title>
          <Dialog.Close className={styles.secondaryButton}>Close</Dialog.Close>
        </div>
        <Dialog.Description>PNG, JPEG, WebP, SVG and GIF. Originals are retained; animated images are described from their first frame. You can close this window while uploads continue. {library.limits ? `Maximum file size: ${(library.limits.max_bytes / 1024 / 1024).toLocaleString()} MB.` : "Loading upload limits…"}</Dialog.Description>
        <label className={styles.uploadDropzone} onDragOver={event => event.preventDefault()} onDrop={event => {event.preventDefault(); if (!library.limits) return; library.queue.add(Array.from(event.dataTransfer.files));}}>
          Drop files here or choose files
          <input aria-label="Choose asset files" disabled={!library.limits} type="file" accept={ASSET_UPLOAD_ACCEPT} multiple onChange={event => {library.queue.add(Array.from(event.target.files ?? [])); event.target.value = "";}} />
        </label>
        <div className={styles.assetFilterRow}>
          <label>Type for selected files <select aria-label="Bulk asset type" defaultValue="" onChange={event => library.queue.editAll({creative_type: (event.target.value || undefined) as CreativeType | undefined})}>
            <option value="">Let analysis suggest</option>{CreativeTypeSchema.options.map(value => <option key={value} value={value}>{assetLabel(value)}</option>)}
          </select></label>
          <label>Used as <select aria-label="Bulk usage role" defaultValue="" onChange={event => library.queue.editAll({usage_roles: event.target.value ? [event.target.value as UsageRole] : undefined})}>
            <option value="">Let analysis suggest</option>{UsageRoleSchema.options.map(value => <option key={value} value={value}>{assetLabel(value)}</option>)}
          </select></label>
        </div>
        <div className={styles.uploadRows} aria-live="polite">
          {library.uploads.map(row => <div className={styles.uploadRow} key={row.id}>
            <div className={styles.assetFilterRow}>
              <input type="checkbox" aria-label={`Select ${row.name}`} checked={row.selected} disabled={row.state !== "selected"} onChange={event => library.queue.select(row.id, event.target.checked)} />
              <UploadPreview file={row.file} />
              <div><strong>{row.name}</strong><div>{row.file.type || row.name.split(".").pop()?.toUpperCase()} · {(row.file.size / 1024).toFixed(1)} KB</div></div>
            </div>
            <div className={styles.assetFilterRow}>
              <select aria-label={`Type for ${row.name}`} disabled={row.state !== "selected"} value={row.overrides.creative_type ?? ""} onChange={event => library.queue.edit(row.id, {creative_type: (event.target.value || undefined) as CreativeType | undefined})}>
                <option value="">Suggest type</option>{CreativeTypeSchema.options.map(value => <option key={value} value={value}>{assetLabel(value)}</option>)}
              </select>
              <select aria-label={`Usage for ${row.name}`} disabled={row.state !== "selected"} value={row.overrides.usage_roles?.[0] ?? ""} onChange={event => library.queue.edit(row.id, {usage_roles: event.target.value ? [event.target.value as UsageRole] : undefined})}>
                <option value="">Suggest usage</option>{UsageRoleSchema.options.map(value => <option key={value} value={value}>{assetLabel(value)}</option>)}
              </select>
              <input aria-label={`Note for ${row.name}`} maxLength={4000} placeholder="Optional context" disabled={row.state !== "selected"} value={row.overrides.user_note ?? ""} onChange={event => library.queue.edit(row.id, {user_note: event.target.value})} />
            </div>
            <span>{row.state === "uploaded" ? `Uploaded · ${assetLabel(row.context?.status ?? "queued")}` : assetLabel(row.state)}</span>
            {row.error ? <span role="alert">{row.error}</span> : null}
            {row.context?.diagnostic ? <span>{row.context.diagnostic.message}</span> : null}
            {row.state === "failed" && row.retryable ? <button type="button" className={styles.secondaryButton} onClick={() => library.queue.retry(row.id)}>Retry upload</button> : null}
            {row.assetId && ["failed", "unsupported"].includes(row.context?.status ?? "") ? <button type="button" className={styles.secondaryButton} onClick={() => library.retry(row.assetId!)}>Retry analysis</button> : null}
          </div>)}
        </div>
        <div className={styles.assetFilterRow}>
          <span>{library.uploads.filter(row => row.state === "uploaded").length} / {library.uploads.length} uploaded</span>
          <button type="button" className={styles.primaryButton} disabled={!library.limits || !library.uploads.some(row => row.state === "selected" && row.selected)} onClick={() => library.queue.start()}>Upload selected files</button>
        </div>
        {library.error ? <p role="alert">{library.error}</p> : null}
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}
