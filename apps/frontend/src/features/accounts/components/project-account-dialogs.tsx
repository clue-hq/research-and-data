"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { DesignIcon } from "@/components/ui/design-icon";
import type { Account } from "../model/account";
import components from "./account-components.module.css";
import readability from "./account-readability.module.css";
import styles from "./project-accounts.module.css";

/** The account glyph a row shows when no logo asset exists (ruling S2). */
const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

function ProjectAccountDialog({ children, onClose, title }: {
  children: ReactNode;
  onClose: () => void;
  title: string;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      aria-label={title}
      className={`${styles.dialog} ${readability.uiRegular}`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      ref={dialogRef}
    >
      <header className={styles.dialogHeader}>
        <h2>{title}</h2>
        <button aria-label="Close account dialog" className={components.iconButton} onClick={onClose} type="button">
          <DesignIcon name="detail/x" size={12} />
        </button>
      </header>
      {children}
    </dialog>
  );
}

export function AddProjectAccountsDialog({ accounts, onAdd, onClose, projectTitle }: {
  accounts: Account[];
  onAdd: (accounts: Account[]) => void;
  onClose: () => void;
  projectTitle: string;
}) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const results = accounts.filter((account) => `${account.name} ${account.websiteUrl ?? ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return (
    <ProjectAccountDialog onClose={onClose} title="Add accounts to project">
      <form onSubmit={(event) => { event.preventDefault(); onAdd(accounts.filter(({ id }) => selected.has(id))); onClose(); }}>
        <div className={styles.dialogBody}>
          <p>Choose existing accounts to use in {projectTitle}.</p>
          <label className={`${components.input} ${styles.dialogSearch}`}>
            <DesignIcon name="search" size={12} />
            <input aria-label="Search available accounts" onChange={(event) => setSearch(event.target.value)} placeholder="Search accounts" type="search" value={search} />
          </label>
          <div className={styles.pickerList}>
            {results.map((account) => (
              <label className={styles.pickerRow} key={account.id}>
                <input
                  aria-label={`Add ${account.name}`}
                  checked={selected.has(account.id)}
                  onChange={() => setSelected((current) => {
                    const next = new Set(current);
                    if (next.has(account.id)) next.delete(account.id); else next.add(account.id);
                    return next;
                  })}
                  type="checkbox"
                />
                {/* unoptimized: the logo route is session-authenticated behind the BFF —
                    the Next image optimizer's server-side refetch carries no session cookie
                    and would 401 (the accounts table documents the same). */}
                <Image alt="" className="size-4 shrink-0 object-contain" height={16} src={account.logoPath ?? ACCOUNT_GLYPH_PATH} unoptimized={account.logoPath != null} width={16} />
                <span>{account.name}{account.websiteUrl ? <small>{new URL(account.websiteUrl).hostname}</small> : null}</span>
              </label>
            ))}
            {!results.length ? <p className="py-6 text-center">{accounts.length ? "No matching accounts." : "All available accounts are already in this project."}</p> : null}
          </div>
        </div>
        <footer className={styles.dialogFooter}>
          <Button onClick={onClose} size="md" type="button" variant="transparent">Cancel</Button>
          <Button disabled={!selected.size} size="md" type="submit">Add {selected.size || ""} {selected.size === 1 ? "account" : "accounts"}</Button>
        </footer>
      </form>
    </ProjectAccountDialog>
  );
}
