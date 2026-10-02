"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type {
  GallerySizeCategory,
} from "@/features/projects/model/project-workspace";
import { ProjectIcon } from "@/features/projects/components/project-icon";
import {
  COLLATERAL_TYPE_LABELS,
  SIZE_CATEGORY_LABELS,
  type GalleryDateRange,
  type GalleryGroupBy,
  type GalleryLayout,
  type GallerySort,
} from "../model/project-gallery";
import type { ProjectGalleryController } from "../hooks/use-project-gallery-controller";
import styles from "./project-gallery.module.css";

const SORT_OPTIONS: Array<{ label: string; value: GallerySort }> = [
  { label: "Last viewed", value: "last-viewed" },
  { label: "Last edited", value: "edited-desc" },
  { label: "Date · ascending", value: "edited-asc" },
  { label: "Name · A–Z", value: "name-asc" },
  { label: "Name · Z–A", value: "name-desc" },
];

const GROUP_OPTIONS: Array<{ label: string; value: GalleryGroupBy }> = [
  { label: "No grouping", value: "none" },
  { label: "Account", value: "account" },
  { label: "Collateral type", value: "type" },
];

const DATE_OPTIONS: Array<{ label: string; value: GalleryDateRange }> = [
  { label: "Any time", value: "all" },
  { label: "Today", value: "today" },
  { label: "Last 7 days", value: "last-7-days" },
  { label: "Last 30 days", value: "last-30-days" },
];

const SIZE_CATEGORIES = Object.keys(SIZE_CATEGORY_LABELS) as GallerySizeCategory[];

function MenuOption({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      aria-pressed={active}
      className={styles.menuOption}
      onClick={onClick}
      type="button"
    >
      <span>{children}</span>
      {active ? <ProjectIcon name="check" size={13} /> : <span aria-hidden="true" />}
    </button>
  );
}

function FilterCheck({
  checked,
  children,
  onChange,
}: {
  checked: boolean;
  children: React.ReactNode;
  onChange: () => void;
}) {
  return (
    <button
      aria-pressed={checked}
      className={styles.filterCheck}
      onClick={onChange}
      type="button"
    >
      <span aria-hidden="true" className={styles.checkbox} data-checked={checked}>
        {checked ? <ProjectIcon name="check" size={10} /> : null}
      </span>
      <span>{children}</span>
    </button>
  );
}

