import React, { useState } from "react";

import {
  buildWebButtonProps,
  classifyEmbedUrl,
  duplicateSubtree,
  insertNodeOp,
  moveNodeOp,
  parentOfInPage,
  removeNodeOp,
  setNodeClassesOp,
  setNodePropsOp,
  webNodeButtonAction,
  type WebButtonAction,
  type WebDialogOption,
  type WebNode,
  type WebNodeProps,
  type WebOperation,
  type WebPageSummary,
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
  /** The full page summary — the sibling/parent lookup the header's
   * reorder/duplicate/delete actions need. */
  page: WebPageSummary | null;
  theme: WebTheme | null;
  /** Every dialog component in the document — the button command form's target
   * list. */
  dialogs: WebDialogOption[];
  /** Open/close a dialog component in the preview (component card preview). */
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  /** Select a node in the preview (button command form's "Select dialog"). */
  selectNode: (nodeId: string) => void;
  /** Open the asset drawer to replace the selected image's asset. */
  onReplaceImage: (nodeId: string) => void;
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
  page,
  theme,
  dialogs,
  previewComponent,
  selectNode,
  onReplaceImage,
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
        {page ? <NodeActionRow node={node} page={page} busy={busy} applyOps={applyOps} /> : null}
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
        dialogs={dialogs}
        previewComponent={previewComponent}
        selectNode={selectNode}
        onReplaceImage={onReplaceImage}
        applyOps={applyOps}
        busy={busy}
      />
    </div>
  );
}

/** The inspector header's compact structural actions: move within the same
 * parent (↑/↓, disabled at the ends), Duplicate (deep-copy + remint after the
 * original), Delete (remove_node; disabled for the page root). */
function NodeActionRow({
  node,
  page,
  busy,
  applyOps
}: {
  node: WebNode;
  page: WebPageSummary;
  busy: boolean;
  applyOps: (operations: WebOperation[], intent?: string) => void;
}): React.ReactElement {
  const isRoot = node.id === (page.root ?? "root");
  const parent = parentOfInPage(page, node.id);
  const siblings = parent?.children ?? [];
  const index = siblings.indexOf(node.id);
  const canMoveUp = !busy && !isRoot && parent != null && index > 0;
  const canMoveDown = !busy && !isRoot && parent != null && index >= 0 && index < siblings.length - 1;
  const canDuplicate = !busy && !isRoot && parent != null;
  const canDelete = !busy && !isRoot;

  const move = (delta: number) => {
    if (!parent) {
      return;
    }
    applyOps([moveNodeOp(page.id, node.id, parent.id, index + delta)], "reorder_node");
  };
  const duplicate = () => {
    if (!parent) {
      return;
    }
    const copy = duplicateSubtree(page, node.id);
    if (copy) {
      applyOps(
        [insertNodeOp(page.id, parent.id, index + 1, copy.nodes, copy.root)],
        "duplicate_node"
      );
    }
  };
  const remove = () => applyOps([removeNodeOp(page.id, node.id)], "delete_node");

  return (
    <div className="web-insp-actions" role="group" aria-label="Node actions">
      <button
        type="button"
        className="web-insp-action"
        aria-label="Move up"
        title="Move up"
        disabled={!canMoveUp}
        onClick={() => move(-1)}
      >
        ↑
      </button>
      <button
        type="button"
        className="web-insp-action"
        aria-label="Move down"
        title="Move down"
        disabled={!canMoveDown}
        onClick={() => move(1)}
      >
        ↓
      </button>
      <button
        type="button"
        className="web-insp-action"
        aria-label="Duplicate"
        title="Duplicate"
        disabled={!canDuplicate}
        onClick={duplicate}
      >
        ⧉
      </button>
      <button
        type="button"
        className="web-insp-action is-danger"
        aria-label="Delete"
        title="Delete"
        disabled={!canDelete}
        onClick={remove}
      >
        🗑
      </button>
    </div>
  );
}

interface BodyProps {
  node: WebNode;
  pageId: string;
  theme: WebTheme | null;
  dialogs: WebDialogOption[];
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  selectNode: (nodeId: string) => void;
  onReplaceImage: (nodeId: string) => void;
  applyOps: (operations: WebOperation[], intent?: string) => void;
  busy: boolean;
}

