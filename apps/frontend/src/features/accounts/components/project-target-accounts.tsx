"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { WorkspaceProfileProvider } from "@/components/shell/workspace-profile-context";
import { Button } from "@/components/ui/button";
import { ProjectIcon } from "@/features/projects/components/project-icon";
import type { ChatContextRef } from "@/features/projects/model/chat-context-handoff";
import type { Account } from "../model/account";
import { createDefaultAccountFilterRules } from "../model/account-query";
import { accountPageSizes, accountsForProject, paginateAccounts, ProjectAccountsResponseSchema, type AccountPageSize, type ProjectAccountsResponse } from "../model/project-accounts";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";
import { AddProjectAccountsDialog } from "./project-account-dialogs";
import { ProjectAccountPreview } from "./project-account-preview";
import tableStyles from "./accounts-table.module.css";
import styles from "./project-accounts.module.css";

function ProjectAccountsBreadcrumb({ count, projectTitle }: { count?: number; projectTitle: string }) {
  return (
    <nav aria-label="Target accounts breadcrumb" className={styles.breadcrumb}>
      <span title={projectTitle}>{projectTitle}</span>
      <ProjectIcon name="chevron-right" size={10} />
      <h1>Target accounts</h1>
      <span aria-live="polite" className={styles.count}>{count === undefined ? "" : `${count} ${count === 1 ? "account" : "accounts"}`}</span>
    </nav>
  );
}

type AddToChat = (contextRefs: readonly ChatContextRef[]) => Promise<boolean>;

