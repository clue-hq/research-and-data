"use client";

import { useState, type ReactNode } from "react";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { getAtPath } from "@clue/site-kit/editor-site";
import { richText } from "@clue/site-kit/rich";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import {
  InspectorField,
  InspectorHeader,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  InspectorTextArea,
} from "./inspector-primitives";
import { SiteArrangeSection, SiteHideSection } from "./site-arrange-section";
import { SiteHeaderPlacement } from "./site-header-placement";
import { SiteBoxPanel } from "./site-box-panel";
import { SiteButtonPanel } from "./site-button-panel";
import { SiteImagePanel } from "./site-image-panel";
import { SiteLinkRow } from "./site-link-row";
import { SiteTextPanel } from "./site-text-panel";
import { LayerList } from "./layer-list";
import styles from "./chat-shell.module.css";

export type SiteImageFieldRenderer = (field: FieldDescription, path: string, value: string) => ReactNode;

/**
 * Lane C / C5 (founder ruling: fields in the app): the site's dock. The frame describes the selected
 * section's fields as data (Contract 6 `FieldDescription`); this panel draws them with the existing
 * inspector primitives — the precedent is the custom-component props form in web-inspector.tsx — and
 * hands each committed value to the session (`set_props` to the frame, then one save). Layers come
 * from the app's own copy of the site. While the agent-run lock holds, the whole subtree is disabled
 * by a `display: contents` fieldset, exactly as the props form does it.
 */
export function SiteInspector({
  binding,
  renderImageField,
}: {
  binding: SiteInspectorBinding;
  renderImageField?: SiteImageFieldRenderer;
}) {
  const [contentOpen, setContentOpen] = useState(true);
  const [layersOpen, setLayersOpen] = useState(true);
  return (
    <aside aria-label="Website inspector" className={styles.inspector}>
      <div className={styles.inspectorRail}>
        <InspectorHeader elementActions={false} title={binding.title} />
        {binding.note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {binding.note}
          </p>
        ) : null}
        {binding.error ? (
          <p className={styles.inspectorStatusError} role="alert">
            {binding.error}
          </p>
        ) : null}
        {binding.element?.kind === "container" ? (
          // Plan 4: a box: Fill, Stroke, Layout and Arrange (with its content alignment), then Hide
          // for a header or footer part.
          <>
            <SiteBoxPanel binding={binding} key="box" mode="box" />
            <SiteHideSection binding={binding} key="hide" />
          </>
        ) : binding.element?.kind === "image" ? (
          // Plan 5: an image: Image (Replace), Fit, Alt text, Stroke, Arrange and Visibility.
          <SiteImagePanel binding={binding} key="image" renderImageField={renderImageField} />
        ) : binding.element ? (
          // Site element inspector: a selected text element is styled here; the section's content
          // fields come back when the section itself is selected. Keyed by the kind of selection, not
          // the element (founder 2026-10-19): moving between two texts keeps every group in place and
          // changes its values; each group resets its own per-element state.
          // A button (plan 3) adds its box's Fill, Stroke and Layout between its words and its link;
          // plan 4 adds Arrange and, for a header or footer part, Hide.
          <>
            <SiteTextPanel binding={binding} key="text" />
            {binding.element.kind === "button" && binding.element.box ? (
              <SiteButtonPanel binding={binding} key="button-box" />
            ) : null}
            <SiteLinkRow binding={binding} key="link" />
            <SiteArrangeSection binding={binding} key="arrange" />
            <SiteHideSection binding={binding} key="hide" />
          </>
        ) : binding.fields ? (
          // DESIGN REVIEW (DR4): the section label for a selected site section.
          <>
            <InspectorSection label="Content" onOpenChange={setContentOpen} open={contentOpen}>
              <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
                {binding.fields.length === 0 ? (
                  <p className={styles.inspectorFieldLabel}>This section has nothing to edit here.</p>
                ) : (
                  binding.fields.map((field) => (
                    <SiteFieldControl
                      disabled={binding.disabled}
                      field={field}
                      key={field.name}
                      onCommit={binding.onCommit}
                      path={field.name}
                      renderImageField={renderImageField}
                      values={binding.values}
                    />
                  ))
                )}
              </fieldset>
            </InspectorSection>
          </>
        ) : binding.sectionBox ? (
          // Founder 2026-10-19: a section's background (its own outermost box) shows the section-box
          // panel (plan 4, ruling R2): Fill and Stroke on the outer box, Layout and alignment on the inner.
          <SiteBoxPanel binding={binding} key="section" mode="section" />
        ) : null}
        {/* Plan 6 (ruling R12): the header's own placement, when the header itself is selected (the
            whole header shows only this and Layers: founder 2026-10-19). */}
        {!binding.element && !binding.sectionBox ? <SiteHeaderPlacement binding={binding} key="header" /> : null}
        <InspectorSection label="Layers" onOpenChange={setLayersOpen} open={layersOpen}>
          <LayerList>
            {binding.layers.map((row) => (
              <InspectorLayerRow
                active={row.active}
                depth={row.depth ?? 0}
                icon={row.icon}
                key={row.key}
                label={row.label}
                onClick={() => binding.onSelectLayer(row)}
              />
            ))}
          </LayerList>
        </InspectorSection>
      </div>
    </aside>
  );
}

