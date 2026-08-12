import { useMemo, useRef, useState, useTransition } from "react";
import type { Account, AccountsResponse } from "../model/account";
import type { AccountRecovery } from "../model/account-recovery";
import type { AccountBulkCapabilities } from "../model/bulk-actions";
import { loadAccountsPage } from "../data/accounts.actions";
import { addAccountsToProject } from "../data/bulk-actions.repository";
import { ClueApiError } from "../data/clue-api-error";
import {
  defaultAccountColumnOrder,
  defaultAccountColumnWidths,
  defaultAccountColumns,
  type AccountColumnKey,
  type AccountSort,
  type AccountTableDensity,
} from "../model/account-table-view";
import type { AccountFilterRule } from "../model/account-query";
import {
  createDefaultAccountFilterRules,
  filterAccounts,
  sortAccounts,
} from "../model/account-query";

/** The deferred, explicitly non-durable create control remains untouched in this slice. */
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
  bulkCapabilities: AccountBulkCapabilities,
) {
  const [search, setSearchState] = useState("");
  const [accountRows, setAccountRows] = useState(initialAccounts);
  const [durableAccountIds, setDurableAccountIds] = useState(
    () => new Set(initialAccounts.map((account) => account.id)),
  );
  const [page, setPage] = useState(initialMeta.page ?? 1);
  const [pageSize, setPageSize] = useState(initialMeta.pageSize ?? 20);
  const [totalPages, setTotalPages] = useState(initialMeta.totalPages ?? 1);
  const [totalCount, setTotalCount] = useState(initialMeta.total);
  const [loadRecovery, setLoadRecovery] = useState<AccountRecovery | null>(null);
  const [isPageLoading, startPageTransition] = useTransition();
  const [filters, setFiltersState] = useState(createDefaultAccountFilterRules);
  const [sort, setSortState] = useState<AccountSort>("default");
  const [density, setDensity] = useState<AccountTableDensity>("spacious");
  const [columnOrder, setColumnOrder] = useState(defaultAccountColumnOrder);
  const [columnWidths, setColumnWidths] = useState(defaultAccountColumnWidths);
  const [visibleColumns, setVisibleColumns] = useState(defaultAccountColumns);
  const [selectedAccountIds, setSelectedAccountIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedProjectId, setSelectedProjectIdState] = useState(
    bulkCapabilities.projects[0]?.id ?? "",
  );
  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const bulkAttemptKey = useRef<string | null>(null);

  const visibleAccounts = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    const searched = accountRows.filter(
      (account) =>
        !normalizedSearch ||
        account.name.toLocaleLowerCase().includes(normalizedSearch),
    );
    return sortAccounts(filterAccounts(searched, filters), sort);
  }, [accountRows, filters, search, sort]);

  const hasActiveFilter = useMemo(
    () => search.trim() !== "" || filters.some((rule) => rule.value.trim() !== ""),
    [filters, search],
  );

  const projectOptions = useMemo(() => {
    const projects = new Map<string, Account["projects"][number]>();
    for (const account of accountRows) {
      for (const project of account.projects) projects.set(project.projectId, project);
    }
    return [...projects.values()].sort((first, second) =>
      (first.name ?? "").localeCompare(second.name ?? ""),
    );
  }, [accountRows]);

  function clearSelection() {
    setSelectedAccountIds(new Set());
    bulkAttemptKey.current = null;
  }

  function toggleColumn(column: AccountColumnKey) {
    if (column === "company") return;
    setVisibleColumns((current) => ({ ...current, [column]: !current[column] }));
  }

  function moveColumn(column: AccountColumnKey, direction: -1 | 1) {
    if (column === "company") return;
    setColumnOrder((current) => {
      const currentIndex = current.indexOf(column);
      const nextIndex = currentIndex + direction;
      if (currentIndex < 0 || nextIndex <= 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[currentIndex], next[nextIndex]] = [next[nextIndex], next[currentIndex]];
      return next;
    });
  }

  function reorderColumn(source: AccountColumnKey, target: AccountColumnKey) {
    if (source === target || source === "company") return;
    setColumnOrder((current) => {
      const next = current.filter((column) => column !== source);
      const targetIndex = target === "company" ? 1 : next.indexOf(target);
      next.splice(targetIndex, 0, source);
      return next;
    });
  }

  function setColumnWidth(column: AccountColumnKey, width: number) {
    setColumnWidths((current) => ({ ...current, [column]: width }));
  }

  function resetColumnWidth(column: AccountColumnKey) {
    setColumnWidths((current) => ({
      ...current,
      [column]: defaultAccountColumnWidths[column],
    }));
  }

  function createAccount(name: string, domain: string) {
    setAccountRows((current) => [createLocalAccount(name, domain), ...current]);
    clearSelection();
  }

  function loadPage(nextPage: number, nextPageSize = pageSize) {
    if (isPageLoading) return;
    clearSelection();
    startPageTransition(async () => {
      try {
        const result = await loadAccountsPage(nextPage, nextPageSize);
        if (result.status === "recovery") {
          setLoadRecovery(result.recovery);
          return;
        }
        const { response } = result;
        setAccountRows(response.data);
        setDurableAccountIds(new Set(response.data.map((account) => account.id)));
        setPage(response.meta.page ?? nextPage);
        setPageSize(response.meta.pageSize ?? nextPageSize);
        setTotalPages(response.meta.totalPages ?? 1);
        setTotalCount(response.meta.total);
        setLoadRecovery(null);
      } catch (error) {
        console.error("Unexpected Accounts pagination failure", error);
        setLoadRecovery({ kind: "contract_error", requestId: null, retryable: false });
      }
    });
  }

  function setSearch(value: string) {
    clearSelection();
    setSearchState(value);
  }

  function setFilters(value: AccountFilterRule[]) {
    clearSelection();
    setFiltersState(value);
  }

  function setSort(value: AccountSort) {
    clearSelection();
    setSortState(value);
  }

  function setSelectedProjectId(value: string) {
    setSelectedProjectIdState(value);
    bulkAttemptKey.current = null;
  }

  function toggleAccount(accountId: string) {
    if (!durableAccountIds.has(accountId)) return;
    bulkAttemptKey.current = null;
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  function toggleAllVisibleAccounts() {
    bulkAttemptKey.current = null;
    setSelectedAccountIds((current) => {
      const selectable = visibleAccounts.filter((account) =>
        durableAccountIds.has(account.id),
      );
      const allVisibleSelected =
        selectable.length > 0 &&
        selectable.every((account) => current.has(account.id));
      return allVisibleSelected
        ? new Set()
        : new Set(
            selectable.map((account) => account.id),
          );
    });
  }

  async function executeAddToProject() {
    if (!selectedProjectId || selectedAccountIds.size === 0 || isBulkSubmitting) return;
    if (selectedAccountIds.size > bulkCapabilities.addToProject.maxItems) return;
    const idempotencyKey = bulkAttemptKey.current ?? crypto.randomUUID();
    bulkAttemptKey.current = idempotencyKey;
    setIsBulkSubmitting(true);
    setBulkNotice(null);
    try {
      const result = await addAccountsToProject({
        accountIds: [...selectedAccountIds],
        idempotencyKey,
        projectId: selectedProjectId,
      });
      const project = bulkCapabilities.projects.find(
        (option) => option.id === selectedProjectId,
      );
      const reflectedIds = new Set(
        result.items
          .filter((item) => item.outcome === "completed" || item.outcome === "unchanged")
          .map((item) => item.subjectId),
      );
      setAccountRows((current) =>
        current.map((account) =>
          !project ||
          !reflectedIds.has(account.id) ||
          account.projects.some((membership) => membership.projectId === project.id)
            ? account
            : {
                ...account,
                projects: [
                  ...account.projects,
                  {
                    projectId: project.id,
                    name: project.name,
                    addedVia: "manual" as const,
                    addedAt: null,
                  },
                ],
                primaryProjectId: account.primaryProjectId ?? project.id,
              },
        ),
      );
      const parts = [
        result.counts.completed ? `${result.counts.completed} added` : null,
        result.counts.unchanged ? `${result.counts.unchanged} already in project` : null,
        result.counts.ineligible ? `${result.counts.ineligible} ineligible` : null,
        result.counts.failed ? `${result.counts.failed} failed` : null,
      ].filter(Boolean);
      setBulkNotice(parts.join(" · "));
      clearSelection();
    } catch (error) {
      if (error instanceof ClueApiError && error.status === 401) {
        window.location.assign("/sign-in?reason=session_expired");
        return;
      }
      setBulkNotice(
        error instanceof ClueApiError && error.status === 403
          ? "You no longer have permission to add Accounts to this project."
          : "The Account action could not finish. Try again to safely resume it.",
      );
    } finally {
      setIsBulkSubmitting(false);
    }
  }

  return {
    bulkCapabilities,
    bulkNotice,
    clearBulkNotice: () => setBulkNotice(null),
    clearSelection,
    columnOrder,
    columnWidths,
    createAccount,
    density,
    executeAddToProject,
    filters,
    hasActiveFilter,
    isBulkSubmitting,
    isPageLoading,
    loadPage,
    loadRecovery,
    moveColumn,
    page,
    pageSize,
    projectOptions,
    reorderColumn,
    resetColumnWidth,
    search,
    selectedAccountIds,
    selectableAccountIds: durableAccountIds,
    selectedProjectId,
    selectionEnabled: bulkCapabilities.addToProject.allowed,
    setColumnWidth,
    setDensity,
    setFilters,
    setSearch,
    setSelectedProjectId,
    setSort,
    sort,
    toggleAccount,
    toggleAllVisibleAccounts,
    toggleColumn,
    totalCount,
    totalPages,
    visibleAccounts,
    visibleColumns,
  };
}
