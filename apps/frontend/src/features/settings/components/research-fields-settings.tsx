"use client";
import { Menu } from "@base-ui/react/menu";
import { Archive, Ellipsis, LockKeyhole, Pencil, Plus, TextCursorInput, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useResearchFields, useResearchFieldRow } from "../hooks/use-research-fields";
import type { ResearchFieldsController } from "../hooks/research-fields-controller";
import { researchFieldCreatedLabel, type ResearchField, type ResearchFields } from "../model/research-fields";
import { SettingsInput } from "./settings-primitives";
import settings from "./settings.module.css";
import styles from "./research-fields.module.css";

function ResearchFieldRow({ row, controller, canManage, pending }: {
  row: ResearchField;
  controller: ResearchFieldsController;
  canManage: boolean;
  pending: boolean;
}) {
  const { menuTriggerRef, ...edit } = useResearchFieldRow(row, controller);
  const created = researchFieldCreatedLabel(row.created_at);
  return (
    <tr aria-busy={pending}>
      <td>
        {edit.editing === "label" ? (
          <>
            <SettingsInput ariaLabel={`Name for ${row.label}`} autoFocus maxLength={200} {...edit.label} />
            <p className={styles.help}>{edit.label.readOnly ? "Saving…" : "Enter to save · Esc to cancel"}</p>
          </>
        ) : <span className={styles.fieldName}>{row.label}</span>}
        <span className={styles.origin}>
          {row.origin === "platform" ? <><LockKeyhole size={12} aria-hidden="true" />Platform</> : "Workspace"}
        </span>
        {row.origin === "workspace" ? (
          <span className={styles.creator}>
            {row.created_by ? `Added by ${row.created_by}` : "Workspace member"}
            {created ? <> · <time dateTime={row.created_at ?? undefined}>{created}</time></> : null}
          </span>
        ) : null}
      </td>
      <td>
        {edit.editing === "description" ? (
          <>
            <textarea aria-label={`Description for ${row.label}`} className={settings.textarea} autoFocus rows={4} maxLength={2000} {...edit.description} />
            <p className={styles.help}>{edit.description.readOnly ? "Saving…" : "Saves on blur · ⌘/Ctrl+Enter · Esc to cancel"}</p>
          </>
        ) : <span className={styles.description}>{row.description || "—"}</span>}
      </td>
      <td>
        {canManage && row.origin === "workspace" ? (
          <Menu.Root open={edit.menuOpen} onOpenChange={edit.onMenuOpenChange}>
            <Menu.Trigger ref={menuTriggerRef} className={settings.iconButton} aria-label={`More actions for ${row.label}`} disabled={pending}>
              <Ellipsis size={16} strokeWidth={1.4} />
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Positioner sideOffset={4} align="end">
                <Menu.Popup className={`${settings.memberMenu} ${styles.rowMenu}`} finalFocus={edit.editing ? false : undefined}>
                  {edit.confirmRetire ? (
                    <>
                      <p className={styles.retireNote}>Retiring removes this field from research and tables. Existing evidence stays available. This cannot be undone; the field key stays reserved.</p>
                      <Menu.Item closeOnClick={false} className={styles.danger} disabled={pending} onClick={() => void edit.retire()}>
                        <Archive size={14} />{pending ? "Retiring…" : "Confirm retire"}
                      </Menu.Item>
                      <Menu.Item disabled={pending}>Cancel</Menu.Item>
                    </>
                  ) : (
                    <>
                      <Menu.Item onClick={() => edit.edit("label")}><Pencil size={14} />Edit name</Menu.Item>
                      <Menu.Item onClick={() => edit.edit("description")}><TextCursorInput size={14} />Edit description</Menu.Item>
                      <Menu.Item closeOnClick={false} className={styles.danger} onClick={edit.confirm}><Archive size={14} />Retire</Menu.Item>
                    </>
                  )}
                </Menu.Popup>
              </Menu.Positioner>
            </Menu.Portal>
          </Menu.Root>
        ) : null}
      </td>
    </tr>
  );
}

export function ResearchFieldsSettings({ fields, canManage }: { fields: ResearchFields; canManage: boolean }) {
  const { createButtonRef, ...state } = useResearchFields(fields, canManage);
  const nameError = state.createError?.field === "label";
  const descriptionError = state.createError?.field === "description";
  return (
    <div className={styles.stack}>
      <p className={styles.lead}>Define what research should find about your {fields.entity}.</p>
      <div className={styles.toolbar}>
        <span className={styles.count}>{state.rows.length} {state.rows.length === 1 ? "field" : "fields"}</span>
        {canManage ? <Button ref={createButtonRef} type="button" size="md" variant="secondary" onClick={state.openCreate} disabled={state.creating}><Plus size={14} />Create field</Button> : null}
      </div>
      {canManage && state.showCreate ? (
        <form className={styles.createForm} onSubmit={state.submit} aria-label="Create research field" aria-busy={state.creating}>
          <div className={styles.formHeading}>
            <h2>Create field</h2>
            <button type="button" className={settings.iconButton} aria-label="Close create field" onClick={state.closeCreate} disabled={state.creating}><X size={16} /></button>
          </div>
          <label className={styles.label} htmlFor="research-field-name">Name <span aria-hidden="true">*</span></label>
          <SettingsInput id="research-field-name" ariaLabel="Name" autoFocus required maxLength={200} value={state.label} onChange={event => state.setLabel(event.target.value)} readOnly={state.creating} placeholder="e.g. Uses Salesforce" aria-invalid={nameError || undefined} aria-describedby={nameError ? "research-field-name-error" : undefined} />
          {nameError ? <p id="research-field-name-error" className={styles.error} role="alert">{state.createError?.message}</p> : null}
          <label className={styles.label} htmlFor="research-field-description">Description <span aria-hidden="true">*</span></label>
          <textarea id="research-field-description" aria-label="Description" className={settings.textarea} required rows={4} maxLength={2000} value={state.description} onChange={event => state.setDescription(event.target.value)} readOnly={state.creating} placeholder="Find whether the account uses Salesforce as its CRM. Cite a job posting, customer story or integration page as evidence." aria-invalid={descriptionError || undefined} aria-describedby={descriptionError ? "research-field-description-error" : "research-field-help"} />
          {descriptionError ? <p id="research-field-description-error" className={styles.error} role="alert">{state.createError?.message}</p> : null}
          <p id="research-field-help" className={styles.help}>Tell research what to find and what counts as evidence. Used on future research runs.</p>
          {state.createError && !state.createError.field ? <p className={styles.error} role="alert">{state.createError.message}</p> : null}
          <div className={styles.formActions}>
            <Button type="button" size="md" variant="transparent" disabled={state.creating} onClick={state.closeCreate}>Cancel</Button>
            <Button type="submit" size="md" variant="primary" disabled={state.creating || !state.label.trim() || !state.description.trim()}>{state.creating ? "Creating…" : "Create field"}</Button>
          </div>
        </form>
      ) : null}
      <div className={styles.tableFrame}>
        <table className={styles.table}>
          <thead><tr><th scope="col">Name</th><th scope="col">Description</th><th scope="col" aria-label="Actions" /></tr></thead>
          <tbody>
            {state.rows.map(row => <ResearchFieldRow key={row.key} row={row} controller={state.controller} canManage={canManage} pending={state.controller.isPending(row.key)} />)}
          </tbody>
        </table>
        {state.rows.length === 0 ? <p className={styles.empty}>No research fields yet.</p> : null}
      </div>
    </div>
  );
}
