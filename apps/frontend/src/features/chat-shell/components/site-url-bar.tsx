"use client";

import { ArrowLeftIcon, ArrowRightIcon, RotateCwIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { SiteUrlBinding } from "@/features/site-editor/model/site-pages";
import styles from "./chat-shell.module.css";

/**
 * DESIGN REVIEW (DR3): the browser-style URL toolbar (founder ruling 2026-10-11): back, forward, the
 * existing device menu, the current route — editable to jump — and reload. A route the site has no
 * page for puts the current route back and says nothing (plan Q6 (a); W3.3 bars new failure UI).
 */
export function SiteUrlBar({ binding, deviceMenu }: { binding: SiteUrlBinding; deviceMenu: ReactNode }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null) binding.go(draft);
    setDraft(null);
  };
  return (
    <div className={styles.siteUrlBar}>
      <button aria-label="Back" className={styles.deviceButton} disabled={!binding.canBack} onClick={binding.back} type="button">
        <ArrowLeftIcon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
      </button>
      <button aria-label="Forward" className={styles.deviceButton} disabled={!binding.canForward} onClick={binding.forward} type="button">
        <ArrowRightIcon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
      </button>
      <div className={styles.siteUrlField}>
        {deviceMenu}
        <input
          aria-label="Page address"
          className={styles.siteUrlInput}
          onBlur={commit}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
            if (event.key === "Escape") setDraft(null);
          }}
          spellCheck={false}
          value={draft ?? binding.route}
        />
        <button aria-label="Reload page" className={styles.deviceButton} onClick={binding.reload} type="button">
          <RotateCwIcon absoluteStrokeWidth aria-hidden="true" size={14} strokeWidth={1.25} />
        </button>
      </div>
    </div>
  );
}
