import { useMemo, useState } from "react";
import type { Account } from "../model/account";
import { useAccountWorkspaceOwner } from "./use-account-owner";
import { resolveAccountOwner } from "../model/account-owner";
import { createLocalAccount } from "../model/create-account";
import {
  createAccountColumnDefinitions,
  createAccountColumnOrder,
  createAccountColumnVisibility,
  createAccountColumnWidths,
  type AccountColumnKey,
  type AccountSort,
  type AccountTableDensity,
} from "../model/account-table-view";
import {
  createDefaultAccountFilterRules,
  filterAccounts,
  sortAccounts,
} from "../model/account-query";

export function useAccountsScreenController(initialAccounts: Account[]) {
  const workspaceOwner = useAccountWorkspaceOwner();
  const initialColumnDefinitions = createAccountColumnDefinitions(
    initialAccounts,
  );
  const [search, setSearch] = useState("");
  const [accountRows, setAccountRows] = useState(initialAccounts);
  const [filters, setFilters] = useState(createDefaultAccountFilterRules);
  const [sort, setSort] = useState<AccountSort>("default");
  const [density, setDensity] =
    useState<AccountTableDensity>("spacious");
  const [columnOrder, setColumnOrder] = useState(
    () => createAccountColumnOrder(initialColumnDefinitions),
  );
  const [columnWidths, setColumnWidths] = useState(
    () => createAccountColumnWidths(initialColumnDefinitions),
  );
  const [visibleColumns, setVisibleColumns] = useState(
    () => createAccountColumnVisibility(initialColumnDefinitions),
  );
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
    return sortAccounts(filterAccounts(searched, filters), sort).map((account) => ({
      ...account, owner: resolveAccountOwner(account),
    }));
  }, [accountRows, filters, search, sort]);

  const columnDefinitions = useMemo(
    () => createAccountColumnDefinitions(accountRows),
    [accountRows],
  );

  // The research-status filter's vocabulary is the served `researchStatusLabel`
  // of the rows in hand — the browser keeps no status label map (source map §6).
  const researchStatusOptions = useMemo(() => {
    const options = new Map<string, { label: string; value: string }>();
    for (const account of accountRows) {
      options.set(account.researchStatus, {
        label: account.researchStatusLabel ?? account.researchStatus,
        value: account.researchStatus,
      });
    }
    return [...options.values()].sort((first, second) =>
      first.label.localeCompare(second.label),
    );
  }, [accountRows]);

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
    const defaultWidth =
      columnDefinitions.find((definition) => definition.key === column)
        ?.width ?? 140;
    setColumnWidths((current) => ({
      ...current,
      [column]: defaultWidth,
    }));
  }

  function createAccount(name: string, websiteUrl: string) {
    setAccountRows((current) => [
      createLocalAccount(name, websiteUrl, workspaceOwner),
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
    columnDefinitions,
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
    researchStatusOptions,
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
