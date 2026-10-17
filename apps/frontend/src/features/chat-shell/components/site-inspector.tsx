"use client";

import { useState, type ReactNode } from "react";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { getAtPath } from "@clue/site-kit/editor-site";
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
import { SiteTextPanel } from "./site-text-panel";
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
        {binding.element ? (
          // Site element inspector: a selected text element is styled here; the section's content
          // fields come back when the section itself is selected. Keyed by the selection, so each
          // element starts with fresh drafts.
          <SiteTextPanel binding={binding} key={binding.selectionKey} />
        ) : binding.fields ? (
          // DESIGN REVIEW (DR4): the section label for a selected site section.
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
        ) : null}
        <InspectorSection label="Layers" onOpenChange={setLayersOpen} open={layersOpen}>
          <div className={styles.layerList}>
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
          </div>
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
