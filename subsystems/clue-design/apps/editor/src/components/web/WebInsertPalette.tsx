"use client";

import React, { useEffect, useRef, useState } from "react";

import type {
  CustomComponentCatalogItem,
  InsertableKind
} from "@/engine/webDocuments";

/**
 * The Inspect-rail "Add" affordance: a button that opens a small menu of
 * insertables. A plain-node choice calls {@link WebInsertPaletteProps.onInsert}
 * (the shell builds + applies the insert_node op); "Image…" calls
 * {@link WebInsertPaletteProps.onInsertImage} (the shell opens the asset drawer
 * in insert mode). Pure UI — placement + op shaping live in the shell/engine.
 */

interface WebInsertPaletteProps {
  onInsert: (kind: InsertableKind) => void;
  onInsertImage: () => void;
  onInsertCustomComponent: (component: CustomComponentCatalogItem) => void;
  customComponents: CustomComponentCatalogItem[];
  customComponentsStatus: "idle" | "loading" | "ready" | "error";
  customComponentsUnavailableReason: string | null;
  disabled: boolean;
}

/** The menu order — basics, then Tier-2 components. "image" is handled
 * separately (it opens the drawer), so it carries no `kind` here. */
const INSERTABLES: { kind: InsertableKind; label: string }[] = [
  { kind: "section", label: "Section" },
  { kind: "row", label: "Row" },
  { kind: "column", label: "Column" },
  { kind: "text", label: "Text" },
  { kind: "button", label: "Button" },
  { kind: "icon", label: "Icon" }
];

const COMPONENT_INSERTABLES: { kind: InsertableKind; label: string }[] = [
  { kind: "dialog", label: "Dialog" },
  { kind: "accordion", label: "Accordion" },
  { kind: "marquee", label: "Marquee" },
  { kind: "nav_menu", label: "Nav menu" },
  { kind: "carousel", label: "Carousel" },
  { kind: "tabs", label: "Tabs" },
  { kind: "embed", label: "Embed" }
];

export function WebInsertPalette({
  onInsert,
  onInsertImage,
  onInsertCustomComponent,
  customComponents,
  customComponentsStatus,
  customComponentsUnavailableReason,
  disabled
}: WebInsertPaletteProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close the menu on an outside click or Escape.
  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const choose = (kind: InsertableKind) => {
    setOpen(false);
    onInsert(kind);
  };

  return (
    <div className="web-insert-palette" ref={rootRef}>
      <button
        type="button"
        className="btn btn-secondary btn-sm web-insert-add"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="web-insert-plus" aria-hidden="true">
          +
        </span>
        Add
      </button>
      {open ? (
        <div className="web-insert-menu" role="menu">
          {INSERTABLES.map((item) => (
            <button
              key={item.kind}
              type="button"
              role="menuitem"
              className="web-insert-item"
              onClick={() => choose(item.kind)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            role="menuitem"
            className="web-insert-item"
            onClick={() => {
              setOpen(false);
              onInsertImage();
            }}
          >
            Image…
          </button>
          <div className="web-insert-sep" role="separator" />
          {COMPONENT_INSERTABLES.map((item) => (
            <button
              key={item.kind}
              type="button"
              role="menuitem"
              className="web-insert-item"
              onClick={() => choose(item.kind)}
            >
              {item.label}
            </button>
          ))}
          <div className="web-insert-sep" role="separator" />
          <div role="group" aria-labelledby="web-insert-custom-components-label">
            <div
              id="web-insert-custom-components-label"
              className="web-insert-menu-label"
            >
              Custom components
            </div>
            {customComponentsStatus === "loading" ? (
              <span className="web-insert-empty" role="status">
                Loading custom components…
              </span>
            ) : customComponentsUnavailableReason ? (
              <span className="web-insert-empty">
                {customComponentsUnavailableReason}
              </span>
            ) : customComponentsStatus === "error" ? (
              <span className="web-insert-empty" role="alert">
                Custom components could not be loaded.
              </span>
            ) : customComponents.length === 0 ? (
              <span className="web-insert-empty">
                No compiled custom components.
              </span>
            ) : (
              customComponents.map((component) => (
                <button
                  key={component.latestArtifact.artifact_id}
                  type="button"
                  role="menuitem"
                  className="web-insert-item web-insert-custom"
                  aria-label={`Insert ${component.latestArtifact.manifest.meta.name} custom component`}
                  title={component.latestArtifact.manifest.meta.description}
                  onClick={() => {
                    setOpen(false);
                    onInsertCustomComponent(component);
                  }}
                >
                  <span>{component.latestArtifact.manifest.meta.name}</span>
                  <small>{component.latestArtifact.manifest.meta.description}</small>
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
