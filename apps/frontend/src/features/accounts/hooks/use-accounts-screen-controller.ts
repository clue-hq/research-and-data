import { useMemo, useState, useTransition } from "react";
import type { Account, AccountsResponse } from "../model/account";
import type { AccountRecovery } from "../model/account-recovery";
import { loadMoreAccounts } from "../data/accounts.actions";
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

/**
 * An optimistic, client-only row for an account the user just typed in.
 *
 * No create endpoint exists on this read surface, so the row exists only in
 * this session. Every enrichment field is left genuinely empty — a
 * placeholder score or an "Unknown" band here would be indistinguishable from
 * a real backend answer.
 */
function createLocalAccount(name: string, domain: string): Account {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");

  return {
    id: `${slug}-${crypto.randomUUID()}`,
    name,
    domain,
    employeeCount: null,
    revenueBand: null,
    logoUrl: null,
    projects: [],
    primaryProjectId: null,
    scores: [],
    researchStatus: [],
    updatedAt: null,
  };
}

export function useAccountsScreenController(
  initialAccounts: Account[],
  initialMeta: AccountsResponse["meta"],
) {
  const [search, setSearch] = useState("");
  const [accountRows, setAccountRows] = useState(initialAccounts);
  // Pagination is keyset: the page holds only what has been fetched so far,
  // and `total` is the size of the whole filtered set on the backend. The two
  // are reported separately because they are different numbers.
  const [nextCursor, setNextCursor] = useState(initialMeta.nextCursor);
  const [totalCount, setTotalCount] = useState(initialMeta.total);
  const [loadRecovery, setLoadRecovery] =
    useState<AccountRecovery | null>(null);
  const [isLoadingMore, startLoadingMore] = useTransition();
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

  // Whether the user has narrowed the table at all. Keyed on the *authored*
  // filters, not on whether they happened to exclude a row: a filter that
  // excludes nothing on the loaded page still hides whatever sits on the pages
  // that were never fetched, which is exactly when the caveat matters.
  const hasActiveFilter = useMemo(
    () => search.trim() !== "" || filters.some((rule) => rule.value.trim() !== ""),
    [filters, search],
  );

  const projectOptions = useMemo(() => {
    const projects = new Map<string, Account["projects"][number]>();
    for (const account of accountRows) {
      for (const project of account.projects) {
        projects.set(project.projectId, project);
      }
    }
    return [...projects.values()].sort((first, second) =>
      (first.name ?? "").localeCompare(second.name ?? ""),
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

  function createAccount(name: string, domain: string) {
    setAccountRows((current) => [
      createLocalAccount(name, domain),
      ...current,
    ]);
  }

  function loadMore() {
    const cursor = nextCursor;
    if (!cursor || isLoadingMore) return;

    startLoadingMore(async () => {
      try {
        const result = await loadMoreAccounts(cursor);
        if (result.status === "recovery") {
          setLoadRecovery(result.recovery);
          return;
        }
        const { response } = result;
        setAccountRows((current) => {
          // The backend can only append here, but a retried action must not
          // duplicate rows the table already holds.
          const seen = new Set(current.map((account) => account.id));
          return [
            ...current,
            ...response.data.filter((account) => !seen.has(account.id)),
          ];
        });
        setNextCursor(response.meta.nextCursor);
        setTotalCount(response.meta.total);
        setLoadRecovery(null);
      } catch (error) {
        console.error("Unexpected Accounts pagination failure", error);
        setLoadRecovery({
          kind: "contract_error",
          requestId: null,
          retryable: false,
        });
      }
    });
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
    hasActiveFilter,
    hasMore: nextCursor !== null,
    isLoadingMore,
    loadedCount: accountRows.length,
    loadRecovery,
    loadMore,
    totalCount,
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