function ProjectAccountsTable({ data, onAddToChat, onReread, projectId, projectTitle }: {
  data: ProjectAccountsResponse;
  onAddToChat?: AddToChat;
  onReread: () => void;
  projectId: string;
  projectTitle: string;
}) {
  const project = useMemo(() => ({ id: projectId, name: projectTitle }), [projectId, projectTitle]);
  const accounts = useMemo(() => accountsForProject(data.accounts, projectId), [data.accounts, projectId]);
  const controller = useAccountsScreenController(accounts, data.bulkCapabilities, undefined, { project });
  const [pageSize, setPageSize] = useState<AccountPageSize>(25);
  const [pageRequest, setPageRequest] = useState({ key: "", page: 1 });
  const [adding, setAdding] = useState(false);
  const [addFailed, setAddFailed] = useState(false);
  const [addingToChat, setAddingToChat] = useState(false);
  const [preview, setPreview] = useState<Account | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const queryKey = JSON.stringify([controller.search, controller.filters, controller.sort, pageSize]);
  const pagination = paginateAccounts(controller.visibleAccounts, pageRequest.key === queryKey ? pageRequest.page : 1, pageSize);
  const available = data.availableAccounts.filter((account) => !controller.accounts.some(({ id }) => id === account.id));
  const isEmpty = controller.accounts.length === 0;
  // "Add to chat" (founder request 2026-09-11; not in the design build): the
  // global table's action, minus its destination picker — this tab already sits
  // beside the chat it targets. Same gate as the global bar (a real chat
  // transport and the server's capability), same limit, same context refs.
  const selectedCount = controller.selectedAccountIds.size;
  const addToChatShown = onAddToChat !== undefined && controller.chatHandoffAvailable && data.bulkCapabilities.addToChat.allowed;
  const overAddToChatLimit = selectedCount > data.bulkCapabilities.addToChat.maxItems;

  function clearFilters() {
    controller.setSearch("");
    controller.setFilters(createDefaultAccountFilterRules());
  }
  function setPage(page: number) {
    setPageRequest({ key: queryKey, page });
    viewportRef.current?.scrollTo({ top: 0 });
  }
  /**
   * Founder ruling 2: the dialog's picks go to the backend, not to local state.
   *
   * The controller owns the write (a component may not reach a repository) and
   * reflects the rows only when it is accepted. On success the served lists are
   * re-read so `availableAccounts` stops offering what is now a member; on a
   * refusal nothing on screen changes and the failure is stated.
   */
  async function addAccounts(accounts: Account[]) {
    if (await controller.submitAddAccounts(accounts)) {
      setAddFailed(false);
      onReread();
      return;
    }
    setAddFailed(true);
  }
  // The selection is cleared only once the chat has the accounts (the global
  // table's `onTransferred` rule); a refusal leaves it in place to retry.
  async function addSelectionToChat() {
    if (!onAddToChat || addingToChat) return;
    setAddingToChat(true);
    try {
      const accepted = await onAddToChat(
        [...controller.selectedAccountIds].map((accountId) => ({ objectId: accountId, objectType: "account" as const, version: null })),
      );
      if (accepted) controller.clearSelection();
    } finally {
      setAddingToChat(false);
    }
  }

  return (
    <section aria-label="Project target accounts" className={styles.surface}>
      <ProjectAccountsBreadcrumb count={controller.accounts.length} projectTitle={projectTitle} />
      <AccountsToolbar
        columnDefinitions={controller.columnDefinitions}
        columnOrder={controller.columnOrder}
        density={controller.density}
        embedded
        filters={controller.filters}
        onAddAccounts={() => setAdding(true)}
        onColumnMove={controller.moveColumn}
        onColumnReorder={controller.reorderColumn}
        onColumnToggle={controller.toggleColumn}
        onCreateAccount={controller.createAccount}
        onDensityChange={controller.setDensity}
        onFiltersChange={controller.setFilters}
        onSearchChange={controller.setSearch}
        onSortChange={controller.setSort}
        projects={[project]}
        researchStatusOptions={controller.researchStatusOptions}
        search={controller.search}
        sort={controller.sort}
        visibleColumns={controller.visibleColumns}
      />
      {selectedCount ? (
        <div className={styles.selection}>
          <span>{selectedCount} selected in this project</span>
          {addToChatShown ? (
            <Button disabled={overAddToChatLimit || addingToChat} onClick={() => { void addSelectionToChat(); }} size="md" type="button">
              {addingToChat ? "Adding…" : "Add to chat"}
            </Button>
          ) : null}
          <Button onClick={() => controller.toggleAccounts(controller.accounts.filter(({ id }) => controller.selectedAccountIds.has(id)))} size="sm" variant="transparent">Clear selection</Button>
          {addToChatShown && overAddToChatLimit ? (
            <span className="text-[var(--clue-content-subtle)]" role="alert">Select at most {data.bulkCapabilities.addToChat.maxItems} Accounts.</span>
          ) : null}
        </div>
      ) : null}
      {addFailed ? (
        <div className={styles.empty} role="alert">
          <h2>Unable to add accounts</h2>
          <p>Please try again.</p>
          <Button onClick={() => { setAddFailed(false); setAdding(true); }} size="md">Try again</Button>
        </div>
      ) : null}
      <div className={`${tableStyles.viewport} ${styles.viewport}`} ref={viewportRef}>
        {pagination.total ? (
          <AccountsTable
            accounts={pagination.accounts}
            columnDefinitions={controller.columnDefinitions}
            columnOrder={controller.columnOrder}
            columnWidths={controller.columnWidths}
            density={controller.density}
            label="Project target accounts"
            onColumnResize={controller.setColumnWidth}
            onColumnResizeReset={controller.resetColumnWidth}
            onOpenAccount={setPreview}
            onToggleAccount={controller.toggleAccount}
            onToggleAll={() => controller.toggleAccounts(pagination.accounts)}
            selectedAccountIds={controller.selectedAccountIds}
            visibleColumns={controller.visibleColumns}
          />
        ) : (
          <div className={styles.empty}>
            <ProjectIcon name={isEmpty ? "target-accounts" : "search"} size={24} />
            <h2>{isEmpty ? "No target accounts yet" : "No matching accounts"}</h2>
            <p>{isEmpty ? "Add accounts to this project to get started." : "Try another search or clear your filters."}</p>
            <Button onClick={isEmpty ? () => setAdding(true) : clearFilters} size="md" variant="transparent">{isEmpty ? "Add accounts" : "Clear filters"}</Button>
          </div>
        )}
      </div>
      <footer className={styles.footer}>
        <span aria-live="polite">{pagination.start}–{pagination.end} of {pagination.total} accounts</span>
        <div aria-label="Account pagination" className={styles.pagination}>
          <label className={styles.pageSize}>Rows per page
            <select onChange={(event) => { setPageSize(Number(event.target.value) as AccountPageSize); viewportRef.current?.scrollTo({ top: 0 }); }} value={pageSize}>
              {accountPageSizes.map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
          <Button disabled={pagination.page <= 1} onClick={() => setPage(pagination.page - 1)} size="sm" variant="transparent">Previous</Button>
          <span>Page {pagination.page} of {pagination.pageCount}</span>
          <Button disabled={pagination.page >= pagination.pageCount} onClick={() => setPage(pagination.page + 1)} size="sm" variant="transparent">Next</Button>
        </div>
      </footer>
      {adding ? <AddProjectAccountsDialog accounts={available} onAdd={(accounts) => { void addAccounts(accounts); }} onClose={() => setAdding(false)} projectTitle={projectTitle} /> : null}
      {preview ? <ProjectAccountPreview projectId={projectId} account={preview} key={preview.id} onClose={() => setPreview(null)} /> : null}
    </section>
  );
}

export function ProjectTargetAccounts({ active, onAddToChat, projectId, projectTitle, refreshToken }: { active: boolean; onAddToChat?: AddToChat; projectId: string; projectTitle: string; refreshToken?: number }) {
  const [data, setData] = useState<ProjectAccountsResponse | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // First load when the tab becomes active; afterwards every discovery tick (`refreshToken`)
    // re-reads without dropping `data`, so the table keeps its columns, selection and page
    // while verified rows climb in (spec 2026-09-12 §3).
    if (!active) return;
    const request = new AbortController();
    fetch(`/api/projects/${encodeURIComponent(projectId)}/accounts`, { signal: request.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load project accounts");
        return ProjectAccountsResponseSchema.parse(await response.json());
      })
      .then((result) => { if (!request.signal.aborted) { setData(result); setError(false); } })
      .catch(() => { if (!request.signal.aborted && data === null) setError(true); });
    return () => request.abort();
    // `data` is deliberately not a dependency: it changes on every read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, attempt, projectId, refreshToken]);

  // Re-read the served lists after a membership write, without dropping `data`:
  // the table keeps its columns, selection and page while the pool catches up.
  async function reread() {
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/accounts`);
      if (!response.ok) throw new Error("Unable to load project accounts");
      setData(ProjectAccountsResponseSchema.parse(await response.json()));
    } catch {
      // The rows already hold what the write returned; a stale pool is the only cost.
    }
  }

  if (data) return (
    <WorkspaceProfileProvider profile={data.profile}>
      <ProjectAccountsTable data={data} onAddToChat={onAddToChat} onReread={() => { void reread(); }} projectId={projectId} projectTitle={projectTitle} />
    </WorkspaceProfileProvider>
  );
  return (
    <section aria-busy={!error} aria-label="Project target accounts" className={styles.surface}>
      <ProjectAccountsBreadcrumb projectTitle={projectTitle} />
      {error ? (
        <div className={styles.empty} role="alert">
          <h2>Unable to load target accounts</h2>
          <p>Please try again.</p>
          <Button onClick={() => { setError(false); setAttempt((current) => current + 1); }} size="md">Try again</Button>
        </div>
      ) : (
        <div className={styles.loadingRows} role="status">
          <span className="sr-only">Loading target accounts</span>
          {Array.from({ length: 8 }, (_, row) => <div aria-hidden="true" className={styles.loadingRow} key={row}>{Array.from({ length: 5 }, (_, cell) => <span className={styles.skeleton} key={cell} />)}</div>)}
        </div>
      )}
    </section>
  );
}
