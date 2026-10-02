"use client";

import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { DesignIcon } from "@/components/ui/design-icon";
import {
  useAccountsSortController,
  useAccountsToolbarController,
} from "../hooks/use-accounts-toolbar-controller";
import type { AccountProject } from "../model/account";
import type { AccountFilterRule } from "../model/account-query";
import type {
  AccountColumnDefinition,
  AccountColumnKey,
  AccountColumnVisibility,
  AccountSort,
  AccountTableDensity,
} from "../model/account-table-view";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import toolbarStyles from "./accounts-toolbar.module.css";
import { AccountColumnIcon } from "./account-column-icon";
import {
  AccountsFilterPanel,
  type AccountFilterOption,
} from "./accounts-filter-panel";
import { TableDensitySelector } from "./table-density-selector";

interface AccountsToolbarProps {
  embedded?: boolean;
  onAddAccounts?: () => void;
  columnDefinitions: AccountColumnDefinition[];
  columnOrder: AccountColumnKey[];
  density: AccountTableDensity;
  filters: AccountFilterRule[];
  onColumnMove: (column: AccountColumnKey, direction: -1 | 1) => void;
  onColumnReorder: (
    source: AccountColumnKey,
    target: AccountColumnKey,
  ) => void;
  onColumnToggle: (column: AccountColumnKey) => void;
  onCreateAccount: (name: string, websiteUrl: string) => void;
  onDensityChange: (density: AccountTableDensity) => void;
  onFiltersChange: (filters: AccountFilterRule[]) => void;
  onSearchChange: (value: string) => void;
  onSortChange: (value: AccountSort) => void;
  projects: AccountProject[];
  researchStatusOptions: AccountFilterOption[];
  search: string;
  sort: AccountSort;
  visibleColumns: AccountColumnVisibility;
}

