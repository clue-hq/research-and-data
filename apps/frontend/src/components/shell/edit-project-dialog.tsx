import { useRef } from "react";
import { Dialog } from "@base-ui/react/dialog";
import styles from "./project-sidebar-tree.module.css";
import { SidebarFigmaIcon } from "./sidebar-figma-icon";

interface EditProjectDialogProps {
  name: string;
  canSave: boolean;
  error: string | null;
  saving: boolean;
  onCancel: () => void;
  onChangeName: (name: string) => void;
  onRemove: () => void;
  onSave: () => void;
}

export function EditProjectDialog({
  name,
  canSave,
  error,
  saving,
  onCancel,
  onChangeName,
  onRemove,
  onSave,
}: EditProjectDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <Dialog.Root open onOpenChange={(open) => {
      if (!open) onCancel();
    }}>
      <Dialog.Portal>
        <div className={styles.dialogLayer}>
          <Dialog.Backdrop className={styles.dialogBackdrop} />
          <Dialog.Popup
            aria-busy={saving}
            className={styles.editDialog}
            initialFocus={inputRef}
            render={<form onSubmit={(event) => {
              event.preventDefault();
              onSave();
            }} />}
          >
            <div className={styles.dialogHeader}>
              <Dialog.Title render={<h2 />}>Edit project</Dialog.Title>
              <Dialog.Close
                aria-label="Close"
                disabled={saving}
                className={styles.dialogIconButton}
                type="button"
              >
                <SidebarFigmaIcon name="sidebar-close" />
              </Dialog.Close>
            </div>

            <label className={styles.projectNameField}>
              <span className="sr-only">Project name</span>
              <SidebarFigmaIcon name="sidebar-folder-closed" />
              <input
                ref={inputRef}
                aria-describedby={error ? "rename-project-error" : undefined}
                aria-invalid={Boolean(error)}
                disabled={saving}
                maxLength={200}
                required
                onChange={(event) => onChangeName(event.target.value)}
                value={name}
              />
            </label>

            {error ? (
              <p className={styles.renameError} id="rename-project-error" role="alert">
                {error}
              </p>
            ) : null}

            <div className={styles.dialogActions}>
              <button
                className={`${styles.dialogButton} ${styles.removeButton}`}
                onClick={onRemove}
                disabled={saving}
                type="button"
              >
                Archive project
              </button>
              <div className={styles.dialogActionsRight}>
                <button
                  className={`${styles.dialogButton} ${styles.cancelButton}`}
                  onClick={onCancel}
                  disabled={saving}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className={`${styles.dialogButton} ${styles.saveButton}`}
                  disabled={!canSave}
                  type="submit"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </Dialog.Popup>
        </div>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
