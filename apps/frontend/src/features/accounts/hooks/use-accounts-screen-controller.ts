import { useMemo, useRef, useState } from "react";
import type { Account, AccountProject } from "../model/account";
import { useChatTransport } from "@/features/projects/data/projects-transport";
import { useAccountWorkspaceOwner } from "./use-account-owner";
import { resolveAccountOwner } from "../model/account-owner";
import type { AccountBulkCapabilities } from "../model/bulk-actions";
import {
  createLocalAccount,
  isLocalDraftAccount,
  type AccountRow,
} from "../model/create-account";
import {
  addAccountsToProject,
  addSelectedAccountsToProject,
} from "../data/bulk-actions.repository";
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

/**
 * `options.project` scopes the controller to one project's target accounts.
 *
 * Given, the rows the screen reads (`accounts`) and everything derived from
 * them — search, filters, sort, the column definitions — are the rows holding
 * that membership; the rest of the workspace's accounts stay in `accountRows`
 * so a row added to the project appears without a re-read. Omitted, the
 * controller behaves exactly as the workspace-wide Accounts screen always has.
 */
export function useAccountsScreenController(
  initialAccounts: Account[],
  bulkCapabilities: AccountBulkCapabilities,
  submitAddToProject: typeof addSelectedAccountsToProject = addSelectedAccountsToProject,
  options?: { project?: AccountProject },
) {
  const project = options?.project;
  const workspaceOwner = useAccountWorkspaceOwner();
  // The chat handoff exists only against the real backend: in fixture mode the
  // projects transport has nowhere to prepare a composer draft.
  const chatHandoffAvailable = useChatTransport().mode === "http";
  const initialColumnDefinitions = createAccountColumnDefinitions(
    initialAccounts,
  );
  const [search, setSearch] = useState("");
  const [accountRows, setAccountRows] = useState<AccountRow[]>(initialAccounts);
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
  const [selectedProjectId, setSelectedProjectIdState] = useState(
    bulkCapabilities.projects[0]?.id ?? "",
  );
  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  // One idempotency key per attempt at the same selection, so a retry after a
  // timeout resumes the same operation instead of starting a second one.
  const bulkAttemptKey = useRef<string | null>(null);

  const scopedAccounts = useMemo(() => project
    ? accountRows.filter((account) => account.projects.some(({ id }) => id === project.id))
    : accountRows, [accountRows, project]);

  const visibleAccounts = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    const searched = scopedAccounts.filter(
      (account) =>
        !normalizedSearch ||
        account.name.toLocaleLowerCase().includes(normalizedSearch),
    );
    return sortAccounts(filterAccounts(searched, filters), sort).map((account) => ({
      ...account, owner: resolveAccountOwner(account),
    }));
  }, [scopedAccounts, filters, search, sort]);

  const columnDefinitions = useMemo(
    () => createAccountColumnDefinitions(scopedAccounts),
    [scopedAccounts],
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

  // A local draft exists only in this tab, so no server-side bulk action can
  // name it: it is never selectable.
  const selectableAccountIds = useMemo(
    () =>
      new Set(
        accountRows
          .filter((account) => !isLocalDraftAccount(account))
          .map((account) => account.id),
      ),
    [accountRows],
  );

  /**
   * The selection a bulk action can actually act on.
   *
   * Searching, filtering or sorting does NOT clear the selection (that is the
   * design build's behaviour, and a filter is not a deselection): a row hidden
   * by the current view keeps its checkbox and comes back with it. It is simply
   * not counted while it is out of view, so nothing is ever submitted that the
   * operator cannot see.
   */
  const visibleSelectedAccountIds = useMemo(
    () =>
      new Set(
        visibleAccounts
          .filter(
            (account) =>
              selectedAccountIds.has(account.id) &&
              selectableAccountIds.has(account.id),
          )
          .map((account) => account.id),
      ),
    [selectableAccountIds, selectedAccountIds, visibleAccounts],
  );

  function clearSelection() {
    setSelectedAccountIds(new Set());
    bulkAttemptKey.current = null;
  }

  function setSelectedProjectId(value: string) {
    setSelectedProjectIdState(value);
    bulkAttemptKey.current = null;
  }

  async function executeAddToProject() {
    if (
      !selectedProjectId ||
      visibleSelectedAccountIds.size === 0 ||
      isBulkSubmitting
    ) {
      return;
    }
    if (visibleSelectedAccountIds.size > bulkCapabilities.addToProject.maxItems) {
      return;
    }
    const project = bulkCapabilities.projects.find(
      (option) => option.id === selectedProjectId,
    );
    if (!project) return;

    const idempotencyKey = bulkAttemptKey.current ?? crypto.randomUUID();
    bulkAttemptKey.current = idempotencyKey;
    setIsBulkSubmitting(true);
    setBulkNotice(null);
    try {
      const outcome = await submitAddToProject({
        accountIds: [...visibleSelectedAccountIds],
        idempotencyKey,
        project,
        rows: accountRows,
      });
      if (outcome.status === "session_expired") {
        window.location.assign("/sign-in?reason=session_expired");
        return;
      }
      if (outcome.status === "added") {
        setAccountRows(outcome.rows);
        setBulkNotice(outcome.notice);
        clearSelection();
        return;
      }
      setBulkNotice(outcome.notice);
    } finally {
      setIsBulkSubmitting(false);
    }
  }

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

  /**
   * Show accounts the server has just placed in this project.
   *
   * Called only after the write succeeded, so nothing here is optimistic: the
   * membership stamped on each row is the one the backend now holds. Rows the
   * screen already has are left alone, and the columns widen to cover any
   * custom variable the new rows carry that the old ones did not.
   */
  function addAccounts(accounts: Account[]) {
    const added = accounts.map((account) => project && !account.projects.some(({ id }) => id === project.id)
      ? { ...account, projects: [...account.projects, project] }
      : account);
    setAccountRows((current) => [...current, ...added.filter((account) => !current.some(({ id }) => id === account.id))]);
    const definitions = createAccountColumnDefinitions(added);
    setColumnOrder((current) => [...current, ...definitions.map(({ key }) => key).filter((key) => !current.includes(key))]);
    setColumnWidths((current) => ({ ...createAccountColumnWidths(definitions), ...current }));
    setVisibleColumns((current) => ({ ...createAccountColumnVisibility(definitions), ...current }));
  }

  /**
   * Founder ruling 2: adding accounts to a project is a real membership write.
   *
   * The design build added the picked accounts to its own state and stopped
   * there. Here the backend decides: the rows are reflected only once the write
   * is accepted, and a refusal returns `false` with nothing touched, so the
   * screen can say so rather than show a membership the platform does not hold.
   * It is the same bulk action the workspace-wide selection bar submits.
   */
  async function submitAddAccounts(accounts: Account[]): Promise<boolean> {
    if (!project) return false;
    try {
      await addAccountsToProject({
        accountIds: accounts.map(({ id }) => id),
        idempotencyKey: crypto.randomUUID(),
        projectId: project.id,
      });
    } catch {
      return false;
    }
    addAccounts(accounts);
    return true;
  }

  function toggleAccount(accountId: string) {
    if (!selectableAccountIds.has(accountId)) return;
    bulkAttemptKey.current = null;
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  /**
   * Select every given account, or clear them all when they already are.
   *
   * A local draft is never selected here either: the guard belongs to the
   * selection, not to the caller, so a page-wide or project-wide toggle cannot
   * name a row no server-side bulk action could act on.
   */
  function toggleAccounts(accounts: Account[]) {
    bulkAttemptKey.current = null;
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      const selectable = accounts.filter((account) =>
        selectableAccountIds.has(account.id),
      );
      const allSelected =
        selectable.length > 0 &&
        selectable.every((account) => next.has(account.id));

      for (const account of selectable) {
        if (allSelected) next.delete(account.id);
        else next.add(account.id);
      }

      return next;
    });
  }

  function toggleAllVisibleAccounts() {
    toggleAccounts(visibleAccounts);
  }

  return {
    accounts: scopedAccounts,
    addAccounts,
    bulkCapabilities,
    bulkNotice,
    chatHandoffAvailable,
    clearBulkNotice: () => setBulkNotice(null),
    clearSelection,
    createAccount,
    columnDefinitions,
    columnOrder,
    columnWidths,
    density,
    executeAddToProject,
    filters,
    isBulkSubmitting,
    selectableAccountIds,
    selectedProjectId,
    selectionEnabled:
      bulkCapabilities.addToProject.allowed ||
      (chatHandoffAvailable && bulkCapabilities.addToChat.allowed),
    setSelectedProjectId,
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
    submitAddAccounts,
    toggleAccount,
    toggleAccounts,
    toggleAllVisibleAccounts,
    toggleColumn,
    visibleAccounts,
    visibleSelectedAccountIds,
    visibleColumns,
  };
}
