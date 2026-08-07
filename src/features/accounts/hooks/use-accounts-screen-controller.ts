import { useMemo, useState } from "react";
import type { Account } from "../model/account";
import {
  defaultAccountColumnOrder,
  defaultAccountColumnWidths,
  defaultAccountColumns,
  type AccountColumnKey,
  type AccountSort,
  type AccountTableDensity,
} from "../model/account-table-view";
import {
  createDefaultAccountFilterRules,
  filterAccounts,
  sortAccounts,
} from "../model/account-query";

function createLocalAccount(name: string, websiteUrl: string): Account {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

  return {
    employeeBand: "Unknown",
    fitScore: 0,
    id: `${slug}-${crypto.randomUUID()}`,
    locationCount: 0,
    logoPath: "/icons/building.svg",
    name,
    overallFit: "Medium",
    primaryProjectId: null,
    projects: [],
    researchIsRefreshing: false,
    researchStatus: "not_started",
    revenueBand: "Unknown",
    websiteUrl,
  };
}

export function useAccountsScreenController(initialAccounts: Account[]) {
  const [search, setSearch] = useState("");
  const [accountRows, setAccountRows] = useState(initialAccounts);
  const [filters, setFilters] = useState(createDefaultAccountFilterRules);
  const [sort, setSort] = useState<AccountSort>("default");
  const [density, setDensity] =
    useState<AccountTableDensity>("spacious");
  const [columnOrder, setColumnOrder] = useState(
    defaultAccountColumnOrder,
  );
  const [columnWidths, setColumnWidths] = useState(
    defaultAccountColumnWidths,
  );
  const [visibleColumns, setVisibleColumns] = useState(defaultAccountColumns);
  const [selectedAccountIds, setSelectedAccountIds] = useState<Set<string>>(
    () => new Set(),
  );

  const visibleAccounts = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    const searched = accountRows.filter(
      (account) =>
        !normalizedSearch ||
        account.name.toLocaleLowerCase().includes(normalizedSearch),
    );
    return sortAccounts(filterAccounts(searched, filters), sort);
  }, [accountRows, filters, search, sort]);

  const projectOptions = useMemo(() => {
    const projects = new Map<string, Account["projects"][number]>();
    for (const account of accountRows) {
      for (const project of account.projects) projects.set(project.id, project);
    }
    return [...projects.values()].sort((first, second) =>
      first.name.localeCompare(second.name),
    );
  }, [accountRows]);

  function toggleColumn(column: AccountColumnKey) {
    if (column === "company") return;

    setVisibleColumns((current) => ({
      ...current,
      [column]: !current[column],
    }));
  }

  function moveColumn(column: AccountColumnKey, direction: -1 | 1) {
    if (column === "company") return;

    setColumnOrder((current) => {
      const currentIndex = current.indexOf(column);
      const nextIndex = currentIndex + direction;
      if (
        currentIndex < 0 ||
        nextIndex <= 0 ||
        nextIndex >= current.length
      ) {
        return current;
      }

      const next = [...current];
      [next[currentIndex], next[nextIndex]] = [
        next[nextIndex],
        next[currentIndex],
      ];
      return next;
    });
  }

  function reorderColumn(
    source: AccountColumnKey,
    target: AccountColumnKey,
  ) {
    if (source === target || source === "company") return;

    setColumnOrder((current) => {
      const next = current.filter((column) => column !== source);
      const targetIndex =
        target === "company" ? 1 : next.indexOf(target);
      next.splice(targetIndex, 0, source);
      return next;
    });
  }

  function setColumnWidth(column: AccountColumnKey, width: number) {
    setColumnWidths((current) => ({
      ...current,
      [column]: width,
    }));
  }

  function resetColumnWidth(column: AccountColumnKey) {
    setColumnWidths((current) => ({
      ...current,
      [column]: defaultAccountColumnWidths[column],
    }));
  }

  function createAccount(name: string, websiteUrl: string) {
    setAccountRows((current) => [
      createLocalAccount(name, websiteUrl),
      ...current,
    ]);
  }

  function toggleAccount(accountId: string) {
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  function toggleAllVisibleAccounts() {
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      const allVisibleSelected =
        visibleAccounts.length > 0 &&
        visibleAccounts.every((account) => next.has(account.id));

      for (const account of visibleAccounts) {
        if (allVisibleSelected) next.delete(account.id);
        else next.add(account.id);
      }

      return next;
    });
  }

  return {
    createAccount,
    columnOrder,
    columnWidths,
    density,
    filters,
    moveColumn,
    reorderColumn,
    resetColumnWidth,
    search,
    selectedAccountIds,
    projectOptions,
    setFilters,
    setColumnWidth,
    setDensity,
    setSearch,
    setSort,
    sort,
    toggleAccount,
    toggleAllVisibleAccounts,
    toggleColumn,
    visibleAccounts,
    visibleColumns,
  };
}
