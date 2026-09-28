import Image from "next/image";
import { useEffect, useRef } from "react";
import {
  COMPOSER_CATEGORIES,
  composerCategoryCounts,
  entityCategory,
  type ComposerCategory,
} from "../model/composer-context-catalog";
import { ContactAvatar } from "@/features/accounts/components/contact-avatar";
import type { ProjectEntity } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

function EntityVisual({ entity }: { entity: ProjectEntity }) {
  if (entity.icon) {
    return (
      <span aria-hidden="true" className={styles.entityIcon}>
        <ProjectIcon name={entity.icon} size={16} />
      </span>
    );
  }
  if (entity.type === "contact") {
    // A contact has no stored image; the avatar draws the name's initials (and an image if
    // one is ever served).
    return (
      <ContactAvatar
        className={styles.entityAvatar}
        name={entity.label}
        size={24}
        src={entity.imagePath}
      />
    );
  }
  // The account's mark: the same logo the accounts screens show (the platform's logo route
  // or Brandfetch's embed-only Logo API URL), else the building glyph. The optimizer is off
  // for a served logo for the reason the accounts table gives: the route is session-bound and
  // the CDN refuses programmatic fetches.
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={styles.entityLogo}
      height={24}
      src={entity.imagePath ?? ACCOUNT_GLYPH_PATH}
      unoptimized={entity.imagePath != null}
      width={24}
    />
  );
}

function Option({
  active,
  contactCount = 0,
  entity,
  expanded = false,
  nested = false,
  onActiveChange,
  onSelect,
  onToggle,
  selected,
}: {
  active: boolean;
  /** Discovered contacts under this account row; 0 draws no fold control. */
  contactCount?: number;
  entity: ProjectEntity;
  expanded?: boolean;
  /** A contact row drawn beneath its account. */
  nested?: boolean;
  onActiveChange?: (entityId: string) => void;
  onSelect: (entityId: string) => void;
  onToggle?: (entityId: string) => void;
  selected: boolean;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  // The listbox scrolls (max-height + overflow-y) but the active row is chosen by index, so
  // arrowing past the fold would move the highlight out of sight. "nearest" only scrolls when
  // the row is actually clipped, so a hover-activated row never jumps the list.
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <div className={styles.entityRow} data-nested={nested ? "true" : "false"}>
      <button
        aria-selected={selected}
        className={styles.entityOption}
        data-active={active ? "true" : "false"}
        ref={ref}
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
            {!nested && entity.accountName ? ` | ${entity.accountName}` : ""}
          </small>
        </span>
        {selected ? <ProjectIcon name="status-check" size={14} /> : null}
      </button>
      {contactCount > 0 && onToggle ? (
        // The fold control is its own button beside the row: clicking the row tags the
        // account, clicking the chevron only shows or hides its contacts.
        <button
          aria-expanded={expanded}
          aria-label={
            expanded
              ? `Hide ${contactCount} contacts of ${entity.label}`
              : `Show ${contactCount} contacts of ${entity.label}`
          }
          className={styles.entityExpand}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onToggle(entity.id)}
          type="button"
        >
          <small>{contactCount}</small>
          <span className={styles.entityExpandChevron}>
            <ProjectIcon name="chevron-right" size={14} />
          </span>
        </button>
      ) : null}
    </div>
  );
}

export function EntityPicker({
  activeCategory,
  activeId,
  catalog,
  categoriesEnabled,
  category,
  contactCounts,
  expandedAccountIds,
  onActiveChange,
  onBack,
  onOpenCategory,
  onSelect,
  onToggleAccount,
  query,
  results,
  selectedIds,
}: {
  activeCategory?: ComposerCategory;
  activeId?: string;
  catalog: ProjectEntity[];
  categoriesEnabled: boolean;
  category: ComposerCategory | null;
  /** Discovered contacts per account id — what draws an account's fold control. */
  contactCounts: ReadonlyMap<string, number>;
  expandedAccountIds: ReadonlySet<string>;
  onActiveChange?: (entityId: string) => void;
  onBack: () => void;
  onOpenCategory: (category: ComposerCategory) => void;
  onSelect: (entityId: string) => void;
  onToggleAccount: (accountId: string) => void;
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
                // The tree only exists while browsing: search results stay flat, with a
                // contact's account named beside its title instead.
                contactCount={
                  searching || entity.type !== "account"
                    ? 0
                    : contactCounts.get(entity.id)
                }
                entity={entity}
                expanded={expandedAccountIds.has(entity.id)}
                key={entity.id}
                nested={!searching && entity.type === "contact" && !!entity.accountId}
                onActiveChange={onActiveChange}
                onSelect={onSelect}
                onToggle={searching ? undefined : onToggleAccount}
                selected={selectedIds.includes(entity.id)}
              />
            ))}
        </section>
      ))}
      {results.length === 0 ? <p className={styles.entityPickerEmpty}>{emptyCopy}</p> : null}
    </div>
  );
}
