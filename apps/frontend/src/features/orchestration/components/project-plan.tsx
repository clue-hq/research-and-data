"use client";

import { useMemo, useRef, useState } from "react";
import Image from "next/image";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { selectedGift, stageLabels, type DirectMailState } from "@/features/direct-mail/model/direct-mail";
import type { WorkspaceController } from "../hooks/use-workspace";
import { person } from "../model/workspace";
import { accountRows, queryAccounts, selectedVisibleIds, type AccountQuery } from "../model/account-list";
import type { PreviewKind } from "./account-detail";
import s from "./workspace.module.css";

export function ProjectPlan({ controller, mail, open }: {
  controller: WorkspaceController;
  mail: DirectMailState | null;
  open: (id: string, preview?: PreviewKind) => void;
}) {
  const data = controller.data!;
  const [query, setQuery] = useState<AccountQuery>({ page: 1, pageSize: 25 });
  const [selected, setSelected] = useState<string[]>([]);
  const [assignTo, setAssignTo] = useState("");
  const [notice, setNotice] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => accountRows(data, mail), [data, mail]);
  const result = useMemo(() => queryAccounts(rows, query), [rows, query]);
  const selectedIds = selectedVisibleIds(selected, result.items);
  const selectedSet = new Set(selectedIds);
  const owners = data.people.filter((p) => p.canOwn).map((p) => ({ value: p.id, label: p.name }));
  const changeQuery = (patch: AccountQuery) => {
    setQuery((previous) => ({ ...previous, page: 1, ...patch }));
    setSelected([]);
    setNotice("");
    scroller.current?.scrollTo({ top: 0 });
  };
  const assign = async () => {
    const items = result.items.filter((row) => selectedSet.has(row.account.id)).map(({ account }) => ({ id: account.id, revision: account.revision }));
    const saved = await controller.run(() => controller.repository!.assignOwners(items, assignTo));
    if (saved) {
      setNotice(`${items.length} accounts assigned to ${person(data, assignTo).name}.`);
      setSelected([]);
    }
  };

  return (
    <div className={s.workspace}>
      <div className={s.toolbar}>
        <label className={s.search}>
          <Search size={15} aria-hidden="true" />
          <input aria-label="Search project accounts" placeholder="Search accounts" value={query.search ?? ""} onChange={(event) => changeQuery({ search: event.target.value })} />
        </label>
        <SelectField ariaLabel="Filter account status" className={s.select} value={query.status ?? "all"} onValueChange={(status) => changeQuery({ status })} options={[
          { value: "all", label: "All statuses" }, { value: "review", label: "Needs review" }, { value: "active", label: "In progress" },
          { value: "delivered", label: "Delivered" }, { value: "ready", label: "Research ready" }, { value: "research", label: "Research pending" }, { value: "canceled", label: "Canceled" },
        ]} />
        <SelectField ariaLabel="Filter account owner" className={s.select} value={query.ownerId ?? "all"} onValueChange={(ownerId) => changeQuery({ ownerId })} options={[{ value: "all", label: "All owners" }, ...owners]} />
        <div className={s.toolbarSpacer} />
        <SelectField ariaLabel="Sort accounts" className={s.select} value={query.sort ?? "priority"} onValueChange={(sort) => changeQuery({ sort: sort as AccountQuery["sort"] })} options={[
          { value: "priority", label: "Needs attention first" }, { value: "name", label: "Account name" }, { value: "fit", label: "Highest fit" },
        ]} />
      </div>
      {selectedIds.length ? <div className={s.selectionBar}>
        <span>{selectedIds.length} selected on this page</span>
        <SelectField ariaLabel="Assign selected accounts to" className={s.select} value={assignTo} disabled={controller.pending} onValueChange={setAssignTo} options={[{ value: "", label: "Choose owner" }, ...owners]} />
        <Button size="sm" variant="primary" disabled={!assignTo || controller.pending} onClick={() => void assign()}>{controller.pending ? "Assigning…" : "Assign owner"}</Button>
        <button className={s.textButton} onClick={() => setSelected([])} disabled={controller.pending}>Clear selection</button>
      </div> : notice ? <div className={s.notice} role="status">{notice}</div> : null}
      <div className={s.tableScroll} ref={scroller}>
        <table className={`${s.table} ${s.accountTable}`}>
          <caption className={s.srOnly}>Project accounts, research, gifts and connected artifacts</caption>
          <thead><tr>
            <th className={s.checkboxCell}><input type="checkbox" aria-label="Select all accounts on this page" checked={result.items.length > 0 && selectedIds.length === result.items.length} ref={(node) => { if (node) node.indeterminate = selectedIds.length > 0 && selectedIds.length < result.items.length; }} disabled={!result.items.length || controller.pending} onChange={(event) => setSelected(event.target.checked ? result.items.map(({ account }) => account.id) : [])} /></th>
            <th>Account</th><th>Owner</th><th>Research</th><th>Direct mail</th><th>Artifacts</th>
          </tr></thead>
          <tbody>{result.items.map(({ account, mailer, artifacts, status }) => {
            const gift = mailer ? mailer.approval?.gift ?? selectedGift(mailer) : null;
            return <tr key={account.id} data-selected={selectedSet.has(account.id) || undefined}>
              <td className={s.checkboxCell}><input type="checkbox" aria-label={`Select ${account.name}`} checked={selectedSet.has(account.id)} disabled={controller.pending} onChange={(event) => setSelected(event.target.checked ? [...selectedIds, account.id] : selectedIds.filter((id) => id !== account.id))} /></td>
              <td><button className={s.accountButton} onClick={() => open(account.id)}>{account.name}</button><p className={s.caption}>{account.industry}</p></td>
              <td><span>{person(data, account.ownerId).name}</span><p className={s.caption}>{account.territory}</p></td>
              <td>{account.researchStatus === "ready" ? <button className={s.textButton} onClick={() => open(account.id)}>Ready <span className={s.caption}>· {account.fit} fit</span></button> : <span className={s.muted}>Pending</span>}</td>
              <td>{mailer ? <button className={s.giftCell} onClick={() => open(account.id, "gift")} aria-label={`Preview gift for ${account.name}`}>
                {gift ? <Image src={gift.image} alt="" className={s.giftThumb} width={32} height={32} unoptimized /> : null}
                <span><span className={s.truncate}>{gift?.name ?? "Choose a gift"}</span><span className={s.caption} data-attention={status === "address" || status === "review" || undefined}>{status === "address" ? "Address needed" : stageLabels[mailer.stage]}</span></span>
              </button> : <span className={s.muted}>{account.mailerId && !mail ? "Loading…" : "Not started"}</span>}</td>
              <td>{artifacts.length ? <button className={s.assetLink} onClick={() => open(account.id, "page")} aria-label={`Preview artifacts for ${account.name}`}>{artifacts.length} {artifacts.length === 1 ? "asset" : "assets"}</button> : <span className={s.muted}>—</span>}</td>
            </tr>;
          })}</tbody>
        </table>
        {!result.items.length ? <div className={s.empty}><p>No accounts match these filters.</p><button className={s.textButton} onClick={() => changeQuery({ search: "", ownerId: "all", status: "all" })}>Clear filters</button></div> : null}
      </div>
      <footer className={s.pagination}>
        <span>{result.total ? `${((result.page - 1) * result.pageSize + 1).toLocaleString()}–${Math.min(result.page * result.pageSize, result.total).toLocaleString()}` : "0"} of {result.total.toLocaleString()} accounts</span>
        <div className={s.paginationControls}>
          <SelectField ariaLabel="Accounts per page" className={s.pageSize} value={String(result.pageSize)} onValueChange={(value) => changeQuery({ pageSize: Number(value) })} options={[25, 50, 100].map((size) => ({ value: String(size), label: `${size} per page` }))} />
          <Button variant="transparent" size="sm" disabled={result.page <= 1 || controller.pending} onClick={() => changeQuery({ page: result.page - 1 })}>Previous</Button>
          <span className={s.pageNumber}>{result.page} / {result.pages}</span>
          <Button variant="transparent" size="sm" disabled={result.page >= result.pages || controller.pending} onClick={() => changeQuery({ page: result.page + 1 })}>Next</Button>
        </div>
      </footer>
    </div>
  );
}
