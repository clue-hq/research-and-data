import Image from "next/image";
import type { ProjectEntity } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function EntityPicker({
  activeId,
  entities,
  onActiveChange,
  onQueryChange,
  onSelect,
  query,
  selectedIds,
  showSearch = true,
}: {
  activeId?: string;
  entities: ProjectEntity[];
  onActiveChange?: (entityId: string) => void;
  onQueryChange?: (value: string) => void;
  onSelect: (entityId: string) => void;
  query?: string;
  selectedIds: string[];
  showSearch?: boolean;
}) {
  const hasAccounts = entities.some((entity) => entity.type === "account");
  const hasContacts = entities.some((entity) => entity.type === "contact");

  return (
    <div
      aria-label="Choose account or contact"
      className={styles.entityPicker}
      role="listbox"
    >
      {showSearch ? (
        <label className={styles.pickerSearch}>
          <ProjectIcon name="search" size={14} />
          <input
            autoFocus
            onChange={(event) => onQueryChange?.(event.target.value)}
            placeholder="Search accounts and contacts"
            type="search"
            value={query ?? ""}
          />
        </label>
      ) : null}
      {(["account", "contact"] as const).map((type) => {
        const typeHasResults = type === "account" ? hasAccounts : hasContacts;
        if (!typeHasResults) return null;
        return (
          <section key={type}>
            <p className={styles.pickerLabel}>
              {type === "account" ? "Account" : "Contacts"}
            </p>
            {entities
              .filter((entity) => entity.type === type)
              .map((entity) => (
                <button
                  aria-selected={selectedIds.includes(entity.id)}
                  className={styles.entityOption}
                  data-active={activeId === entity.id ? "true" : "false"}
                  key={entity.id}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => onActiveChange?.(entity.id)}
                  onClick={() => onSelect(entity.id)}
                  role="option"
                  type="button"
                >
                  <Image
                    alt=""
                    aria-hidden="true"
                    className={
                      type === "contact" ? styles.entityAvatar : styles.entityLogo
                    }
                    height={24}
                    src={entity.imagePath ?? "/logos/clue.svg"}
                    width={24}
                  />
                  <span>
                    <strong>{entity.label}</strong>
                    <small>
                      {entity.secondaryLabel}
                      {entity.accountName ? ` | ${entity.accountName}` : ""}
                    </small>
                  </span>
                  {selectedIds.includes(entity.id) ? (
                    <ProjectIcon name="status-check" size={14} />
                  ) : null}
                </button>
              ))}
          </section>
        );
      })}
      {!hasAccounts && !hasContacts ? (
        <p className={styles.entityPickerEmpty}>No matching accounts or contacts</p>
      ) : null}
    </div>
  );
}