function WebInspectorBody({
  node,
  pageId,
  theme,
  dialogs,
  previewComponent,
  selectNode,
  onReplaceImage,
  applyOps,
  busy
}: BodyProps): React.ReactElement {
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
        <ButtonCard
          node={node}
          busy={busy}
          dialogs={dialogs}
          selectNode={selectNode}
          applyProps={applyProps}
        />
      ) : null}
      {node.kind === "component" ? (
        <ComponentCard
          node={node}
          busy={busy}
          previewComponent={previewComponent}
          applyProps={applyProps}
        />
      ) : null}
      {(node.kind === "container" || node.kind === "section") ? (
        <ContainerCard node={node} busy={busy} applyClasses={applyClasses} />
      ) : null}
      {node.kind === "image" ? (
        <ImageCard
          node={node}
          busy={busy}
          applyProps={applyProps}
          onReplaceImage={onReplaceImage}
        />
      ) : null}
      {node.kind === "embed" ? <EmbedCard node={node} busy={busy} applyProps={applyProps} /> : null}

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

const BUTTON_ACTIONS: { value: WebButtonAction; label: string }[] = [
  { value: "link", label: "Link" },
  { value: "show_modal", label: "Open dialog" },
  { value: "close", label: "Close dialog" }
];

/** The display label for a dialog target — its node id plus authored name. */
function dialogOptionLabel(dialog: WebDialogOption): string {
  return dialog.name ? `${dialog.id} · ${dialog.name}` : dialog.id;
}

