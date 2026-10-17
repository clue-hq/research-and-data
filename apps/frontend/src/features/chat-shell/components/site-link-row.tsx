"use client";

import { useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorInput, InspectorSection, InspectorSelect } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

const NO_PAGE = "Not a page of this site";

/**
 * The site element inspector's Link row (plan 2, spec §2): where the selected text links to — a page
 * of this site or a web address — and whether it opens in a new tab. In rich text it links the
 * highlighted words (or the whole text) and can remove the link; a link that is part of the section
 * (a card's link, a menu link, a copied link) is changed where it lives. Where no link can be made the
 * row says why. Every change is one save.
 */
export function SiteLinkRow({ binding }: { binding: SiteInspectorBinding }) {
  const [open, setOpen] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const state = binding.linkState;
  const commit = (change: { href: string; newTab: boolean } | null) => {
    if (binding.disabled) return;
    setNote(binding.onLinkCommit(change));
  };
  if (state.kind === "none") {
    return (
      <InspectorSection label="Link" onOpenChange={setOpen} open={open}>
        <p className={styles.inspectorStatusNote} role="status">
          {state.reason}
        </p>
      </InspectorSection>
    );
  }
  const labelOf = (page: { route: string; title: string }) => (page.title === page.route ? page.route : `${page.title} (${page.route})`);
  const current = binding.pages.find((page) => page.route === state.href);
  return (
    <InspectorSection label="Link" onOpenChange={setOpen} open={open}>
      <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
        <InspectorField label="Goes to">
          <InspectorInput
            ariaLabel="Link address"
            disabled={binding.disabled}
            onCommitValue={(value) => {
              if (value.trim()) commit({ href: value, newTab: state.newTab });
              else if (state.removable) commit(null);
            }}
            placeholder="A page like /analysis, or https://…"
            value={state.href}
          />
        </InspectorField>
        <InspectorField label="Page">
          <InspectorSelect
            disabled={binding.disabled}
            label="A page of this site"
            onChange={(label) => {
              const page = binding.pages.find((candidate) => labelOf(candidate) === label);
              if (page) commit({ href: page.route, newTab: state.newTab });
            }}
            options={[NO_PAGE, ...binding.pages.map(labelOf)]}
            value={current ? labelOf(current) : NO_PAGE}
          />
        </InspectorField>
        <label className={styles.checkboxRow}>
          <input
            aria-label="Open in a new tab"
            checked={state.newTab}
            disabled={binding.disabled || !state.href}
            onChange={(event) => commit({ href: state.href, newTab: event.target.checked })}
            type="checkbox"
          />
          <span>Open in a new tab</span>
        </label>
        {state.removable ? (
          <button className={styles.inspectorControl} disabled={binding.disabled} onClick={() => commit(null)} type="button">
            Remove link
          </button>
        ) : null}
        {state.shared ? (
          <p className={styles.inspectorStatusNote} role="status">
            Other links in this section go to the same address, so changing it changes them too.
          </p>
        ) : null}
        {note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {note}
          </p>
        ) : null}
      </fieldset>
    </InspectorSection>
  );
}
