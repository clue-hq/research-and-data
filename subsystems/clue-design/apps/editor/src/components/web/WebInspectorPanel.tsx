import React, { useState } from "react";

import {
  setNodeClassesOp,
  setNodePropsOp,
  type WebNode,
  type WebNodeProps,
  type WebOperation,
  type WebTheme
} from "@/engine/webDocuments";
import {
  bgColorFacet,
  directionFacet,
  displayFacet,
  gapFacet,
  paddingXFacet,
  paddingYFacet,
  textAlignFacet,
  textColorFacet,
  textSizeFacet,
  TEXT_SIZE_RAMP,
  SPACING_STEPS,
  type ClassFacet
} from "@/engine/webClassFacets";

/**
 * The Inspect-mode panel: reads the selected node from the loaded WebDoc and
 * exposes per-kind property controls plus a universal class escape hatch. Pure
 * presentation per docs/frontend-practices.md rule 2 — every control builds ONE
 * operation (a class rewrite via {@link ClassFacet}, or a whole-props edit) and
 * fires `applyOps`; the hook owns persistence, base-version, and 409/422.
 *
 * Solid vs derived: a facet control shows the parsed value when the utility is
 * present (solid) and "Default" otherwise (derived) — no computed-style
 * readback in v1, so an inherited value reads as Default until it's set here.
 */

interface WebInspectorPanelProps {
  node: WebNode | null;
  /** The page the node lives in — the `page_id` every op carries. */
  pageId: string;
  theme: WebTheme | null;
  applyOps: (operations: WebOperation[], intent?: string) => void;
  busy: boolean;
  /** Info note (409 reload) and inline error (422 diagnostic), surfaced in the
   * panel header. */
  note: string | null;
  error: string | null;
}

const TEXT_VARIANTS = ["display", "h1", "h2", "h3", "h4", "body", "small", "overline"];
const BUTTON_VARIANTS = ["primary", "secondary", "outline", "ghost", "link"];
const ALIGN_OPTIONS: { value: string; label: string }[] = [
  { value: "left", label: "Align left" },
  { value: "center", label: "Align center" },
  { value: "right", label: "Align right" },
  { value: "justify", label: "Justify" }
];

export function WebInspectorPanel({
  node,
  pageId,
  theme,
  applyOps,
  busy,
  note,
  error
}: WebInspectorPanelProps): React.ReactElement {
  if (!node) {
    return (
      <div className="web-insp-empty">
        <p className="web-insp-empty-title">Select an element on the canvas</p>
        <p className="web-empty-hint">
          Click any element in the preview to edit its text, color, and layout.
        </p>
      </div>
    );
  }

  return (
    <div className="web-insp">
      <header className="web-insp-head">
        <span className="web-insp-id">{node.id}</span>
        <span className="web-insp-kind">{node.kind}</span>
      </header>
      {note ? (
        <p className="web-insp-note" role="status">
          {note}
        </p>
      ) : null}
      {error ? (
        <p className="web-insp-error" role="alert">
          {error}
        </p>
      ) : null}

      {/* Field state (text inputs, textarea) is seeded from the node, so remount
          it when the selection changes. */}
      <WebInspectorBody
        key={node.id}
        node={node}
        pageId={pageId}
        theme={theme}
        applyOps={applyOps}
        busy={busy}
      />
    </div>
  );
}

interface BodyProps {
  node: WebNode;
  pageId: string;
  theme: WebTheme | null;
  applyOps: (operations: WebOperation[], intent?: string) => void;
  busy: boolean;
}

function WebInspectorBody({ node, pageId, theme, applyOps, busy }: BodyProps): React.ReactElement {
  const applyClasses = (facet: ClassFacet, value: string | null, intent: string) => {
    applyOps([setNodeClassesOp(pageId, node.id, facet.set(node.classes, value))], intent);
  };
  const applyProps = (props: WebNodeProps, intent: string) => {
    applyOps([setNodePropsOp(pageId, node.id, props)], intent);
  };

  return (
    <div className="web-insp-cards">
      {node.kind === "text" ? (
        <TextCard node={node} theme={theme} busy={busy} applyClasses={applyClasses} applyProps={applyProps} />
      ) : null}
      {node.kind === "button" ? (
        <ButtonCard node={node} busy={busy} applyProps={applyProps} />
      ) : null}
      {(node.kind === "container" || node.kind === "section") ? (
        <ContainerCard node={node} busy={busy} applyClasses={applyClasses} />
      ) : null}
      {node.kind === "image" ? <ImageCard node={node} busy={busy} applyProps={applyProps} /> : null}

      <ClassesCard node={node} pageId={pageId} busy={busy} applyOps={applyOps} />
    </div>
  );
}