function ButtonCard({
  node,
  busy,
  dialogs,
  selectNode,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  dialogs: WebDialogOption[];
  selectNode: (nodeId: string) => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const label = node.label ?? "";
  const variant = node.variant ?? "primary";
  const newTab = node.new_tab ?? false;
  const [href, setHref] = useState(node.href ?? "");
  // Action + target are local so the UI can switch to a dialog action and show
  // its empty state even before a target exists to commit against.
  const [action, setAction] = useState<WebButtonAction>(webNodeButtonAction(node));
  const [target, setTarget] = useState<string>(node.command_target ?? dialogs[0]?.id ?? "");

  // Build the whole-props payload from the current fields, overriding one at a
  // time. A dialog action with no target can't form a valid command — skip the
  // commit (the empty state explains why).
  const commit = (
    over: Partial<{
      action: WebButtonAction;
      target: string;
      variant: string;
      href: string;
      newTab: boolean;
    }>,
    intent: string
  ) => {
    const nextAction = over.action ?? action;
    const nextTarget = over.target ?? target;
    if (nextAction !== "link" && !nextTarget) {
      return;
    }
    applyProps(
      buildWebButtonProps({
        action: nextAction,
        label,
        variant: over.variant ?? variant,
        href: over.href ?? href,
        new_tab: over.newTab ?? newTab,
        command_target: nextTarget
      }),
      intent
    );
  };

  const onActionChange = (next: WebButtonAction) => {
    setAction(next);
    if (next === "link") {
      commit({ action: "link" }, "button_action");
      return;
    }
    const nextTarget = target || dialogs[0]?.id || "";
    setTarget(nextTarget);
    commit({ action: next, target: nextTarget }, "button_action");
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
      <PropSelect
        label="Action"
        value={action}
        options={BUTTON_ACTIONS.map((choice) => choice.value)}
        disabled={busy}
        onChange={(next) => onActionChange(next as WebButtonAction)}
      />

      {action === "link" ? (
        <>
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
        </>
      ) : dialogs.length === 0 ? (
        <p className="web-insp-hint">No dialogs in this page yet</p>
      ) : (
        <>
          <label className="field web-insp-field">
            <span className="field-label">Dialog</span>
            <select
              value={target}
              disabled={busy}
              onChange={(event) => {
                setTarget(event.target.value);
                commit({ target: event.target.value }, "button_command_target");
              }}
            >
              {dialogs.map((dialog) => (
                <option key={dialog.id} value={dialog.id}>
                  {dialogOptionLabel(dialog)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy || !target}
            onClick={() => {
              if (target) {
                selectNode(target);
              }
            }}
          >
            Select dialog
          </button>
        </>
      )}
    </Card>
  );
}

const MARQUEE_DIRECTIONS = ["left", "right"];
const MARQUEE_SPEED_MIN = 5;
const MARQUEE_SPEED_MAX = 120;

function clampMarqueeSpeed(value: number): number {
  if (Number.isNaN(value)) {
    return MARQUEE_SPEED_MIN;
  }
  return Math.min(MARQUEE_SPEED_MAX, Math.max(MARQUEE_SPEED_MIN, value));
}

const COMPONENT_TITLES: Record<string, string> = {
  dialog: "Dialog",
  accordion: "Accordion",
  marquee: "Marquee",
  nav_menu: "Nav menu",
  carousel: "Carousel",
  tabs: "Tabs"
};

const CAROUSEL_AUTOPLAY_MIN = 2;
const CAROUSEL_AUTOPLAY_MAX = 60;

function ComponentCard({
  node,
  busy,
  previewComponent,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const component = node.component ?? "";
  const title = COMPONENT_TITLES[component] ?? "Component";

  if (component === "dialog") {
    return (
      <DialogComponentCard
        node={node}
        busy={busy}
        title={title}
        previewComponent={previewComponent}
        applyProps={applyProps}
      />
    );
  }
  if (component === "accordion") {
    return <AccordionComponentCard node={node} busy={busy} title={title} applyProps={applyProps} />;
  }
  if (component === "marquee") {
    return <MarqueeComponentCard node={node} busy={busy} title={title} applyProps={applyProps} />;
  }
  if (component === "carousel") {
    return <CarouselComponentCard node={node} busy={busy} title={title} applyProps={applyProps} />;
  }
  if (component === "tabs") {
    return <TabsComponentCard node={node} busy={busy} title={title} applyProps={applyProps} />;
  }
  if (component === "nav_menu") {
    return (
      <Card title={title}>
        <p className="web-insp-hint">
          Items are this component’s children — select them in the canvas.
        </p>
      </Card>
    );
  }
  return (
    <Card title={title}>
      <p className="web-insp-hint">This component has no editable properties.</p>
    </Card>
  );
}

function DialogComponentCard({
  node,
  busy,
  title,
  previewComponent,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  title: string;
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const [ariaLabel, setAriaLabel] = useState(node.aria_label ?? "");
  const commitAriaLabel = () => {
    if (ariaLabel === (node.aria_label ?? "")) {
      return;
    }
    const trimmed = ariaLabel.trim();
    applyProps(
      trimmed
        ? { kind: "component", component: "dialog", aria_label: trimmed }
        : { kind: "component", component: "dialog" },
      "component_aria_label"
    );
  };
  return (
    <Card title={title}>
      <label className="field web-insp-field">
        <span className="field-label">ARIA label</span>
        <input
          type="text"
          value={ariaLabel}
          disabled={busy}
          onChange={(event) => setAriaLabel(event.target.value)}
          onBlur={commitAriaLabel}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="Describe the dialog (optional)"
        />
      </label>
      <div className="web-insp-field">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy}
          onClick={() => previewComponent(node.id, "open")}
        >
          Preview open
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy}
          onClick={() => previewComponent(node.id, "close")}
        >
          Close preview
        </button>
      </div>
    </Card>
  );
}

function AccordionComponentCard({
  node,
  busy,
  title,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  title: string;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const singleOpen = node.single_open ?? false;
  const [defaultOpen, setDefaultOpen] = useState(
    typeof node.default_open === "number" ? String(node.default_open) : ""
  );

  const commit = (over: Partial<{ singleOpen: boolean; defaultOpen: string }>, intent: string) => {
    const nextDefault = over.defaultOpen ?? defaultOpen;
    const parsed = nextDefault.trim() === "" ? null : Number.parseInt(nextDefault, 10);
    applyProps(
      parsed != null && !Number.isNaN(parsed)
        ? {
            kind: "component",
            component: "accordion",
            single_open: over.singleOpen ?? singleOpen,
            default_open: parsed
          }
        : { kind: "component", component: "accordion", single_open: over.singleOpen ?? singleOpen },
      intent
    );
  };

  return (
    <Card title={title}>
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={singleOpen}
          disabled={busy}
          onChange={(event) => commit({ singleOpen: event.target.checked }, "accordion_single_open")}
        />
        Only one panel open at a time
      </label>
      <label className="field web-insp-field">
        <span className="field-label">Default open panel</span>
        <input
          type="number"
          min={0}
          value={defaultOpen}
          disabled={busy}
          onChange={(event) => setDefaultOpen(event.target.value)}
          onBlur={() => {
            const current =
              typeof node.default_open === "number" ? String(node.default_open) : "";
            if (defaultOpen !== current) {
              commit({ defaultOpen }, "accordion_default_open");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="None"
        />
      </label>
    </Card>
  );
}

function MarqueeComponentCard({
  node,
  busy,
  title,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  title: string;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const speed = typeof node.speed_s === "number" ? node.speed_s : MARQUEE_SPEED_MIN;
  const direction: "left" | "right" = node.direction === "right" ? "right" : "left";
  const pauseOnHover = node.pause_on_hover ?? false;
  const [speedDraft, setSpeedDraft] = useState(String(speed));

  const commit = (
    over: Partial<{ speed: number; direction: "left" | "right"; pauseOnHover: boolean }>,
    intent: string
  ) => {
    applyProps(
      {
        kind: "component",
        component: "marquee",
        speed_s: over.speed ?? speed,
        direction: over.direction ?? direction,
        pause_on_hover: over.pauseOnHover ?? pauseOnHover
      },
      intent
    );
  };

  return (
    <Card title={title}>
      <label className="field web-insp-field">
        <span className="field-label">Speed (seconds)</span>
        <input
          type="number"
          min={MARQUEE_SPEED_MIN}
          max={MARQUEE_SPEED_MAX}
          value={speedDraft}
          disabled={busy}
          onChange={(event) => setSpeedDraft(event.target.value)}
          onBlur={() => {
            const clamped = clampMarqueeSpeed(Number.parseFloat(speedDraft));
            setSpeedDraft(String(clamped));
            if (clamped !== speed) {
              commit({ speed: clamped }, "marquee_speed");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
        />
      </label>
      <PropSelect
        label="Direction"
        value={direction}
        options={MARQUEE_DIRECTIONS}
        disabled={busy}
        onChange={(next) => commit({ direction: next as "left" | "right" }, "marquee_direction")}
      />
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={pauseOnHover}
          disabled={busy}
          onChange={(event) => commit({ pauseOnHover: event.target.checked }, "marquee_pause_on_hover")}
        />
        Pause on hover
      </label>
    </Card>
  );
}

function CarouselComponentCard({
  node,
  busy,
  title,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  title: string;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const showArrows = node.show_arrows ?? true;
  const [autoplay, setAutoplay] = useState(
    typeof node.autoplay_s === "number" ? String(node.autoplay_s) : ""
  );

  const commit = (over: Partial<{ showArrows: boolean; autoplay: string }>, intent: string) => {
    const nextAutoplay = over.autoplay ?? autoplay;
    const trimmed = nextAutoplay.trim();
    let parsed: number | undefined;
    if (trimmed !== "") {
      const value = Number.parseInt(trimmed, 10);
      if (!Number.isNaN(value)) {
        parsed = Math.min(CAROUSEL_AUTOPLAY_MAX, Math.max(CAROUSEL_AUTOPLAY_MIN, value));
      }
    }
    applyProps(
      parsed != null
        ? {
            kind: "component",
            component: "carousel",
            show_arrows: over.showArrows ?? showArrows,
            autoplay_s: parsed
          }
        : { kind: "component", component: "carousel", show_arrows: over.showArrows ?? showArrows },
      intent
    );
  };

  return (
    <Card title={title}>
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={showArrows}
          disabled={busy}
          onChange={(event) => commit({ showArrows: event.target.checked }, "carousel_show_arrows")}
        />
        Show arrows
      </label>
      <label className="field web-insp-field">
        <span className="field-label">Autoplay (seconds)</span>
        <input
          type="number"
          min={CAROUSEL_AUTOPLAY_MIN}
          max={CAROUSEL_AUTOPLAY_MAX}
          value={autoplay}
          disabled={busy}
          onChange={(event) => setAutoplay(event.target.value)}
          onBlur={() => {
            const current = typeof node.autoplay_s === "number" ? String(node.autoplay_s) : "";
            if (autoplay !== current) {
              commit({ autoplay }, "carousel_autoplay");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="Off"
        />
      </label>
    </Card>
  );
}

function TabsComponentCard({
  node,
  busy,
  title,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  title: string;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const [defaultTab, setDefaultTab] = useState(
    typeof node.default_tab === "number" ? String(node.default_tab) : "0"
  );
  const commit = () => {
    const parsed = Number.parseInt(defaultTab.trim(), 10);
    const value = Number.isNaN(parsed) ? 0 : Math.max(0, parsed);
    setDefaultTab(String(value));
    if (value !== (node.default_tab ?? 0)) {
      applyProps({ kind: "component", component: "tabs", default_tab: value }, "tabs_default_tab");
    }
  };
  return (
    <Card title={title}>
      <label className="field web-insp-field">
        <span className="field-label">Default tab</span>
        <input
          type="number"
          min={0}
          value={defaultTab}
          disabled={busy}
          onChange={(event) => setDefaultTab(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
        />
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
  applyProps,
  onReplaceImage
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
  onReplaceImage: (nodeId: string) => void;
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
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={busy}
        onClick={() => onReplaceImage(node.id)}
      >
        Replace…
      </button>
    </Card>
  );
}

/** The embed card's two modes — the Mutiny trust split. URL mode classifies a
 * committed link (calendly allowlisted, else any https custom; non-https is
 * refused inline). Code-snippet mode commits raw html (sandboxed at render).
 * Current mode is derived: a non-empty html with no url reads as a snippet. */
function EmbedCard({
  node,
  busy,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const isCalendly = node.provider === "calendly";
  const currentUrl = typeof node.url === "string" ? node.url : "";
  const currentHtml = node.html ?? "";
  const initialMode: "url" | "snippet" =
    currentHtml.trim() !== "" && currentUrl === "" ? "snippet" : "url";
  const [mode, setMode] = useState<"url" | "snippet">(initialMode);
  const [url, setUrl] = useState(currentUrl);
  const [html, setHtml] = useState(currentHtml);
  const [urlError, setUrlError] = useState<string | null>(null);

  const commitUrl = () => {
    setUrlError(null);
    if (url.trim() === "" && currentUrl === "") {
      return;
    }
    const props = classifyEmbedUrl(url);
    if (!props) {
      setUrlError("Enter an https:// URL.");
      return;
    }
    applyProps(props, "embed_url");
  };

  const commitSnippet = () => {
    if (html === currentHtml && currentUrl === "") {
      return;
    }
    applyProps({ kind: "embed", provider: "custom", html }, "embed_snippet");
  };

  return (
    <Card title="Embed">
      <div className="web-insp-field">
        <div className="web-align-row" role="group" aria-label="Embed mode">
          <button
            type="button"
            className={`btn btn-ghost btn-sm${mode === "url" ? " is-selected" : ""}`}
            aria-pressed={mode === "url"}
            disabled={busy}
            onClick={() => setMode("url")}
          >
            URL
          </button>
          <button
            type="button"
            className={`btn btn-ghost btn-sm${mode === "snippet" ? " is-selected" : ""}`}
            aria-pressed={mode === "snippet"}
            disabled={busy}
            onClick={() => setMode("snippet")}
          >
            Code snippet
          </button>
          {isCalendly ? <span className="web-embed-badge">Calendly</span> : null}
        </div>
      </div>

      {mode === "url" ? (
        <label className="field web-insp-field">
          <span className="field-label">URL</span>
          <input
            type="text"
            value={url}
            disabled={busy}
            onChange={(event) => setUrl(event.target.value)}
            onBlur={commitUrl}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.currentTarget.blur();
              }
            }}
            placeholder="https://…"
          />
          {urlError ? (
            <span className="web-insp-error" role="alert">
              {urlError}
            </span>
          ) : null}
        </label>
      ) : (
        <label className="field web-insp-field">
          <span className="field-label">Code snippet</span>
          <textarea
            className="web-insp-classes"
            value={html}
            disabled={busy}
            spellCheck={false}
            rows={4}
            onChange={(event) => setHtml(event.target.value)}
            onBlur={commitSnippet}
            placeholder="<iframe …></iframe>"
          />
          <span className="web-insp-hint">
            Runs sandboxed. Give the embed a height class (e.g. h-[700px]).
          </span>
        </label>
      )}
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