function SmallIcon({
  name,
  size = 12,
}: {
  name: string;
  size?: number;
}) {
  const intrinsicSizes: Record<string, [number, number]> = {
    check: [9, 6.5],
    close: [9.89, 9.89],
    "filters/grip-vertical": [5, 9],
    "filters/plus-horizontal": [9, 1],
    "filters/plus-vertical": [1, 9],
    "filters/trash": [10, 11],
    "plus-horizontal": [9, 1],
    "plus-vertical": [1, 9],
  };
  const [width, height] = intrinsicSizes[name] ?? [size, size];

  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center"
      style={{ height: size, width: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className="block max-w-none object-contain"
        height={height}
        src={`/icons/${name}.svg`}
        width={width}
      />
    </span>
  );
}

function ToolbarButton({
  icon,
  label,
  onClick,
  expanded,
}: {
  expanded?: boolean;
  icon: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-expanded={expanded}
      className={`${readability.actionMedium} flex h-[var(--clue-ds-product-component-button-sm-height)] items-center justify-center gap-[var(--clue-ds-product-component-button-gap)] rounded-[var(--clue-ds-product-component-button-sm-radius)] px-[var(--clue-ds-product-component-button-sm-padding-inline)] transition-colors hover:bg-[var(--clue-background-hover)] focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] focus-visible:outline-none`}
      onClick={onClick}
      type="button"
    >
      {icon === "plus" ? (
        <span aria-hidden="true" className="relative size-3 shrink-0">
          {/* Figma exports the plus as two centered leaf vectors. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt=""
            className="absolute top-1/2 left-1/2 h-px w-[9px] -translate-x-1/2 -translate-y-1/2"
            src="/icons/plus-horizontal.svg"
          />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt=""
            className="absolute top-1/2 left-1/2 h-[9px] w-px -translate-x-1/2 -translate-y-1/2"
            src="/icons/plus-vertical.svg"
          />
        </span>
      ) : (
        <DesignIcon name={icon} size={12} />
      )}
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}

function ColumnToggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      aria-checked={checked}
      aria-label={`${checked ? "Hide" : "Show"} ${label}`}
      className={`flex h-5 w-8 shrink-0 items-center rounded-[var(--clue-ds-product-component-button-md-radius)] p-0.5 transition-colors focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] ${
        checked
          ? "justify-end bg-[var(--clue-content-neutral)]"
          : "justify-start bg-[var(--clue-ds-color-border-subtle)]"
      }`}
      onClick={onChange}
      role="switch"
      type="button"
    >
      <span className="size-4 rounded-[var(--clue-ds-product-component-button-sm-radius)] border-[0.5px] border-[var(--clue-border-neutral)] bg-[var(--clue-background-neutral)] shadow-[var(--clue-ds-shadow-card-subtle)]" />
    </button>
  );
}

function ColumnsPanel({
  columnDefinitions,
  columnOrder,
  density,
  onDensityChange,
  onMove,
  onReorder,
  onToggle,
  visibleColumns,
}: {
  columnDefinitions: AccountColumnDefinition[];
  columnOrder: AccountColumnKey[];
  density: AccountTableDensity;
  onDensityChange: (density: AccountTableDensity) => void;
  onMove: (column: AccountColumnKey, direction: -1 | 1) => void;
  onReorder: (
    source: AccountColumnKey,
    target: AccountColumnKey,
  ) => void;
  onToggle: (column: AccountColumnKey) => void;
  visibleColumns: AccountColumnVisibility;
}) {
  const orderedColumns = columnOrder.map(
    (columnKey) =>
      columnDefinitions.find((column) => column.key === columnKey),
  ).filter((column): column is AccountColumnDefinition => Boolean(column));

  return (
    <section className={`${readability.popoverEnter} ${components.popover} absolute top-9 right-0 z-40 w-[300px] overflow-hidden`}>
      <h2 className={`${readability.actionMedium} px-3 pt-3 pb-1 text-[var(--clue-content-subtle)]`}>
        Columns
      </h2>
      {orderedColumns.map((column, index) => (
        <div
          className={`group/column flex h-8 items-center justify-between px-3 transition-colors hover:bg-[var(--clue-background-hover)] ${
            column.key === "company"
              ? "cursor-default"
              : "cursor-grab active:cursor-grabbing"
          }`}
          draggable={column.key !== "company"}
          key={column.key}
          onDragOver={(event) => event.preventDefault()}
          onDragStart={(event) => {
            if (column.key === "company") {
              event.preventDefault();
              return;
            }
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(
              "text/x-clue-account-column",
              column.key,
            );
          }}
          onDrop={(event) => {
            event.preventDefault();
            const source = event.dataTransfer.getData(
              "text/x-clue-account-column",
            ) as AccountColumnKey;
            if (columnOrder.includes(source)) {
              onReorder(source, column.key);
            }
          }}
        >
          <span className="flex min-w-0 items-center gap-2">
            {column.key !== "company" ? (
              <SmallIcon name="filters/grip-vertical" size={12} />
            ) : null}
            <AccountColumnIcon name={column.icon} size={12} />
            <span className={`${readability.uiRegular} truncate`}>
              {column.label}
            </span>
          </span>
          <span className="flex items-center gap-1">
            {column.key === "company" ? (
              <span className={`${readability.actionMedium} pr-1 text-[var(--clue-content-subtle)]`}>
                Pinned
              </span>
            ) : (
              <>
                <button
                  aria-label={`Move ${column.label} earlier`}
                  className="flex size-5 items-center justify-center rounded-[var(--clue-ds-product-component-button-sm-radius)] text-[var(--clue-content-subtle)] opacity-0 outline-none transition-opacity hover:bg-[var(--clue-background-neutral)] focus-visible:opacity-100 focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] disabled:opacity-0 group-hover/column:opacity-100"
                  disabled={index <= 1}
                  onClick={() => onMove(column.key, -1)}
                  type="button"
                >
                  ↑
                </button>
                <button
                  aria-label={`Move ${column.label} later`}
                  className="flex size-5 items-center justify-center rounded-[var(--clue-ds-product-component-button-sm-radius)] text-[var(--clue-content-subtle)] opacity-0 outline-none transition-opacity hover:bg-[var(--clue-background-neutral)] focus-visible:opacity-100 focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] disabled:opacity-0 group-hover/column:opacity-100"
                  disabled={index === orderedColumns.length - 1}
                  onClick={() => onMove(column.key, 1)}
                  type="button"
                >
                  ↓
                </button>
                <ColumnToggle
                  checked={visibleColumns[column.key]}
                  label={column.label}
                  onChange={() => onToggle(column.key)}
                />
              </>
            )}
          </span>
        </div>
      ))}
      <div className="mt-2 border-t-[0.5px] border-[var(--clue-border-neutral)] px-3 pt-3 pb-3">
        <h2 className={`${readability.actionMedium} mb-2 text-[var(--clue-content-subtle)]`}>
          Row density
        </h2>
        <TableDensitySelector
          density={density}
          onChange={onDensityChange}
        />
      </div>
    </section>
  );
}

function CheckRow({
  checked,
  label,
  onClick,
}: {
  checked: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`${readability.uiRegular} flex h-8 w-full items-center px-3 text-left hover:bg-[var(--clue-background-hover)]`}
      onClick={onClick}
      type="button"
    >
      <span className="flex size-6 items-center justify-center">
        {checked ? <SmallIcon name="check" size={12} /> : null}
      </span>
      <span>{label}</span>
    </button>
  );
}

function SortPanel({
  onSortChange,
  sort,
}: {
  onSortChange: AccountsToolbarProps["onSortChange"];
  sort: AccountsToolbarProps["sort"];
}) {
  const controller = useAccountsSortController(sort, onSortChange);

  return (
    <section className={`${readability.popoverEnter} ${components.popover} absolute top-9 right-0 z-40 w-[235px] overflow-hidden`}>
      <h2 className={`${readability.actionMedium} px-3 pt-3 pb-1 text-[var(--clue-content-subtle)]`}>
        Sort by
      </h2>
      <CheckRow
        checked={controller.sortField === "default"}
        label="Default order"
        onClick={() => controller.chooseField("default")}
      />
      <CheckRow
        checked={controller.sortField === "name"}
        label="Account name"
        onClick={() => controller.chooseField("name")}
      />
      <CheckRow
        checked={controller.sortField === "project"}
        label="Project"
        onClick={() => controller.chooseField("project")}
      />
      {controller.sortField !== "default" ? (
        <div className="mt-2 border-t-[0.5px] border-[var(--clue-ds-color-border-subtle)]">
          <h2 className={`${readability.actionMedium} px-3 pt-3 pb-1 text-[var(--clue-content-subtle)]`}>
            Order
          </h2>
          <CheckRow
            checked={!controller.descending}
            label="Ascending"
            onClick={controller.chooseAscending}
          />
          <CheckRow
            checked={controller.descending}
            label="Descending"
            onClick={controller.chooseDescending}
          />
        </div>
      ) : null}
      <div className="h-2" />
    </section>
  );
}

function NewAccountModal({
  name,
  onCancel,
  onNameChange,
  onSubmit,
  onWebsiteChange,
  website,
}: {
  name: string;
  onCancel: () => void;
  onNameChange: (value: string) => void;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  onWebsiteChange: (value: string) => void;
  website: string;
}) {
  return createPortal(
    <div
      aria-labelledby="new-account-title"
      aria-modal="true"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[#111827]/20 p-4 backdrop-blur-[1px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
      role="dialog"
    >
      <form
        className={`${components.popover} w-[463px] max-w-full overflow-hidden shadow-[0_18px_54px_rgba(0,24,62,0.18)]`}
        onSubmit={onSubmit}
      >
        <header className="flex items-center justify-between pt-3 pr-3 pb-2 pl-4">
          <h2 className="font-medium" id="new-account-title">
            New account
          </h2>
          <button
            aria-label="Close new account dialog"
            className={components.iconButton}
            onClick={onCancel}
            type="button"
          >
            <SmallIcon name="close" size={16} />
          </button>
        </header>
        <div className="space-y-4 px-4 py-3">
          <label className="grid grid-cols-[1fr_280px] items-start gap-4">
            <span className="pt-2">Company name</span>
            <input
              autoFocus
              className={`${components.input} px-2`}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder="Acme Inc"
              value={name}
            />
          </label>
          <label className="grid grid-cols-[1fr_280px] items-start gap-4">
            <span className="pt-2">Website</span>
            <input
              className={`${components.input} px-2`}
              onChange={(event) => onWebsiteChange(event.target.value)}
              placeholder="www.acme.com"
              value={website}
            />
          </label>
        </div>
        <footer className="flex justify-end gap-2 p-4">
          <Button
            onClick={onCancel}
            size="md"
            type="button"
            variant="transparent"
          >
            Cancel
          </Button>
          <Button
            disabled={!name.trim() || !website.trim()}
            size="md"
            type="submit"
          >
            Create
          </Button>
        </footer>
      </form>
    </div>,
    document.body,
  );
}

export function AccountsToolbar({
  embedded = false,
  onAddAccounts,
  columnDefinitions,
  columnOrder,
  density,
  filters,
  onColumnMove,
  onColumnReorder,
  onColumnToggle,
  onCreateAccount,
  onDensityChange,
  onFiltersChange,
  onSearchChange,
  onSortChange,
  projects,
  researchStatusOptions,
  search,
  sort,
  visibleColumns,
}: AccountsToolbarProps) {
  const {
    closePanel,
    controlsRef,
    newAccountName,
    newAccountWebsite,
    openPanel,
    setNewAccountName,
    setNewAccountWebsite,
    submitNewAccount,
    togglePanel,
  } = useAccountsToolbarController(onCreateAccount);

  return (
    <header className={`${readability.uiRegular} ${embedded ? toolbarStyles.embedded : "relative z-20 flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-table)] bg-white pr-5 pl-14 lg:px-6"}`}>
      <div className="flex min-w-0 items-center gap-4">
        {!embedded ? <h1 className={readability.pageTitle}>Accounts</h1> : null}
        <label className={`${components.input} flex w-[clamp(140px,20vw,240px)] shrink-0 items-center gap-1.5 px-2.5`}>
          <span className="sr-only">Search accounts</span>
          <DesignIcon name="search" size={12} />
          <input
            className={`${readability.uiRegular} min-w-0 flex-1 bg-transparent outline-none placeholder:text-[var(--clue-content-subtle)]`}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={embedded ? "Search accounts" : "Search"}
            type="search"
            value={search}
          />
        </label>
      </div>

      <div
        className={embedded ? toolbarStyles.controls : "relative ml-4 hidden shrink-0 items-center gap-2.5 md:flex"}
        ref={controlsRef}
      >
        <div className="relative">
          <ToolbarButton
            expanded={openPanel === "columns"}
            icon="settings"
            label="Customise columns"
            onClick={() => togglePanel("columns")}
          />
          {openPanel === "columns" ? (
            <ColumnsPanel
              columnDefinitions={columnDefinitions}
              columnOrder={columnOrder}
              density={density}
              onDensityChange={onDensityChange}
              onMove={onColumnMove}
              onReorder={onColumnReorder}
              onToggle={onColumnToggle}
              visibleColumns={visibleColumns}
            />
          ) : null}
        </div>
        <div className="relative">
          <ToolbarButton
            expanded={openPanel === "sort"}
            icon="sort"
            label="Sort"
            onClick={() => togglePanel("sort")}
          />
          {openPanel === "sort" ? (
            <SortPanel onSortChange={onSortChange} sort={sort} />
          ) : null}
        </div>
        <div className="relative">
          <ToolbarButton
            expanded={openPanel === "filter"}
            icon="filter"
            label="Filter"
            onClick={() => togglePanel("filter")}
          />
          {openPanel === "filter" ? (
            <AccountsFilterPanel
              filters={filters}
              onFiltersChange={onFiltersChange}
              projects={projects}
              researchStatusOptions={researchStatusOptions}
            />
          ) : null}
        </div>
        <ToolbarButton
          expanded={openPanel === "new"}
          icon="plus"
          label={onAddAccounts ? "Add accounts" : "New account"}
          onClick={onAddAccounts ?? (() => togglePanel("new"))}
        />
      </div>

      {openPanel === "new" ? (
        <NewAccountModal
          name={newAccountName}
          onCancel={closePanel}
          onNameChange={setNewAccountName}
          onSubmit={submitNewAccount}
          onWebsiteChange={setNewAccountWebsite}
          website={newAccountWebsite}
        />
      ) : null}
    </header>
  );
}
