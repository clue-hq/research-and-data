"use client";

import { useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorInput, InspectorSection, InspectorSelect, SegmentedControl } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

const NO_PAGE = "Choose a page";
const DESTINATIONS: { label: string; value: "web" | "page" }[] = [
  { label: "Web address", value: "web" },
  { label: "Page on this site", value: "page" },
];
const OPEN_IN: { label: string; value: "same" | "new" }[] = [
  { label: "Same tab", value: "same" },
  { label: "New tab", value: "new" },
];

/**
 * The site element inspector's Link row (plan 2, spec §2): where the selected text links to — a page
 * of this site or a web address — and whether it opens in the same tab or a new one (plan 3, R8: the
 * mockup's layout). In rich text it links the
 * highlighted words (or the whole text) and can remove the link; a link that is part of the section
 * (a card's link, a menu link, a copied link) is changed where it lives. Where no link can be made the
 * row says why. Every change is one save.
 */
export function SiteLinkRow({ binding }: { binding: SiteInspectorBinding }) {
  const [open, setOpen] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  // Which control "Goes to" shows; until the marketer picks, the link's own kind decides.
  const [destination, setDestination] = useState<"web" | "page" | null>(null);
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
  const goesTo = destination ?? (current || (!state.href && binding.pages.length) ? "page" : "web");
  return (
    <InspectorSection label="Link" onOpenChange={setOpen} open={open}>
      <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
        <InspectorField label="Goes to">
          <SegmentedControl
            ariaLabel="Link goes to"
            disabled={binding.disabled}
            onChange={setDestination}
            options={DESTINATIONS}
            value={goesTo}
          />
        </InspectorField>
        {goesTo === "web" ? (
          <InspectorField label="Address">
            <InspectorInput
              ariaLabel="Link address"
              disabled={binding.disabled}
              onCommitValue={(value) => {
                if (value.trim()) commit({ href: value, newTab: state.newTab });
                else if (state.removable) commit(null);
              }}
              placeholder="https://…, #section or mailto:"
              value={state.href}
            />
          </InspectorField>
        ) : (
          <InspectorField label="Page">
            <InspectorSelect
              disabled={binding.disabled}
              label="A page of this site"
              onChange={(label) => {
                const page = binding.pages.find((candidate) => labelOf(candidate) === label);
                if (page) commit({ href: page.route, newTab: state.newTab });
              }}
              options={current ? binding.pages.map(labelOf) : [NO_PAGE, ...binding.pages.map(labelOf)]}
              value={current ? labelOf(current) : NO_PAGE}
            />
          </InspectorField>
        )}
        <InspectorField label="Open in">
          <SegmentedControl
            ariaLabel="Link opens in"
            disabled={binding.disabled || !state.href}
            onChange={(value) => commit({ href: state.href, newTab: value === "new" })}
            options={OPEN_IN}
            value={state.newTab ? "new" : "same"}
          />
        </InspectorField>
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