// ── shared controls ──────────────────────────────────────────────────────────

function Card({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">{title}</h3>
      {children}
    </section>
  );
}

/** A facet-backed select whose empty option clears the family ("Default"). A
 * present-but-unknown value is added as an extra option so it still displays. */
function FacetSelect({
  label,
  value,
  options,
  disabled,
  onChange
}: {
  label: string;
  value: string | null;
  options: readonly string[];
  disabled: boolean;
  onChange: (value: string | null) => void;
}): React.ReactElement {
  const merged = value && !options.includes(value) ? [...options, value] : options;
  return (
    <label className="field web-insp-field">
      <span className="field-label">{label}</span>
      <select
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
      >
        <option value="">Default</option>
        {merged.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A plain (non-clearing) select for whole-props enums (variant). */
function PropSelect({
  label,
  value,
  options,
  disabled,
  onChange
}: {
  label: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  onChange: (value: string) => void;
}): React.ReactElement {
  return (
    <label className="field web-insp-field">
      <span className="field-label">{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

// ── per-kind cards ───────────────────────────────────────────────────────────

function TextCard({
  node,
  theme,
  busy,
  applyClasses,
  applyProps
}: {
  node: WebNode;
  theme: WebTheme | null;
  busy: boolean;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const variant = node.variant ?? "body";
  const content = node.content ?? "";
  const color = textColorFacet.parse(node.classes);
  const size = textSizeFacet.parse(node.classes);
  const align = textAlignFacet.parse(node.classes);
  const tokens = theme ? Object.entries(theme.tokens) : [];

  return (
    <Card title="Text">
      <PropSelect
        label="Style"
        value={variant}
        options={TEXT_VARIANTS}
        disabled={busy}
        onChange={(next) => applyProps({ kind: "text", variant: next, content }, "text_variant")}
      />

      <div className="field web-insp-field">
        <span className="field-label">Color</span>
        {tokens.length > 0 ? (
          <div className="web-swatch-grid" role="group" aria-label="Text color">
            {tokens.map(([token, cssColor]) => (
              <button
                key={token}
                type="button"
                title={token}
                aria-label={token}
                aria-pressed={color === token}
                disabled={busy}
                className={`web-swatch${color === token ? " is-selected" : ""}`}
                style={{ backgroundColor: cssColor }}
                onClick={() => applyClasses(textColorFacet, token, "text_color")}
              />
            ))}
            <button
              type="button"
              className={`web-swatch is-clear${color === null ? " is-selected" : ""}`}
              aria-label="Default color"
              title="Default"
              disabled={busy}
              onClick={() => applyClasses(textColorFacet, null, "text_color")}
            >
              ×
            </button>
          </div>
        ) : (
          <p className="web-insp-hint">No theme colors available.</p>
        )}
      </div>

      <FacetSelect
        label="Size"
        value={size}
        options={TEXT_SIZE_RAMP}
        disabled={busy}
        onChange={(next) => applyClasses(textSizeFacet, next, "text_size")}
      />

      <div className="field web-insp-field">
        <span className="field-label">Alignment</span>
        <div className="web-align-row" role="group" aria-label="Text alignment">
          {ALIGN_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-label={option.label}
              aria-pressed={align === option.value}
              disabled={busy}
              className={`web-align-btn${align === option.value ? " is-selected" : ""}`}
              onClick={() =>
                applyClasses(
                  textAlignFacet,
                  align === option.value ? null : option.value,
                  "text_align"
                )
              }
            >
              <AlignGlyph value={option.value} />
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function AlignGlyph({ value }: { value: string }): React.ReactElement {
  // Four horizontal rules whose x-offsets encode the alignment.
  const rows: Record<string, number[]> = {
    left: [0, 0, 0, 0],
    center: [1, 0, 1, 0],
    right: [2, 2, 2, 2],
    justify: [0, 0, 0, 0]
  };
  const offsets = rows[value] ?? [0, 0, 0, 0];
  const widths = value === "justify" ? [14, 14, 14, 14] : [14, 9, 12, 7];
  return (
    <svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true" focusable="false">
      {[0, 1, 2, 3].map((i) => (
        <rect
          key={i}
          x={offsets[i]}
          y={i * 3 + 0.5}
          width={widths[i]}
          height="1.5"
          rx="0.75"
          fill="currentColor"
        />
      ))}
    </svg>
  );
}

function ButtonCard({
  node,
  busy,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const label = node.label ?? "";
  const variant = node.variant ?? "primary";
  const [href, setHref] = useState(node.href ?? "");
  const newTab = node.new_tab ?? false;

  const commit = (patch: Partial<{ href: string; variant: string; newTab: boolean }>, intent: string) => {
    applyProps(
      {
        kind: "button",
        label,
        href: patch.href ?? href,
        variant: patch.variant ?? variant,
        new_tab: patch.newTab ?? newTab
      },
      intent
    );
  };

  return (
    <Card title="Button">
      <PropSelect
        label="Variant"
        value={variant}
        options={BUTTON_VARIANTS}
        disabled={busy}
        onChange={(next) => commit({ variant: next }, "button_variant")}
      />
      <label className="field web-insp-field">
        <span className="field-label">Link (href)</span>
        <input
          type="text"
          value={href}
          disabled={busy}
          onChange={(event) => setHref(event.target.value)}
          onBlur={() => {
            if (href !== (node.href ?? "")) {
              commit({ href }, "button_href");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="https://…"
        />
      </label>
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={newTab}
          disabled={busy}
          onChange={(event) => commit({ newTab: event.target.checked }, "button_new_tab")}
        />
        Open in a new tab
      </label>
    </Card>
  );
}

function ContainerCard({
  node,
  busy,
  applyClasses
}: {
  node: WebNode;
  busy: boolean;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
}): React.ReactElement {
  return (
    <Card title="Layout">
      <FacetSelect
        label="Display"
        value={displayFacet.parse(node.classes)}
        options={["flex", "grid", "block", "inline-flex", "hidden"]}
        disabled={busy}
        onChange={(next) => applyClasses(displayFacet, next, "display")}
      />
      <FacetSelect
        label="Direction"
        value={directionFacet.parse(node.classes)}
        options={["row", "col"]}
        disabled={busy}
        onChange={(next) => applyClasses(directionFacet, next, "direction")}
      />
      <FacetSelect
        label="Gap"
        value={gapFacet.parse(node.classes)}
        options={SPACING_STEPS}
        disabled={busy}
        onChange={(next) => applyClasses(gapFacet, next, "gap")}
      />
      <FacetSelect
        label="Padding X"
        value={paddingXFacet.parse(node.classes)}
        options={SPACING_STEPS}
        disabled={busy}
        onChange={(next) => applyClasses(paddingXFacet, next, "padding_x")}
      />
      <FacetSelect
        label="Padding Y"
        value={paddingYFacet.parse(node.classes)}
        options={SPACING_STEPS}
        disabled={busy}
        onChange={(next) => applyClasses(paddingYFacet, next, "padding_y")}
      />
    </Card>
  );
}

function ImageCard({
  node,
  busy,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const [alt, setAlt] = useState(node.alt ?? "");
  return (
    <Card title="Image">
      <label className="field web-insp-field">
        <span className="field-label">Alt text</span>
        <input
          type="text"
          value={alt}
          disabled={busy}
          onChange={(event) => setAlt(event.target.value)}
          onBlur={() => {
            if (alt !== (node.alt ?? "")) {
              applyProps(
                {
                  kind: "image",
                  asset_id: node.asset_id ?? "",
                  alt,
                  href: node.href ?? null,
                  new_tab: node.new_tab ?? false
                },
                "image_alt"
              );
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="Describe the image"
        />
      </label>
    </Card>
  );
}

/** The universal escape hatch: edit the whole class string directly. Seeded
 * from the node; commits the exact text via `set_node_classes` on Apply. */
function ClassesCard({
  node,
  pageId,
  busy,
  applyOps
}: {
  node: WebNode;
  pageId: string;
  busy: boolean;
  applyOps: (operations: WebOperation[], intent?: string) => void;
}): React.ReactElement {
  const [draft, setDraft] = useState(node.classes);
  const dirty = draft !== node.classes;
  return (
    <Card title="CSS classes">
      <p className="web-insp-hint">
        Escape hatch — edit the raw Tailwind classes. Anything the controls above
        don’t model is preserved here.
      </p>
      <textarea
        className="web-insp-classes"
        value={draft}
        disabled={busy}
        spellCheck={false}
        rows={3}
        onChange={(event) => setDraft(event.target.value)}
        aria-label="CSS classes"
      />
      <button
        type="button"
        className="btn btn-primary btn-sm"
        disabled={busy || !dirty}
        onClick={() => applyOps([setNodeClassesOp(pageId, node.id, draft)], "set_classes")}
      >
        Apply
      </button>
    </Card>
  );
}
