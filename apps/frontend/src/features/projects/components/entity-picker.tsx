import Image from "next/image";
import {
  COMPOSER_CATEGORIES,
  composerCategoryCounts,
  entityCategory,
  type ComposerCategory,
} from "../model/composer-context-catalog";
import type { ProjectEntity } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

function EntityVisual({ entity }: { entity: ProjectEntity }) {
  if (entity.icon) {
    return (
      <span aria-hidden="true" className={styles.entityIcon}>
        <ProjectIcon name={entity.icon} size={16} />
      </span>
    );
  }
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={entity.type === "contact" ? styles.entityAvatar : styles.entityLogo}
      height={24}
      src={entity.imagePath ?? "/logos/clue.svg"}
      width={24}
    />
  );
}

function Option({
  active,
  entity,
  onActiveChange,
  onSelect,
  selected,
}: {
  active: boolean;
  entity: ProjectEntity;
  onActiveChange?: (entityId: string) => void;
  onSelect: (entityId: string) => void;
  selected: boolean;
}) {
  return (
    <button
      aria-selected={selected}
      className={styles.entityOption}
      data-active={active ? "true" : "false"}
      onMouseDown={(event) => event.preventDefault()}
      onMouseEnter={() => onActiveChange?.(entity.id)}
      onClick={() => onSelect(entity.id)}
      role="option"
      type="button"
    >
      <EntityVisual entity={entity} />
      <span>
        <strong>{entity.label}</strong>
        <small>
          {entity.secondaryLabel}
          {entity.accountName ? ` | ${entity.accountName}` : ""}
        </small>
      </span>
      {selected ? <ProjectIcon name="status-check" size={14} /> : null}
    </button>
  );
}

export function EntityPicker({
  activeCategory,
  activeId,
  catalog,
  categoriesEnabled,
  category,
  onActiveChange,
  onBack,
  onOpenCategory,
  onSelect,
  query,
  results,
  selectedIds,
}: {
  activeCategory?: ComposerCategory;
  activeId?: string;
  catalog: ProjectEntity[];
  categoriesEnabled: boolean;
  category: ComposerCategory | null;
  onActiveChange?: (entityId: string) => void;
  onBack: () => void;
  onOpenCategory: (category: ComposerCategory) => void;
  onSelect: (entityId: string) => void;
  query: string;
  selectedIds: string[];
  results: ProjectEntity[];
}) {
  const searching = query.trim().length > 0;
  const counts = composerCategoryCounts(catalog);

  if (categoriesEnabled && !searching && category === null) {
    return (
      <div aria-label="Choose context" className={styles.entityPicker} role="listbox">
        {COMPOSER_CATEGORIES.map((item) => (
          <button
            className={styles.pickerCategory}
            data-active={activeCategory === item.key ? "true" : "false"}
            key={item.key}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onOpenCategory(item.key)}
            role="option"
            aria-selected={false}
            type="button"
          >
            <span>{item.label}</span>
            <small>{counts[item.key]}</small>
            <ProjectIcon name="chevron-right" size={14} />
          </button>
        ))}
      </div>
    );
  }

  const groups = searching
    ? COMPOSER_CATEGORIES.filter((item) => results.some((e) => entityCategory(e) === item.key))
    : COMPOSER_CATEGORIES.filter((item) => item.key === (category ?? "accounts"));
  const emptyCopy = searching
    ? "No matches"
    : COMPOSER_CATEGORIES.find((item) => item.key === (category ?? "accounts"))?.empty;

  return (
    <div aria-label="Choose context" className={styles.entityPicker} role="listbox">
      {categoriesEnabled && !searching && category !== null ? (
        <button
          className={styles.pickerBack}
          onMouseDown={(event) => event.preventDefault()}
          onClick={onBack}
          type="button"
        >
          <ProjectIcon name="chevron-right" size={14} />
          Back
        </button>
      ) : null}
      {groups.map((item) => (
        <section key={item.key}>
          {searching || !categoriesEnabled ? (
            <p className={styles.pickerLabel}>
              {categoriesEnabled ? item.label : "Accounts"}
            </p>
          ) : null}
          {results
            .filter((entity) => entityCategory(entity) === item.key)
            .map((entity) => (
              <Option
                active={activeId === entity.id}
                entity={entity}
                key={entity.id}
                onActiveChange={onActiveChange}
                onSelect={onSelect}
                selected={selectedIds.includes(entity.id)}
              />
            ))}
        </section>
      ))}
      {results.length === 0 ? <p className={styles.entityPickerEmpty}>{emptyCopy}</p> : null}
    </div>
  );
}
