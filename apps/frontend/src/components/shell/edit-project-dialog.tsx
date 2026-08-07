import styles from "./project-sidebar-tree.module.css";
import { SidebarFigmaIcon } from "./sidebar-figma-icon";

interface EditProjectDialogProps {
  name: string;
  onCancel: () => void;
  onChangeName: (name: string) => void;
  onRemove: () => void;
  onSave: () => void;
}

export function EditProjectDialog({
  name,
  onCancel,
  onChangeName,
  onRemove,
  onSave,
}: EditProjectDialogProps) {
  return (
    <div className={styles.dialogLayer}>
      <button
        aria-label="Close edit project dialog"
        className={styles.dialogBackdrop}
        onClick={onCancel}
        type="button"
      />
      <form
        aria-labelledby="edit-project-title"
        aria-modal="true"
        className={styles.editDialog}
        onSubmit={(event) => {
          event.preventDefault();
          onSave();
        }}
        role="dialog"
      >
        <div className={styles.dialogHeader}>
          <h2 id="edit-project-title">Edit project</h2>
          <button
            aria-label="Close"
            className={styles.dialogIconButton}
            onClick={onCancel}
            type="button"
          >
            <SidebarFigmaIcon name="sidebar-close" />
          </button>
        </div>

        <label className={styles.projectNameField}>
          <span className="sr-only">Project name</span>
          <SidebarFigmaIcon name="sidebar-folder-closed" />
          <input
            autoFocus
            onChange={(event) => onChangeName(event.target.value)}
            value={name}
          />
        </label>

        <div className={styles.dialogActions}>
          <button
            className={`${styles.dialogButton} ${styles.removeButton}`}
            onClick={onRemove}
            type="button"
          >
            Remove project
          </button>
          <div className={styles.dialogActionsRight}>
            <button
              className={`${styles.dialogButton} ${styles.cancelButton}`}
              onClick={onCancel}
              type="button"
            >
              Cancel
            </button>
            <button
              className={`${styles.dialogButton} ${styles.saveButton}`}
              disabled={!name.trim()}
              type="submit"
            >
              Save
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