export function GalleryToolbar({
  controller,
  library = false,
}: {
  controller: ProjectGalleryController;
  library?: boolean;
}) {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [accountQuery, setAccountQuery] = useState("");
  // Cross-project grouping and sorting only mean something in the library; the
  // project gallery keeps exactly the options it had before.
  const groupOptions = library ? [...GROUP_OPTIONS, { label: "Project", value: "project" as const }] : GROUP_OPTIONS;
  const sortOptions = library
    ? [...SORT_OPTIONS,
       { label: "Account · A–Z", value: "account-asc" as const },
       { label: "Type · A–Z", value: "type-asc" as const },
       { label: "Project · A–Z", value: "project-asc" as const }]
    : SORT_OPTIONS;
  const sortLabel = sortOptions.find((option) => option.value === controller.sort)?.label;
  const normalizedAccountQuery = accountQuery.trim().toLocaleLowerCase();
  const selectedAccounts = controller.accounts.filter((account) =>
    controller.filters.accountIds.includes(account.id)
  );
  const accountSuggestions = normalizedAccountQuery
    ? controller.accounts
        .filter((account) =>
          !controller.filters.accountIds.includes(account.id)
          && account.name.toLocaleLowerCase().includes(normalizedAccountQuery)
        )
        .slice(0, 6)
    : [];

  useEffect(() => {
    if (!controller.openMenu) return;
    const close = (event: PointerEvent) => {
      if (!toolbarRef.current?.contains(event.target as Node)) controller.setOpenMenu(null);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") controller.setOpenMenu(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [controller]);

  return (
    <header className={styles.toolbar} ref={toolbarRef}>
      <div className={styles.toolbarActions}>
        <div className={styles.menuRoot}>
          <button
            aria-expanded={controller.openMenu === "sort"}
            className={styles.toolbarButton}
            onClick={() => controller.setOpenMenu(controller.openMenu === "sort" ? null : "sort")}
            type="button"
          >
            {sortLabel}<ProjectIcon name="chevron-down" size={12} />
          </button>
          {controller.openMenu === "sort" ? (
            <div aria-label="Sort artifacts" className={styles.compactMenu} role="menu">
              {sortOptions.map((option) => (
                <MenuOption
                  active={controller.sort === option.value}
                  key={option.value}
                  onClick={() => {
                    controller.setSort(option.value);
                    controller.setOpenMenu(null);
                  }}
                >
                  {option.label}
                </MenuOption>
              ))}
            </div>
          ) : null}
        </div>

        <div className={styles.menuRoot}>
          <button
            aria-expanded={controller.openMenu === "group"}
            className={styles.toolbarButton}
            onClick={() => controller.setOpenMenu(controller.openMenu === "group" ? null : "group")}
            type="button"
          >
            {controller.groupBy === "none" ? "Group by" : `Group: ${groupOptions.find((option) => option.value === controller.groupBy)?.label}`}
            <ProjectIcon name="chevron-down" size={12} />
          </button>
          {controller.openMenu === "group" ? (
            <div aria-label="Group artifacts" className={styles.compactMenu} role="menu">
              {groupOptions.map((option) => (
                <MenuOption
                  active={controller.groupBy === option.value}
                  key={option.value}
                  onClick={() => {
                    controller.setGroupBy(option.value);
                    controller.setOpenMenu(null);
                  }}
                >
                  {option.label}
                </MenuOption>
              ))}
            </div>
          ) : null}
        </div>

        <div className={styles.menuRoot}>
          <button
            aria-expanded={controller.openMenu === "filter"}
            className={styles.toolbarButton}
            data-active={controller.activeFilterCount > 0}
            onClick={() => controller.setOpenMenu(controller.openMenu === "filter" ? null : "filter")}
            type="button"
          >
            Filter
            {controller.activeFilterCount > 0 ? (
              <span className={styles.filterCount}>{controller.activeFilterCount}</span>
            ) : null}
            <ProjectIcon name="chevron-down" size={12} />
          </button>
          {controller.openMenu === "filter" ? (
            <div aria-label="Filter artifacts" className={styles.filterMenu}>
              <div className={styles.filterMenuHeader}>
                <strong>Filter</strong>
                <button
                  onClick={() => {
                    controller.resetFilters();
                    setAccountQuery("");
                  }}
                  type="button"
                >
                  Clear all
                </button>
              </div>
              {library ? (
                <section className={styles.accountFilterSection}>
                  <h3>Project</h3>
                  {controller.projects.map((project) => (
                    <FilterCheck
                      checked={controller.filters.projectIds?.includes(project.id) ?? false}
                      key={project.id}
                      onChange={() => controller.toggleProject(project.id)}
                    >
                      {project.title}
                    </FilterCheck>
                  ))}
                </section>
              ) : null}
              <section className={styles.accountFilterSection}>
                <h3>Account</h3>
                {selectedAccounts.length > 0 ? (
                  <div aria-label="Selected accounts" className={styles.selectedAccounts}>
                    {selectedAccounts.map((account) => (
                      <button
                        aria-label={`Remove ${account.name} filter`}
                        className={styles.accountChip}
                        key={account.id}
                        onClick={() => controller.toggleAccount(account.id)}
                        type="button"
                      >
                        {account.logoPath ? (
                          <Image alt="" height={14} src={account.logoPath} unoptimized width={14} />
                        ) : null}
                        <span>{account.name}</span>
                        <ProjectIcon name="close" size={10} />
                      </button>
                    ))}
                  </div>
                ) : null}
                <label className={styles.accountSearchField}>
                  <ProjectIcon name="search" size={13} />
                  <input
                    aria-label="Find an account"
                    autoComplete="off"
                    onChange={(event) => setAccountQuery(event.target.value)}
                    placeholder="Type an account name"
                    type="search"
                    value={accountQuery}
                  />
                </label>
                {normalizedAccountQuery ? (
                  <div aria-label="Matching accounts" className={styles.accountSuggestions} role="listbox">
                    {accountSuggestions.length > 0 ? accountSuggestions.map((account) => (
                      <button
                        aria-selected="false"
                        className={styles.accountSuggestion}
                        key={account.id}
                        onClick={() => {
                          controller.toggleAccount(account.id);
                          setAccountQuery("");
                        }}
                        role="option"
                        type="button"
                      >
                        {account.logoPath ? (
                          <Image alt="" height={16} src={account.logoPath} unoptimized width={16} />
                        ) : null}
                        <span>{account.name}</span>
                      </button>
                    )) : (
                      <span className={styles.accountEmpty}>No matching accounts</span>
                    )}
                  </div>
                ) : (
                  <span className={styles.accountHint}>Search instead of browsing a long account list.</span>
                )}
              </section>
              <section>
                <h3>Collateral type</h3>
                {controller.typeOptions.map((type) => (
                  <FilterCheck
                    checked={controller.filters.collateralTypes.includes(type)}
                    key={type}
                    onChange={() => controller.toggleCollateralType(type)}
                  >
                    {COLLATERAL_TYPE_LABELS[type]}
                  </FilterCheck>
                ))}
              </section>
              <section>
                <h3>Date</h3>
                {DATE_OPTIONS.map((option) => (
                  <MenuOption
                    active={controller.filters.dateRange === option.value}
                    key={option.value}
                    onClick={() => controller.setDateRange(option.value)}
                  >
                    {option.label}
                  </MenuOption>
                ))}
              </section>
              <section>
                <h3>Size</h3>
                {SIZE_CATEGORIES.map((category) => (
                  <FilterCheck
                    checked={controller.filters.sizeCategories.includes(category)}
                    key={category}
                    onChange={() => controller.toggleSizeCategory(category)}
                  >
                    {SIZE_CATEGORY_LABELS[category]}
                  </FilterCheck>
                ))}
              </section>
            </div>
          ) : null}
        </div>

      </div>
      <div className={styles.toolbarUtility}>
        <span aria-label="Gallery layout" className={styles.layoutToggle} role="group">
          {(["grid", "list"] as GalleryLayout[]).map((layout) => (
            <button
              aria-label={`${layout === "grid" ? "Grid" : "List"} view`}
              aria-pressed={controller.layout === layout}
              key={layout}
              onClick={() => controller.setLayout(layout)}
              type="button"
            >
              <ProjectIcon name={layout} size={14} />
            </button>
          ))}
        </span>
        <label className={styles.searchField}>
          <ProjectIcon name="search" size={14} />
          <input
            aria-label={library ? "Search all artifacts" : "Search project artifacts"}
            onChange={(event) => controller.setQuery(event.target.value)}
            placeholder="Search"
            type="search"
            value={controller.query}
          />
        </label>
      </div>
    </header>
  );
}