function textOf(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

function SiteFieldControl({
  disabled,
  field,
  onCommit,
  path,
  renderImageField,
  values,
}: {
  disabled: boolean;
  field: FieldDescription;
  onCommit: (name: string, value: unknown) => void;
  path: string;
  renderImageField?: SiteImageFieldRenderer;
  values: Record<string, unknown> | null;
}) {
  const value = getAtPath(values, path);
  switch (field.kind) {
    case "text":
    case "link":
      return (
        <InspectorField label={field.label}>
          <InspectorInput ariaLabel={field.label} disabled={disabled} onCommitValue={(next) => onCommit(path, next)} value={textOf(value)} />
        </InspectorField>
      );
    case "textarea":
      return (
        <InspectorField label={field.label}>
          <InspectorTextArea ariaLabel={field.label} disabled={disabled} onCommitValue={(next) => onCommit(path, next)} value={textOf(value)} />
        </InspectorField>
      );
    case "richtext":
      // Rich text (plan 2, ruling R6): edited on the page, where its bold, links and styled words
      // are; a plain box here would lose them. Shown as its words.
      return (
        <InspectorField label={field.label}>
          <InspectorInput ariaLabel={field.label} readOnly value={richText(textOf(value))} />
          <p className={styles.inspectorFieldLabel}>Edit these words on the page.</p>
        </InspectorField>
      );
    case "number":
      return (
        <InspectorField label={field.label}>
          <InspectorInput
            ariaLabel={field.label}
            disabled={disabled}
            onCommitValue={(next) => {
              const parsed = Number(next);
              if (next.trim() !== "" && Number.isFinite(parsed)) onCommit(path, parsed);
            }}
            value={textOf(value)}
          />
        </InspectorField>
      );
    case "boolean":
      return (
        <label className={styles.checkboxRow}>
          <input
            aria-label={field.label}
            checked={value === true}
            disabled={disabled}
            onChange={(event) => onCommit(path, event.target.checked)}
            type="checkbox"
          />
          <span>{field.label}</span>
        </label>
      );
    case "select": {
      const options = field.options ?? [];
      return (
        <InspectorField label={field.label}>
          <InspectorSelect
            disabled={disabled}
            label={field.label}
            onChange={(label) => {
              const option = options.find((candidate) => candidate.label === label);
              if (option) onCommit(path, option.value);
            }}
            options={options.map((option) => option.label)}
            value={options.find((option) => option.value === value)?.label ?? ""}
          />
        </InspectorField>
      );
    }
    case "image":
      return renderImageField ? (
        renderImageField(field, path, textOf(value))
      ) : (
        <InspectorField label={field.label}>
          <InspectorInput ariaLabel={field.label} readOnly value={textOf(value)} />
        </InspectorField>
      );
    case "list": {
      const items = Array.isArray(value) ? value : [];
      // DESIGN REVIEW (DR6, plan Q2): repeating items are edited in place; adding or removing one
      // waits for a design.
      return (
        <>
          {items.map((_item, index) => (
            <div key={`${path}.${index}`}>
              <p className={styles.inspectorFieldLabel}>{`${field.label} ${index + 1}`}</p>
              {(field.item ?? []).map((child) => (
                <SiteFieldControl
                  disabled={disabled}
                  field={child}
                  key={child.name}
                  onCommit={onCommit}
                  path={`${path}.${index}.${child.name}`}
                  renderImageField={renderImageField}
                  values={values}
                />
              ))}
            </div>
          ))}
        </>
      );
    }
  }
}
