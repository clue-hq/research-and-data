"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { WebLayerRow } from "@/features/design-editor/adapter/layers";
/* W4.7 (contract item 34): the props form's pure decisions. */
import {
  customComponentDraft,
  customComponentDraftCommit,
  customComponentDraftKeyAction,
  customComponentDraftKeySuppressesBlur,
  customComponentFields,
  customComponentSelectCommit,
  customComponentSelectLabel,
  type CustomComponentField,
  type CustomComponentFormBinding,
  type CustomComponentPropCommit,
} from "@/features/design-editor/adapter/custom-component-form";
import {
  richTextLinkPrefill,
  type RichTextLinkBinding,
} from "@/features/design-editor/adapter/rich-text-link-section";
import type {
  WebCloneTextEditsBinding,
  WebPageSectionBinding,
} from "@/features/design-editor/hooks/use-web-editing-session";
import {
  themeColorForToken,
  type ThemeColorOption,
} from "@/features/design-editor/adapter/theme-options";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
/* F5 task 19: the Page section's pure decisions (route grammar, the slug a new
   page's name mints, the two structural Remove refusals, the server-refusal
   wording). */
import {
  addPageDecision,
  pageIsRemovable,
  pageWriteMessage,
  routeFieldDecision,
  suggestedRouteForName,
} from "./inspector-page-field";
import {
  useInspectorController,
  useInspectorLayerTree,
  type HorizontalAlignment,
  type InspectorEventAddressing,
  type InspectorPresentationState,
} from "../hooks/use-inspector-controller";
import {
  ColorControl,
  InspectorField,
  InspectorHeader,
  InspectorIcon,
  InspectorImageUpload,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  InspectorTokenControl,
  RadiusControls,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";

const FONT_OPTIONS = ["Inter", "Satoshi Variable", "Season Serif", "DM Mono"] as const;
// §6(5): 13 dropped from the size options; 32 maps to 3xl.
const FONT_SIZE_OPTIONS = ["12", "14", "16", "18", "20", "24", "32"] as const;
// W3.2 §2 additions: the text style select (ruling 25) and the line-spacing
// select (ruling 26) — the two founder-ordered typography additions.
const TEXT_STYLE_OPTIONS = ["Display", "H1", "H2", "H3", "H4", "Body", "Small", "Overline"] as const;
const LINE_SPACING_OPTIONS = ["none", "tight", "snug", "normal", "relaxed", "loose"] as const;
const FONT_WEIGHT_OPTIONS = ["Regular", "Medium", "Semi Bold", "Bold"] as const;
// §2 delta (contract row 13): Tile is dropped — no engine object-fit value.
const FILL_MODE_OPTIONS = ["Fit", "Fill", "Stretch"] as const;
// §2 delta (contract row 16): Critical is dropped — no engine `critical`
// variant. The engine's `outline`/`link` variants have no dummy slot, so a
// node carrying one hydrates nothing and the select shows its default (§6(5)).
const BUTTON_STYLE_OPTIONS = ["Primary", "Secondary", "Transparent"] as const;
// Ruling 18b: the dummy's icon option lists (name / size / stroke) are gone
// with the sections they fed — the engine backs none of them, and the ruling
// hides rather than disables. The dummy's `InspectorDecoratedSelect` primitive
// stays in `inspector-primitives.tsx` (presentation truth is not this task's to
// delete); nothing in the web inspector renders it now.
const WEB_INSPECTOR_SELECTIONS = [
  "canvas",
  "text",
  "image",
  "button",
  "icon",
  "container",
  "section",
] as const satisfies readonly ChatShellInspectorSelection[];
type WebInspectorSelection = (typeof WEB_INSPECTOR_SELECTIONS)[number];

const INSPECTOR_TITLES: Record<WebInspectorSelection, string> = {
  button: "Button",
  canvas: "Canvas",
  container: "Container",
  icon: "Icon",
  image: "Image1",
  section: "Section",
  text: "Text34",
};
const INSPECTOR_REVIEW_LABELS: Record<WebInspectorSelection, string> = {
  button: "Button",
  canvas: "Canvas",
  container: "Container",
  icon: "Icon",
  image: "Image",
  section: "Section",
  text: "Text",
};
type InspectorController = ReturnType<typeof useInspectorController>;
type InspectorLayerTreeController = ReturnType<typeof useInspectorLayerTree>;

// W2.3: when the caller supplies real document layer rows, every schema's
// Layers section renders them instead of its fixture tree. The context keeps
// the seven schema views untouched except for the one fallback expression at
// each Layers site.
const DocumentLayersContext = createContext<ReactNode>(null);

function SchemaLayers({ fallback }: { fallback: ReactNode }) {
  const real = useContext(DocumentLayersContext);
  return <>{real ?? fallback}</>;
}

// W4.0: the document's real theme tokens for every ColorControl in this panel,
// carried as data (the seam rule: presentation never fetches). Undefined — the
// chats route, any mount without a document theme — leaves every picker on the
// dummy's fixture palette, unchanged. Only the text schema's Color control
// consumes it today; the other schemas' color controls join in their own W4
// tasks.
const ThemeColorsContext = createContext<readonly ThemeColorOption[] | undefined>(
  undefined,
);

function useThemeColors() {
  return useContext(ThemeColorsContext);
}

/** W2.3: the real layer tree — rows built from the document hierarchy
 * (design-editor `buildWebLayerRows`, nesting capped at depth 1 per ruling
 * 41), rendered with the dummy's own `InspectorLayerRow` primitive. Depth-0
 * rows expand/collapse locally (born expanded); clicking any row selects its
 * canvas node through the bridge. */
function DocumentLayers({
  onSelectLayer,
  rows,
}: {
  onSelectLayer?: (nodeId: string) => void;
  rows: WebLayerRow[];
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  return (
    <div className={styles.layerList}>
      {rows.map((row) => {
        if (row.parentId && collapsed[row.parentId]) return null;
        return (
          <InspectorLayerRow
            active={row.active}
            depth={row.depth}
            expandable={row.expandable}
            expanded={row.expandable ? !collapsed[row.nodeId] : undefined}
            icon={row.icon}
            key={row.nodeId}
            label={row.label}
            onClick={() => {
              if (row.expandable) {
                setCollapsed((current) => ({
                  ...current,
                  [row.nodeId]: !current[row.nodeId],
                }));
              }
              onSelectLayer?.(row.nodeId);
            }}
          />
        );
      })}
    </div>
  );
}

function TextAlignment({
  horizontal,
  onHorizontalChange,
  onVerticalChange,
  vertical,
  verticalHidden = false,
}: {
  // The ad surface's §2-row-2 Justify toggle widened the shared
  // `HorizontalAlignment`; this annotation follows it. The web control's own
  // three options — and everything it renders — are unchanged.
  horizontal: HorizontalAlignment;
  onHorizontalChange: (value: HorizontalAlignment) => void;
  onVerticalChange: (value: "bottom" | "middle" | "top") => void;
  vertical: "bottom" | "middle" | "top";
  /** W3.2 (ruling 8): the text schema hides vertical alignment. */
  verticalHidden?: boolean;
}) {
  const horizontalOptions = [
    ["left", "align-left"],
    ["center", "align-center"],
    ["right", "align-right"],
  ] as const;
  const verticalOptions = [
    ["top", "align-top"],
    ["middle", "align-middle"],
    ["bottom", "align-bottom"],
  ] as const;

  return (
    <div className={styles.alignmentGroups}>
      <div aria-label="Horizontal alignment" className={styles.alignmentControl} role="group">
        {horizontalOptions.map(([value, icon]) => (
          <button
            aria-label={`Align ${value}`}
            aria-pressed={horizontal === value}
            className={horizontal === value ? styles.alignmentActive : ""}
            key={value}
            onClick={() => onHorizontalChange(value)}
            type="button"
          >
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      {verticalHidden ? null : (
      <div
        aria-label="Vertical alignment"
        className={`${styles.alignmentControl} ${styles.verticalAlignment}`}
        role="group"
      >
        {verticalOptions.map(([value, icon]) => (
          <button
            aria-label={`Align ${value}`}
            aria-pressed={vertical === value}
            className={vertical === value ? styles.alignmentActive : ""}
            key={value}
            onClick={() => onVerticalChange(value)}
            type="button"
          >
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      )}
    </div>
  );
}

/** W3.2 (R3, founder-ordered delta): the four per-side boxes collapse to two
 * axis boxes (X/Y). Typed values draft locally and COMMIT on blur/Enter — the
 * dummy's own commit model — so the write path never sees per-keystroke
 * events. */
function PaddingXYControls({
  onCommit,
  values,
}: {
  onCommit: (axis: "x" | "y", value: string) => void;
  values: Record<"bottom" | "left" | "right" | "top", string>;
}) {
  const [draftX, setDraftX] = useState(values.left);
  const [draftY, setDraftY] = useState(values.top);
  const commit = (axis: "x" | "y") => {
    const draft = axis === "x" ? draftX : draftY;
    if (draft !== (axis === "x" ? values.left : values.top)) {
      onCommit(axis, draft);
    }
  };
  return (
    <div className={styles.paddingGrid}>
      <span
        className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
        onBlur={() => commit("x")}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit("x");
        }}
      >
        <span className={styles.fieldPrefix}>X</span>
        <input
          aria-label="Horizontal padding"
          onChange={(event) => setDraftX(event.target.value)}
          value={draftX}
        />
      </span>
      <span
        className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
        onBlur={() => commit("y")}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit("y");
        }}
      >
        <span className={styles.fieldPrefix}>Y</span>
        <input
          aria-label="Vertical padding"
          onChange={(event) => setDraftY(event.target.value)}
          value={draftY}
        />
      </span>
    </div>
  );
}

/** W4.4 (row 22 + R3): the section's Gap box. Same control the dummy ships —
 * the gap icon and the input — but a typed value drafts locally and COMMITS on
 * blur/Enter, so the write path sees one change, not one per keystroke (and
 * the engine's nearest-step snap happens once). */
function GapControl({
  onCommit,
  value,
}: {
  onCommit: (value: string) => void;
  value: string;
}) {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <span
      className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    >
      <InspectorIcon name="gap" size={16} />
      <input
        aria-label="Section gap"
        onChange={(event) => setDraft(event.target.value)}
        value={draft}
      />
    </span>
  );
}

function PaddingControls({
  onChange,
  values,
}: {
  onChange: (side: "bottom" | "left" | "right" | "top", value: string) => void;
  values: Record<"bottom" | "left" | "right" | "top", string>;
}) {
  return (
    <div className={styles.paddingGrid}>
      <InspectorInput ariaLabel="Left padding" onChange={(value) => onChange("left", value)} prefix="L" value={values.left} />
      <InspectorInput ariaLabel="Top padding" onChange={(value) => onChange("top", value)} prefix="T" value={values.top} />
      <InspectorInput ariaLabel="Right padding" onChange={(value) => onChange("right", value)} prefix="R" value={values.right} />
      <InspectorInput ariaLabel="Bottom padding" onChange={(value) => onChange("bottom", value)} prefix="B" value={values.bottom} />
    </div>
  );
}

function TextLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow
        active={tree.activeLayer === "div1"}
        expanded={tree.expandedLayers.div1}
        expandable
        icon="div"
        label="Div1"
        onClick={() => { tree.selectLayer("div1"); tree.toggleLayer("div1"); }}
      />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === "text"}
          depth={1}
          icon="type"
          label="Text"
          onClick={() => { tree.selectLayer("text"); onSelectionChange("text"); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow
        active={tree.activeLayer === "div2"}
        expanded={tree.expandedLayers.div2}
        expandable
        icon="div"
        label="Div2"
        onClick={() => { tree.selectLayer("div2"); tree.toggleLayer("div2"); }}
      />
      {tree.expandedLayers.div2 ? (
        <>
          <InspectorLayerRow active={tree.activeLayer === "rectangle"} depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} />
          <InspectorLayerRow active={tree.activeLayer === "ellipse"} depth={1} icon="ellipse" label="Ellipse" onClick={() => tree.selectLayer("ellipse")} />
        </>
      ) : null}
    </div>
  );
}

function ImageLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <>
          <InspectorLayerRow active={tree.activeLayer === "text"} depth={1} icon="type" label="Text" onClick={() => { tree.selectLayer("text"); onSelectionChange("text"); }} />
          <InspectorLayerRow active={tree.activeLayer === "image"} depth={1} icon="image" label="Image" onClick={() => { tree.selectLayer("image"); onSelectionChange("image"); }} trailing />
        </>
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" /> : null}
    </div>
  );
}

function ButtonLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === "button"}
          depth={1}
          icon="rectangle"
          label="Button"
          onClick={() => { tree.selectLayer("button"); onSelectionChange("button"); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? (
        <>
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} />
          <InspectorLayerRow depth={1} icon="ellipse" label="Ellipse" onClick={() => tree.selectLayer("ellipse")} />
        </>
      ) : null}
    </div>
  );
}

function StructuralLayers({
  onSelectionChange,
  selection,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: Extract<ChatShellInspectorSelection, "container" | "icon" | "section">;
  tree: InspectorLayerTreeController;
}) {
  const icon = selection === "icon" ? "apple" : "div";
  const label = selection[0].toUpperCase() + selection.slice(1);
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow expanded={tree.expandedLayers.div1} expandable icon="div" label="Div1" onClick={() => tree.toggleLayer("div1")} />
      {tree.expandedLayers.div1 ? (
        <InspectorLayerRow
          active={tree.activeLayer === selection}
          depth={1}
          icon={icon}
          label={label}
          onClick={() => { tree.selectLayer(selection); onSelectionChange(selection); }}
          trailing
        />
      ) : null}
      <InspectorLayerRow expanded={tree.expandedLayers.div2} expandable icon="div" label="Div2" onClick={() => tree.toggleLayer("div2")} />
      {tree.expandedLayers.div2 ? <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" onClick={() => tree.selectLayer("rectangle")} /> : null}
    </div>
  );
}

function CanvasLayers({
  onSelectionChange,
  tree,
}: {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  tree: InspectorLayerTreeController;
}) {
  return (
    <div className={styles.layerList}>
      <InspectorLayerRow active={tree.activeLayer === "text-1"} icon="type" label="Text" onClick={() => { tree.selectLayer("text-1"); onSelectionChange("text"); }} />
      <InspectorLayerRow active={tree.activeLayer === "canvas-text"} icon="type" label="Text" onClick={() => { tree.selectLayer("canvas-text"); onSelectionChange("text"); }} trailing />
      <InspectorLayerRow expanded={tree.expandedLayers.group} expandable icon="div" label="Group" onClick={() => tree.toggleLayer("group")} />
      {tree.expandedLayers.group ? (
        <>
          <InspectorLayerRow depth={1} icon="type" label="Text" />
          <InspectorLayerRow depth={1} icon="rectangle" label="Rectangle" />
        </>
      ) : null}
    </div>
  );
}

function Section({
  children,
  id,
  label,
  state,
  toggle,
}: {
  children?: ReactNode;
  id: Parameters<ReturnType<typeof useInspectorController>["toggleSection"]>[0];
  label: string;
  state: ReturnType<typeof useInspectorController>["state"];
  toggle: ReturnType<typeof useInspectorController>["toggleSection"];
}) {
  return <InspectorSection compact={id === "link"} label={label} onOpenChange={() => toggle(id)} open={state.openSections[id]}>{children}</InspectorSection>;
}

function SegmentedControl<Value extends string>({
  ariaLabel,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  onChange: (value: Value) => void;
  options: readonly { label: ReactNode; value: Value }[];
  value: Value;
}) {
  return (
    <div aria-label={ariaLabel} className={styles.inspectorSegmentedControl} role="group">
      {options.map((option) => (
        <button
          aria-pressed={option.value === value}
          className={option.value === value ? styles.inspectorSegmentActive : ""}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function LinkSection({
  ariaLabel,
  controller,
}: {
  ariaLabel: string;
  controller: InspectorController;
}) {
  const { setValue, state, toggleSection } = controller;
  // W4.2 (ruling R-B2, the ratified R3 commit model): the URL drafts locally
  // and commits on blur/Enter — a per-keystroke `setValue("url", …)` would
  // write one operation per character. The checkbox below is already discrete,
  // so it commits as it always has.
  const [draftUrl, setDraftUrl] = useState(state.url);
  return (
    <Section id="link" label="Link to" state={state} toggle={toggleSection}>
      <InspectorField label="URL">
        <InspectorInput
          ariaLabel={ariaLabel}
          onChange={setDraftUrl}
          onCommit={() => {
            if (draftUrl !== state.url) setValue("url", draftUrl);
          }}
          value={draftUrl}
        />
      </InspectorField>
      <label className={styles.checkboxRow}>
        <input checked={state.openInNewTab} onChange={(event) => setValue("openInNewTab", event.target.checked)} type="checkbox" />
        <span>Open in a new tab</span>
      </label>
    </Section>
  );
}

function TokenField({
  controller,
  label,
  options,
  property,
  swatch,
  tokenProperty,
  value,
}: {
  controller: InspectorController;
  label: string;
  /** W4.4: the document's real theme tokens; with `tokenProperty` they make
   * this button a live token picker (rows 19/17). Absent → the dummy button. */
  options?: readonly ThemeColorOption[];
  property: string;
  swatch: string;
  /** W4.4: which inspector token field a pick writes
   * (`tokenTextColor`/`tokenBackgroundColor`) — the W3.1-addressed event seam,
   * so `adapter/apply.ts` turns the label into the facet write. */
  tokenProperty?: "tokenBackgroundColor" | "tokenTextColor";
  value: string;
}) {
  return (
    <InspectorField label={label}>
      <InspectorTokenControl
        label={value}
        onClick={() => controller.requestAction(`token-picker:${property}`)}
        onTokenSelect={
          tokenProperty
            ? (token) => controller.setValue(tokenProperty, token)
            : undefined
        }
        options={options}
        swatch={swatch}
      />
    </InspectorField>
  );
}

/** W4.4: the Style section shared by the container and section schemas — the
 * dummy's two token buttons, now showing the node's hydrated tokens (with the
 * theme's real swatch when the document defines it) and writing through the
 * theme-token popover (rows 19; the popover is row 17's pattern). Both schemas
 * render exactly the two fields the dummy ships. */
function StyleTokenFields({ controller }: { controller: InspectorController }) {
  const { state } = controller;
  const themeColors = useThemeColors();
  return (
    <>
      <TokenField
        controller={controller}
        label="Text color"
        options={themeColors}
        property="textColor"
        swatch={themeColorForToken(themeColors, state.tokenTextColor) ?? "#1C2028"}
        tokenProperty="tokenTextColor"
        value={state.tokenTextColor}
      />
      <TokenField
        controller={controller}
        label="Background color"
        options={themeColors}
        property="backgroundColor"
        swatch={
          themeColorForToken(themeColors, state.tokenBackgroundColor) ?? "#FFFFFF"
        }
        tokenProperty="tokenBackgroundColor"
        value={state.tokenBackgroundColor}
      />
    </>
  );
}

function LayoutSection({
  controller,
  paddingAxes = "four",
}: {
  controller: InspectorController;
  /** W3.2 (R3): "two" collapses the padding boxes to X/Y with blur/Enter
   * commit; "four" keeps the dummy's per-side boxes (until each schema's W4
   * task applies its own delta). */
  paddingAxes?: "four" | "two";
}) {
  const { setNestedValue, setPaddingAxis, state, toggleSection } = controller;
  return (
    <Section id="layout" label="Layout" state={state} toggle={toggleSection}>
      <InspectorField label="Padding">
        {paddingAxes === "two" ? (
          <PaddingXYControls
            onCommit={(axis, value) => setPaddingAxis(axis, value)}
            values={state.padding}
          />
        ) : (
          <PaddingControls onChange={(side, value) => setNestedValue("padding", side, value)} values={state.padding} />
        )}
      </InspectorField>
    </Section>
  );
}

/* ---- W4.8b: the TEXT schema's range-bound "Link to" (begins) --------------
 *
 * Binding contract item 3: for text the section is hidden by default and
 * appears — functional — only while a rich-text range is selected, and it binds
 * to the RANGE link, never to a whole-node href (text has none). The caller
 * supplies the binding ONLY when the ledgered visibility ruling holds
 * (`richTextLinkSectionVisible`), so "hidden" here is literally ABSENT
 * (mapping contract §2) — no disabled fields, no empty shell.
 *
 * Presentation is the dummy's own LinkSection, unchanged: the same collapsed
 * "Link to" section, the same URL field, the same "Open in a new tab"
 * checkbox. Only the wiring underneath differs.
 */
function RichTextLinkSection({
  controller,
  range,
}: {
  controller: InspectorController;
  range: RichTextLinkBinding;
}) {
  const { state, toggleSection } = controller;
  // The live range's own values (the toolbar's prefill semantics). Callers
  // remount this section when they change — see the `key` at the call site —
  // so the draft below is always born from the range it edits.
  const prefill = richTextLinkPrefill(range.selection);
  const [href, setHref] = useState(prefill.href);
  const [newTab, setNewTab] = useState(prefill.newTab);
  // The dummy's own commit model for a typed value (PaddingXYControls above):
  // a LOCAL draft that commits on blur/Enter, so the write path never sees a
  // keystroke. An untouched field commits nothing.
  const commitHref = () => {
    if (href === prefill.href) return;
    range.onSubmitLink(href, newTab, "submit");
  };
  return (
    // Focus moving in tells the frame to hold its edit session open (the
    // bridge otherwise settles it 180ms after its contenteditable blurs);
    // focus leaving the whole section releases it again. `onBlur` bubbles
    // (focusout), so the containment check keeps a hop between these two
    // controls from releasing the session.
    <div
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget)) return;
        range.onInteractionChange(false);
      }}
      onFocusCapture={() => range.onInteractionChange(true)}
      onPointerDownCapture={() => range.onInteractionChange(true)}
    >
      <Section id="link" label="Link to" state={state} toggle={toggleSection}>
        <InspectorField label="URL">
          <span
            className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
            onBlur={commitHref}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitHref();
            }}
          >
            <input
              aria-label="Link URL"
              inputMode="text"
              onChange={(event) => setHref(event.target.value)}
              value={href}
            />
          </span>
        </InspectorField>
        <label className={styles.checkboxRow}>
          <input
            checked={newTab}
            onChange={(event) => {
              setNewTab(event.target.checked);
              // Commits at once — but only over an href that is already
              // valid, so a toggle can neither remove a link nor scold about a
              // half-typed URL (the decision lives in `richTextLinkCommit`).
              range.onSubmitLink(href, event.target.checked, "toggle");
            }}
            type="checkbox"
          />
          <span>Open in a new tab</span>
        </label>
      </Section>
    </div>
  );
}
/* ---- W4.8b (ends) ------------------------------------------------------- */

function TextControls({
  controller,
  layerTree,
  onSelectionChange,
  richTextRange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  /** W4.8b: the live rich-text range to bind "Link to" to. Null/absent → the
   * text schema renders NO Link-to section (contract item 3; §2
   * hidden = absent). The other schemas' LinkSection usages are untouched —
   * they write node props, which text does not have. */
  richTextRange?: RichTextLinkBinding | null;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  const themeColors = useThemeColors();
  return (
    <>
      {richTextRange ? (
        <RichTextLinkSection
          controller={controller}
          // Remount identity: the edited node plus the range's own link
          // values. A new range (or a link changed inside the frame) starts
          // the draft from the new prefill; our own commits leave the key
          // untouched, so typing is never interrupted. This is the same
          // remount-instead-of-reset-effect discipline W4.8a used for the
          // toolbar (this repo's lint forbids a setState inside an effect).
          key={`${richTextRange.nodeId}:${richTextRange.selection.link.state}:${richTextRange.selection.link.href ?? ""}:${richTextRange.selection.link.newTab ?? ""}`}
          range={richTextRange}
        />
      ) : null}
      <Section id="typography" label="Typography" state={state} toggle={toggleSection}>
        {/* R2: the theme tab's token pick is the live write path
            (tokenTextColor); the hex path stays visual-only (§3 inert).
            W4.0: the tab lists the document's real tokens, and the closed
            trigger shows the hydrated token's actual color when the theme
            has it (otherwise the dummy default stands). */}
        <InspectorField label="Color"><ColorControl color={themeColorForToken(themeColors, state.tokenTextColor) ?? state.textColor} onColorChange={(value) => setValue("textColor", value)} onTokenChange={(label) => setValue("tokenTextColor", label)} options={themeColors} /></InspectorField>
        <InspectorField label="Font"><InspectorSelect label="Font" onChange={(value) => setValue("fontFamily", value)} options={FONT_OPTIONS} value={state.fontFamily} /></InspectorField>
        {/* W3.2 §2 addition (ruling 25): the text style/variant select. */}
        <InspectorField label="Style"><InspectorSelect label="Text style" onChange={(value) => setValue("textStyle", value)} options={TEXT_STYLE_OPTIONS} value={state.textStyle} /></InspectorField>
        <div className={styles.fieldGrid}>
          <InspectorField label="Size"><InspectorSelect label="Font size" onChange={(value) => setValue("fontSize", value)} options={FONT_SIZE_OPTIONS} value={state.fontSize} /></InspectorField>
          <InspectorField label="Weight"><InspectorSelect label="Font weight" onChange={(value) => setValue("fontWeight", value)} options={FONT_WEIGHT_OPTIONS} value={state.fontWeight} /></InspectorField>
        </div>
        {/* W3.2 §2 addition (ruling 26): the line-spacing select. */}
        <InspectorField label="Line spacing"><InspectorSelect label="Line spacing" onChange={(value) => setValue("lineSpacing", value)} options={LINE_SPACING_OPTIONS} value={state.lineSpacing} /></InspectorField>
        {/* Ruling 8: vertical alignment hidden on the text schema. */}
        <InspectorField label="Alignment"><TextAlignment horizontal={state.horizontalAlignment} onHorizontalChange={(value) => setValue("horizontalAlignment", value)} onVerticalChange={(value) => setValue("verticalAlignment", value)} vertical={state.verticalAlignment} verticalHidden /></InspectorField>
      </Section>
      {/* R3: text's padding boxes collapse to the two-axis form. */}
      <LayoutSection controller={controller} paddingAxes="two" />
      <Section id="stroke" label="Stroke" state={state} toggle={toggleSection}>
        <InspectorField label="Color"><ColorControl none={state.strokeColor === "none"} /></InspectorField>
        <InspectorField label="Width"><InspectorInput ariaLabel="Stroke width" onChange={(value) => setValue("strokeWidth", value)} value={state.strokeWidth} /></InspectorField>
      </Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<TextLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function CanvasControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  // W4.5 (row 1): the same Background control the dummy ships, now fed the
  // document's real theme tokens and emitting the token label — the write path
  // `adapter/apply.ts` already serves for containers (the page root IS a
  // container). The hex/Custom tab stays §3-inert. No other canvas change: the
  // dummy canvas view has no padding boxes, so §2's padding 4→2 delta has
  // nothing to collapse here.
  //
  // NOT YET REACHABLE end to end, and neither gap is the inspector's to close
  // (both are upstream of this file; recorded 2026-08-18, W4.5):
  //   • Nothing can SELECT the page root. `lumen-web`'s `render_page` renders
  //     only `root.children` into <body>, so no element carries
  //     data-node-id="root"; the canvas bridge's click handler resolves
  //     `closest("[data-node-id]")` and a background click therefore CLEARS
  //     the selection; and `adapter/layers.ts` starts the tree at the root's
  //     children, so the Layers list has no root row either. With no
  //     `selectionId`, W3.1's null contract drops every event this control
  //     emits — which is why picking a token here moves the swatch and writes
  //     nothing.
  //   • Even once written, `root.classes` is DROPPED by the renderer (same
  //     `render_page`), so a page-root `bg-<token>` paints nothing.
  // Closing row 1 needs a lumen-web change (render the root, or hang its
  // classes on <body>) plus a way to select it. Until then this control is
  // honest-but-inert, exactly as it was before the wiring.
  const themeColors = useThemeColors();
  return (
    <>
      <Section id="background" label="Background" state={state} toggle={toggleSection}><InspectorField label="Color"><ColorControl color={themeColorForToken(themeColors, state.tokenBackgroundColor) ?? state.backgroundColor} onColorChange={(value) => setValue("backgroundColor", value)} onTokenChange={(label) => setValue("tokenBackgroundColor", label)} options={themeColors} /></InspectorField></Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<CanvasLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function ImageControls({
  controller,
  layerTree,
  onReplaceImage,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onReplaceImage?: (file: File) => void;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setNestedValue, setRadiusAll, setValue, state, toggleSection } = controller;
  return (
    <>
      <LinkSection ariaLabel="Image link URL" controller={controller} />
      <Section id="fill" label="Fill" state={state} toggle={toggleSection}>
        <InspectorField label="Image">
          {/* W4.2 §1 row 12: the picked File goes out by PROP to the editor
              surface's upload+replace path (presentation stays transport-free).
              With no handler the dummy keeps its local-preview-only behavior —
              never the old `requestAction` dead end. The preview src is the
              node's own asset (ruling R-B5), falling back to the stock png. */}
          <InspectorImageUpload
            onFileSelect={onReplaceImage}
            src={state.imagePreviewSrc}
          />
        </InspectorField>
        <InspectorField label="Mode"><InspectorSelect label="Image fill mode" onChange={(value) => setValue("fillMode", value)} options={FILL_MODE_OPTIONS} value={state.fillMode} /></InspectorField>
      </Section>
      {/* Row 14 + founder ruling F2: the all-corners commit (field or scan
          button) is one `radius.all` change whose write clears the corner
          overrides; the corner fields mirror it. */}
      <Section id="shape" label="Shape" state={state} toggle={toggleSection}><InspectorField label="Radius"><RadiusControls onApplyAll={setRadiusAll} onChange={(corner, value) => setNestedValue("radius", corner, value)} values={state.radius} /></InspectorField></Section>
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}><SchemaLayers fallback={<ImageLayers onSelectionChange={onSelectionChange} tree={layerTree} />} /></Section> : null}
    </>
  );
}

function ButtonControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  const themeColors = useThemeColors();
  return (
    <>
      <LinkSection ariaLabel="Button link URL" controller={controller} />
      <Section id="style" label="Style" state={state} toggle={toggleSection}>
        <InspectorField label="Label">
          <InspectorSelect label="Button style" onChange={(value) => setValue("buttonLabel", value)} options={BUTTON_STYLE_OPTIONS} value={state.buttonLabel} />
        </InspectorField>
        {/* Row 17 (ruling R-B6, re-based onto lane A's shared chip at the
            lane-B merge, 2026-08-19): the two chips are live token pickers —
            label + swatch from hydrated state, a pick writes the bg-/text-
            facet through the apply adapter. Same TokenField/InspectorTokenControl
            machinery as W4.4's container/section Style fields (one popover
            implementation, not two); with no theme mounted the chip stays the
            dummy's dead chip — never a fixture-palette popover that would
            write phantom tokens. */}
        <TokenField
          controller={controller}
          label="Background color"
          options={themeColors}
          property="backgroundColor"
          swatch={themeColorForToken(themeColors, state.tokenBackgroundColor) ?? state.backgroundColor}
          tokenProperty="tokenBackgroundColor"
          value={state.tokenBackgroundColor}
        />
        <TokenField
          controller={controller}
          label="Text color"
          options={themeColors}
          property="textColor"
          swatch={themeColorForToken(themeColors, state.tokenTextColor) ?? "#FFFFFF"}
          tokenProperty="tokenTextColor"
          value={state.tokenTextColor}
        />
      </Section>
      {/* R3: the button's padding boxes collapse to the two-axis form. */}
      <LayoutSection controller={controller} paddingAxes="two" />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<ButtonLayers onSelectionChange={onSelectionChange} tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

function IconControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { state, toggleSection } = controller;
  // Ruling 18b (§2 delta): the icon schema renders ONLY Layout/padding (plus
  // the Layers section every schema carries). The engine's icon node is
  // `WebNodeKind::Icon { icon }` — one agent-authored name from the curated
  // set, no facets, no href — so the dummy's Icon section (icon select, icon
  // color, background color, size, stroke) and its Link-to section have NOTHING
  // behind them. 18b's ruling is "hide", so they are ABSENT here, not disabled:
  // an inert control the marketer can click and watch do nothing is exactly
  // what the ruling refused. Hiding them IS the ruled deviation from the dummy;
  // nothing else about the icon panel changed.
  //
  // Padding is the icon's one live surface, and it needs no icon-specific
  // sanction in `adapter/apply.ts`: the padding cases carry no kind guard
  // because §5 gives the same Layout(-padding) section to embeds and every
  // unmapped kind. The two-box (X/Y) form is R3, shared with every other
  // schema. The header (eye per row 40, lock inert per 39) is global chrome and
  // is untouched.
  return (
    <>
      <LayoutSection controller={controller} paddingAxes="two" />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="icon" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

/* ---- W4.7: the custom-component props form (begins) -----------------------
 *
 * Binding contract item 34: "Custom component → props form | manifest
 * `props_schema` → `set_custom_component_props` | the existing schema-driven
 * form, shown when a custom component is selected." A custom component falls to
 * the §5 layout-only fallback (the CONTAINER view), so the form JOINS that
 * view — it is passed to ContainerControls alone, and every other fallback kind
 * (embed, component, …) keeps the bare layout view unchanged.
 *
 * SCOPE: the form only. The source inspector's first card — status pill,
 * metrics, compile warnings, republish banner, "Edit with AI" — is chrome and
 * is deliberately not ported, nor are its props.
 *
 * Ledgered ruling (2026-08-18): while the artifact is loading, or if its fetch
 * failed, the binding is null and this section is simply ABSENT — no loading
 * shell, no error chrome; the layout fallback stands alone.
 *
 * Every decision (which control, what label, what one settled draft commits,
 * the whole-props payload) lives in the pure adapter so it is testable under
 * this repo's renderer-free runner; what is left here is presentation.
 */
function CustomComponentPropDraftControl({
  field,
  onCommit,
}: {
  field: CustomComponentField;
  onCommit: CustomComponentPropCommit;
}) {
  // The dummy's own commit model for a typed value (PaddingXYControls above):
  // a LOCAL draft that settles on blur/Enter, so the write path never sees a
  // keystroke. The source's `useEffect` re-sync of the draft (:62-64) is
  // replaced by the call site's remount key — this repo's lint forbids a
  // setState inside an effect (same discipline as W4.8a/b).
  const [draft, setDraft] = useState(field.draft);
  // Browser-verified defect (2026-08-18) and its fix. Enter and Escape both end
  // the field's focus, and the blur they cause fires in the SAME browser task —
  // holding the pre-key `draft` closure. So the blur-settle used to run with the
  // stale draft: Escape wrote the very garbage it was abandoning, and Enter
  // settled twice (survivable only because the manual-edits controller drops an
  // apply while one is in flight). This ref makes the key own the outcome and
  // the follow-on blur a no-op. Deliberate deviation from the source's event
  // wiring, which has the same hazard (:141-150) — the binding semantics are the
  // brief's and the source's INTENT (Escape restores and sends NOTHING), not its
  // handler arrangement.
  const skipBlurSettle = useRef(false);
  const settle = () => {
    const decision = customComponentDraftCommit({
      draft,
      schema: field.schema,
      value: field.value,
    });
    if (decision.kind === "revert") setDraft(decision.draft);
    if (decision.kind === "commit") onCommit(field.name, decision.value);
  };
  return (
    <InspectorField label={field.displayLabel}>
      <span
        className={`${styles.inspectorControl} ${styles.inspectorInputControl}`}
        onBlur={() => {
          if (skipBlurSettle.current) {
            skipBlurSettle.current = false;
            return;
          }
          settle();
        }}
        onKeyDown={(event) => {
          const action = customComponentDraftKeyAction(event.key);
          if (action === "none") return;
          skipBlurSettle.current = customComponentDraftKeySuppressesBlur(action);
          if (action === "settle") {
            event.preventDefault();
            settle();
          } else {
            // Escape abandons the draft and sends nothing (source intent
            // :146-149) — the write above is deliberately not reached.
            setDraft(field.draft);
          }
          (event.target as HTMLInputElement).blur();
        }}
      >
        <input
          aria-label={field.ariaLabel}
          id={field.inputId}
          inputMode={field.kind === "number" ? "decimal" : "text"}
          onChange={(event) => setDraft(event.target.value)}
          step={field.kind === "number" ? "any" : undefined}
          type={field.kind === "number" ? "number" : "text"}
          value={draft}
        />
      </span>
    </InspectorField>
  );
}

function CustomComponentPropControl({
  field,
  onCommit,
}: {
  field: CustomComponentField;
  onCommit: CustomComponentPropCommit;
}) {
  // Checkbox and select commit IMMEDIATELY (source :76, :99) — there is no
  // half-typed state to protect. Text and number draft locally.
  if (field.kind === "checkbox") {
    return (
      <label className={styles.checkboxRow} htmlFor={field.inputId}>
        <input
          aria-label={field.ariaLabel}
          checked={field.value === true}
          id={field.inputId}
          onChange={(event) => onCommit(field.name, event.target.checked)}
          type="checkbox"
        />
        <span>{field.displayLabel}</span>
      </label>
    );
  }
  if (field.kind === "select") {
    return (
      <InspectorField label={field.displayLabel}>
        <InspectorSelect
          label={field.ariaLabel}
          onChange={(label) => {
            const value = customComponentSelectCommit(field.selectOptions, label);
            if (value !== null) onCommit(field.name, value);
          }}
          // The inspector's select speaks labels; the adapter owns the
          // label → value mapping, including the "Default" entry whose value
          // is the empty string.
          options={field.selectOptions.map((option) => option.label)}
          value={customComponentSelectLabel(field.selectOptions, field.value)}
        />
      </InspectorField>
    );
  }
  return <CustomComponentPropDraftControl field={field} onCommit={onCommit} />;
}

function CustomComponentPropsSection({
  form,
}: {
  form: CustomComponentFormBinding;
}) {
  // Section-local open state: this section is not one of the controller's
  // fixed schema sections (it exists only for a custom component), so it does
  // not take a slot in the shared `InspectorSectionId` union.
  const [open, setOpen] = useState(true);
  const fields = customComponentFields(form.artifact, form.props);
  return (
    <InspectorSection label="Component properties" onOpenChange={setOpen} open={open}>
      {/* One write at a time: the manual-edits controller drops an apply that
          lands mid-flight, so every control goes dead while one is in the air
          (source `disabled={busy}` on each control). A `display: contents`
          fieldset is the native way to disable a subtree — including the
          select's trigger button — without touching the section's layout or
          the shared primitives. */}
      <fieldset disabled={form.busy} style={{ display: "contents" }}>
        {fields.length === 0 ? (
          <p className={styles.inspectorFieldLabel}>
            This component has no editable properties.
          </p>
        ) : (
          fields.map((field) => (
            <CustomComponentPropControl
              field={field}
              // Remount identity: the prop's LIVE value. A committed change (or
              // any change arriving from the document) reseeds the draft; our
              // own keystrokes leave it untouched, so typing is never
              // interrupted — and an equal-but-differently-spelled draft
              // ("3.0" over 3) survives, exactly as upstream.
              key={`${field.name}:${customComponentDraft(field.value)}`}
              onCommit={form.onCommitProp}
            />
          ))
        )}
        <p className={styles.inspectorFieldLabel}>
          * Required by the pinned artifact schema.
        </p>
      </fieldset>
    </InspectorSection>
  );
}
/* ---- W4.7 (ends) -------------------------------------------------------- */

function ContainerControls({
  controller,
  customComponentForm,
  layerTree,
  layoutOnly = false,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  /** W4.7 (contract item 34): the selected custom component's pinned artifact
   * + live props. Null/absent → NO props section, which is also what a loading
   * or failed artifact fetch yields (ledgered ruling) and what every other
   * fallback kind on this view gets. */
  customComponentForm?: CustomComponentFormBinding | null;
  layerTree: InspectorLayerTreeController;
  /** W5.1 (§5): true when this view is the unknown-kind FALLBACK (embed —
   * item 32; the interactive components — item 33; anything unmapped), not a
   * real container. See the branch below. */
  layoutOnly?: boolean;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      {/* W4.7: the component's own properties lead — they are what the user
          selected the component to change; the §5 layout fallback follows
          unchanged beneath them. */}
      {customComponentForm ? (
        <CustomComponentPropsSection form={customComponentForm} />
      ) : null}
      {/* W5.1 — §5's fallback rule: "unknown/unmapped selection kinds show
          Layout(-padding) only", covering embeds (item 32) and the interactive
          components — dialog/accordion/marquee/carousel/tabs/nav-menu (item
          33). Those kinds land on THIS view (the schema mapper routes them to
          `container` with `layoutOnly`), but they are not containers: they
          carry no href, no bg-/text- facet the inspector may claim, and no
          display mode to segment — the writes below all refuse fail-closed for
          them. §5 rules "Layout only", so the three sections are ABSENT here,
          not disabled — the same posture ruling 18b took for the icon schema.
          A real container (`layoutOnly` false) renders exactly as before:
          rows 19/20 and the Link-to section are untouched. */}
      {layoutOnly ? null : (
        <>
          <LinkSection ariaLabel="Container link URL" controller={controller} />
          <Section id="style" label="Style" state={state} toggle={toggleSection}>
            {/* W4.4 (row 19): the two token buttons, hydrated + live. */}
            <StyleTokenFields controller={controller} />
          </Section>
          <Section id="alignment" label="Alignment" state={state} toggle={toggleSection}>
            <SegmentedControl
              ariaLabel="Container layout mode"
              onChange={(value) => setValue("layoutMode", value)}
              options={([
                { label: "Flex", value: "Flex" },
                { label: "Grid", value: "Grid" },
                { label: "Hide", value: "Hide" },
              ] as const)}
              value={state.layoutMode}
            />
          </Section>
        </>
      )}
      {/* R3: the container's padding boxes collapse to the two-axis form. */}
      <LayoutSection controller={controller} paddingAxes="two" />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="container" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

function SectionControls({
  controller,
  layerTree,
  onSelectionChange,
  showLayers,
}: {
  controller: InspectorController;
  layerTree: InspectorLayerTreeController;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  showLayers: boolean;
}) {
  const { setValue, state, toggleSection } = controller;
  return (
    <>
      {/* Ruling 23 (§2 delta): a web section deliberately has no link — only
          containers do — so the Link-to section is ABSENT here, not disabled. */}
      <Section id="style" label="Style" state={state} toggle={toggleSection}>
        {/* W4.4 (row 19): the two token buttons, hydrated + live. */}
        <StyleTokenFields controller={controller} />
      </Section>
      <Section id="alignment" label="Alignment" state={state} toggle={toggleSection}>
        <InspectorField label="Direction">
          <SegmentedControl
            ariaLabel="Section direction"
            onChange={(value) => setValue("direction", value)}
            options={([
              { label: <InspectorIcon name="move-horizontal" size={12} />, value: "horizontal" },
              { label: <InspectorIcon name="move-vertical" size={12} />, value: "vertical" },
            ] as const)}
            value={state.direction}
          />
        </InspectorField>
        <InspectorField label="Gap">
          {/* W4.4 (R3): free-text drafts locally, commits on blur/Enter. */}
          <GapControl onCommit={(value) => setValue("gap", value)} value={state.gap} />
        </InspectorField>
        <InspectorField label="Wrap">
          <SegmentedControl
            ariaLabel="Section wrapping"
            onChange={(value) => setValue("wrap", value === "yes")}
            options={([
              { label: "Yes", value: "yes" },
              { label: "No", value: "no" },
            ] as const)}
            value={state.wrap ? "yes" : "no"}
          />
        </InspectorField>
      </Section>
      {/* R3: the section's padding boxes collapse to the two-axis form. */}
      <LayoutSection controller={controller} paddingAxes="two" />
      {showLayers ? <Section id="layers" label="Layers" state={state} toggle={toggleSection}>
        <SchemaLayers fallback={<StructuralLayers onSelectionChange={onSelectionChange} selection="section" tree={layerTree} />} />
      </Section> : null}
    </>
  );
}

/** W4.3 (§1 row 17): the web dummy's BUTTON chips are designed "Primary"
 * and "White", but the controller's shared `DEFAULT_STATE`
 * carries "White"/"Content" for these two fields — those are the AD-side
 * image-inspector's designed chip values, and it reads the SAME state fields,
 * so `DEFAULT_STATE` cannot move without breaking that dummy's visual parity
 * instead. The web button schema therefore carries its own dummy initial
 * values here.
 *
 * Merged UNDER the hydrated partial, so hydration and every later pick still
 * win; a real button with no bg-/text- token falls back to the dummy default,
 * which is the established absent-value contract (same posture as
 * `themeColorForToken`'s fallback swatch). */
const WEB_BUTTON_DUMMY_TOKENS: Partial<InspectorPresentationState> = {
  tokenBackgroundColor: "Primary",
  tokenTextColor: "White",
};

// FLAGGED F5 T19: no designed slot in the dummy frontend for a page/route
// section — minimal neutral controls pending founder/design ruling.
//
// It renders ONLY when no node is selected (the binding is null otherwise —
// `use-web-editing-session`), because a selected node means this panel is
// describing that node, and the page is not part of it. Every control here goes
// through the same one-op write path the rest of the inspector uses, and no
// write can fire on a draft the pure decisions refuse.
function PageSection({ binding }: { binding: WebPageSectionBinding }) {
  const {
    activePage,
    busy,
    errorEngineCode,
    onAddPage,
    onRemovePage,
    onSetPageMeta,
    pages,
  } = binding;
  const [open, setOpen] = useState(true);
  const [nameDraft, setNameDraft] = useState(activePage.name);
  const [routeDraft, setRouteDraft] = useState(activePage.route);
  const [routeMessage, setRouteMessage] = useState<string | null>(null);
  // Founder correction 2026-09-04: the NEW page has its own name AND route
  // boxes, in their own group — the route is suggested from the name while
  // the marketer has not typed one, and is visible before Add. The first
  // shape (one Name/Route pair over the live page, a bare "Add a page" box)
  // had a marketer rename and re-route the home page while trying to add one.
  const [newPageName, setNewPageName] = useState("");
  const [newPageRoute, setNewPageRoute] = useState("");
  const [newPageRouteTouched, setNewPageRouteTouched] = useState(false);
  const [addMessage, setAddMessage] = useState<string | null>(null);

  // The DOCUMENT's own page meta outranks whatever is in these boxes: a
  // committed write, an undo, or a page switch all mean the page on screen now
  // says something different, and a draft of the previous value would be this
  // panel lying about the document. React's adjust-state-on-prop-change (a
  // render-time comparison — the pattern `InspectorImageUpload` already uses),
  // never an effect. A REFUSED write reloads nothing, so the typed text
  // survives its own refusal, which is the point.
  const [seed, setSeed] = useState({
    id: activePage.id,
    name: activePage.name,
    route: activePage.route,
  });
  if (
    seed.id !== activePage.id ||
    seed.name !== activePage.name ||
    seed.route !== activePage.route
  ) {
    setSeed({ id: activePage.id, name: activePage.name, route: activePage.route });
    setNameDraft(activePage.name);
    setRouteDraft(activePage.route);
    setRouteMessage(null);
  }

  const siblings = pages.filter((candidate) => candidate.id !== activePage.id);
  // A refusal the field caught itself outranks the last server refusal — it is
  // what the user just did. The server's refusal reaches this field ONLY when
  // its engine code is one of the two route refusals, said in this section's own
  // words (engine prose — "route `/x` is already taken" — never reaches a
  // marketer). Anything else the write path failed on is not this section's to
  // narrate and stays in the inspector's one existing error line.
  const routeError = routeMessage ?? pageWriteMessage(errorEngineCode, null);
  const removable = pageIsRemovable(activePage, pages.length);

  const commitRoute = () => {
    if (busy) return;
    const decision = routeFieldDecision(routeDraft, activePage.route, siblings);
    if (decision.kind === "noop") {
      setRouteMessage(null);
      return;
    }
    if (decision.kind === "refuse") {
      setRouteMessage(decision.message);
      return;
    }
    setRouteMessage(null);
    onSetPageMeta(activePage.id, { route: decision.route });
  };

  const commitName = () => {
    if (busy) return;
    const name = nameDraft.trim();
    // An unnamed page is not an edit — nothing to write, and the box re-seeds
    // from the document on the next change either way.
    if (name === "" || name === activePage.name) return;
    onSetPageMeta(activePage.id, { name });
  };

  const commitAddPage = () => {
    if (busy) return;
    const decision = addPageDecision(newPageName, newPageRoute, pages);
    if (decision.kind === "refuse") {
      setAddMessage(decision.message);
      return;
    }
    setAddMessage(null);
    setNewPageName("");
    setNewPageRoute("");
    setNewPageRouteTouched(false);
    onAddPage(decision.page);
  };

  return (
    <InspectorSection label="Page" onOpenChange={setOpen} open={open}>
      <p className={styles.inspectorPageGroup}>This page</p>
      <InspectorField label="Name">
        <InspectorInput
          ariaLabel="Page name"
          disabled={busy}
          onChange={setNameDraft}
          onCommit={commitName}
          value={nameDraft}
        />
      </InspectorField>
      <InspectorField label="Route">
        <InspectorInput
          ariaLabel="Page route"
          disabled={busy}
          onChange={(value) => {
            setRouteDraft(value);
            setRouteMessage(null);
          }}
          onCommit={commitRoute}
          value={routeDraft}
        />
      </InspectorField>
      {routeError ? (
        <p className={styles.inspectorPageMessage} role="alert">
          {routeError}
        </p>
      ) : null}
      <div className={styles.inspectorPageActions}>
        <button
          className={styles.inspectorPageButton}
          // The engine refuses removing a document's last page, and a site
          // without "/" serves nothing at its own root — so the button simply
          // cannot offer an action that could not succeed.
          disabled={busy || !removable}
          onClick={() => {
            if (busy || !removable) return;
            onRemovePage(activePage.id);
          }}
          type="button"
        >
          Remove page
        </button>
      </div>
      <p className={styles.inspectorPageGroup}>New page</p>
      <InspectorField label="Name">
        <InspectorInput
          ariaLabel="New page name"
          disabled={busy}
          onChange={(value) => {
            setNewPageName(value);
            setAddMessage(null);
            if (!newPageRouteTouched) setNewPageRoute(suggestedRouteForName(value));
          }}
          onCommit={commitAddPage}
          value={newPageName}
        />
      </InspectorField>
      <InspectorField label="Route">
        <InspectorInput
          ariaLabel="New page route"
          disabled={busy}
          onChange={(value) => {
            setNewPageRoute(value);
            // Clearing the box hands the route back to the name's suggestion.
            setNewPageRouteTouched(value.trim() !== "");
            setAddMessage(null);
          }}
          onCommit={commitAddPage}
          value={newPageRoute}
        />
      </InspectorField>
      {addMessage ? (
        <p className={styles.inspectorPageMessage} role="alert">
          {addMessage}
        </p>
      ) : null}
      <div className={styles.inspectorPageActions}>
        <button
          className={styles.inspectorPageButton}
          disabled={busy}
          onClick={commitAddPage}
          type="button"
        >
          Add page
        </button>
      </div>
    </InspectorSection>
  );
}

// R-A6 (slice 3): the human's own text edits inside the selected cloned band.
//
// A plain list in the inspector's existing field styling — deliberately, per the
// founder's ruling for this slice: the visual treatment is reviewed separately,
// and inventing chrome for it here would be inventing UI while wiring. Each row
// says the structural PATH verbatim (the client holds no HTML, so there is no
// honest human name for the element — the API resolves that when the agent is
// briefed) and the words the human typed, with a Clear that takes the edit back.
//
// Nothing renders when the selection owns no list, and nothing renders when the
// list is empty: an unedited clone has nothing to say here.
function CloneTextEditsSection({ binding }: { binding: WebCloneTextEditsBinding }) {
  const [open, setOpen] = useState(true);
  return (
    <InspectorSection label="Cloned text edits" onOpenChange={setOpen} open={open}>
      <div className={styles.inspectorCloneEdits}>
        {binding.overrides.map((row) => (
          <InspectorField key={row.path} label={row.path}>
            <span className={styles.inspectorCloneEditRow}>
              <span className={styles.inspectorCloneEditText} title={row.override.text}>
                {row.override.text}
              </span>
              <button
                className={styles.inspectorPageButton}
                disabled={binding.busy}
                onClick={() => {
                  if (binding.busy) return;
                  binding.onClear(row.path);
                }}
                type="button"
              >
                Clear
              </button>
            </span>
          </InspectorField>
        ))}
      </div>
    </InspectorSection>
  );
}

export function WebInspector({
  addressing,
  cloneTextEdits = null,
  customComponentForm = null,
  error = null,
  hydrated,
  layers,
  layoutOnly = false,
  note = null,
  onReplaceImage,
  onSelectionChange,
  onSelectLayer,
  pageSection = null,
  reviewMenuEnabled = false,
  richTextRange = null,
  selection,
  showLayers = true,
  themeColors,
}: {
  /** W3.2: an inline write error (422 first diagnostic / transport). The
   * minimal pre-W3.3 floor — the save-failure surface is the W3.3 founder
   * gate; do not grow this beyond one line without that ruling. */
  error?: string | null;
  /** W3.2: a transient informational note (409 quiet reload). Same W3.3
   * floor as `error`. */
  note?: string | null;
  /** W3.1: write addressing stamped onto every inspector event this panel
   * dispatches — passed through to the controllers verbatim. */
  addressing?: InspectorEventAddressing;
  /** R-A6 (slice 3): the selected cloned band's human text edits, each with the
   * Clear that takes it back. The session decides whether the selection owns a
   * list at all (the fragment, or the section a pin is born wrapped in);
   * absent/null — and an empty list — render no section, which is every dummy
   * state and every non-clone selection. */
  cloneTextEdits?: WebCloneTextEditsBinding | null;
  /** W4.7 (contract item 34): the selected custom component's pinned artifact
   * + live props, feeding the schema-driven props form. A custom component
   * falls to the §5 layout-only fallback, so ONLY that view (ContainerControls)
   * consumes this; the other schemas are untouched. Null/absent → no props
   * section — which is also what a loading or failed artifact fetch yields
   * (ledgered ruling, 2026-08-18: the fallback stands alone, no loading shell,
   * no error chrome). */
  customComponentForm?: CustomComponentFormBinding | null;
  /** W2.2: real values for the selected node (design-editor hydrate adapter),
   * merged over the dummy defaults at mount. Callers remount per selection. */
  hydrated?: Partial<InspectorPresentationState>;
  /** W2.3: real document layer rows (design-editor `buildWebLayerRows`).
   * When present, every schema's Layers section renders them instead of its
   * fixture tree; absent keeps the dummy fixtures untouched. */
  layers?: WebLayerRow[];
  /** W5.1 (§5): the schema mapper's own flag for the selected node
   * (`inspectorSelectionFor(...).layoutOnly`) — true for the unknown-kind
   * fallback: embeds (item 32), the interactive components (item 33), and
   * anything unmapped, all of which route to the CONTAINER view. Only that
   * view consumes it, and only to hide the sections §5 rules out (Link-to,
   * Style, Alignment); every other schema is untouched, and the icon schema's
   * own trim (18b) is already unconditional in `IconControls`. Absent/false →
   * a real container renders exactly as before. */
  layoutOnly?: boolean;
  /** W4.2 §1 row 12: the image schema's Replace-image pick. The File travels
   * by prop to the editor surface, which uploads it and applies the
   * `upsert_asset`+`replace_asset` batch; absent keeps the dummy's
   * local-preview-only behavior. */
  onReplaceImage?: (file: File) => void;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  /** W2.3: a layer-row click — callers send bridge `selectNode`. */
  onSelectLayer?: (nodeId: string) => void;
  /** F5 task 19 (FLAGGED — no designed slot): the page/route controls. The
   * session hands this over only while NO node is selected, so the section can
   * never render beside a node's own controls; absent/null → no Page section at
   * all, which is every dummy-state mount. */
  pageSection?: WebPageSectionBinding | null;
  reviewMenuEnabled?: boolean;
  /** W4.8b (contract item 3): the live rich-text range whose link the TEXT
   * schema's "Link to" section edits — supplied by the owner only while a
   * range is actually selected (`richTextLinkSectionVisible`). Null/absent →
   * the text schema shows no Link-to section at all (§2 hidden = absent). Only
   * the text schema consumes it; the other six schemas' node-href LinkSection
   * is untouched. */
  richTextRange?: RichTextLinkBinding | null;
  selection: ChatShellInspectorSelection;
  showLayers?: boolean;
  /** W4.0: the document's real theme tokens (design-editor
   * `buildThemeColorOptions`) for the color pickers' Theme tab; absent keeps
   * the dummy's fixture palette. */
  themeColors?: readonly ThemeColorOption[];
}) {
  const inspectorRef = useRef<HTMLElement>(null);
  const [reviewMenuOpen, setReviewMenuOpen] = useState(false);
  const webSelection: WebInspectorSelection = WEB_INSPECTOR_SELECTIONS.includes(
    selection as WebInspectorSelection,
  )
    ? (selection as WebInspectorSelection)
    : "canvas";
  const canvasController = useInspectorController([], "canvas", hydrated, addressing);
  const textController = useInspectorController(["link"], "text", hydrated, addressing);
  const imageController = useInspectorController(["link"], "image", hydrated, addressing);
  // Row 17: the button schema's two token chips start from the WEB dummy's
  // designed values (see WEB_BUTTON_DUMMY_TOKENS); everything else is the
  // shared default, and the hydrated partial still overrides both.
  const buttonController = useInspectorController(["link"], "button", { ...WEB_BUTTON_DUMMY_TOKENS, ...hydrated }, addressing);
  const iconController = useInspectorController(["link"], "icon", hydrated, addressing);
  const containerController = useInspectorController(["link"], "container", hydrated, addressing);
  const sectionController = useInspectorController(["link"], "section", hydrated, addressing);
  const documentLayers = layers ? (
    <DocumentLayers onSelectLayer={onSelectLayer} rows={layers} />
  ) : null;
  const canvasLayerTree = useInspectorLayerTree("canvas-text", ["group"], "canvas");
  const textLayerTree = useInspectorLayerTree("text", ["div1", "div2"], "text");
  const imageLayerTree = useInspectorLayerTree("image", ["div1", "div2"], "image");
  const buttonLayerTree = useInspectorLayerTree("button", ["div1", "div2"], "button");
  const iconLayerTree = useInspectorLayerTree("icon", ["div1", "div2"], "icon");
  const containerLayerTree = useInspectorLayerTree("container", ["div1", "div2"], "container");
  const sectionLayerTree = useInspectorLayerTree("section", ["div1", "div2"], "section");
  const controllers: Record<WebInspectorSelection, InspectorController> = {
    button: buttonController,
    canvas: canvasController,
    container: containerController,
    icon: iconController,
    image: imageController,
    section: sectionController,
    text: textController,
  };
  const activeController = controllers[webSelection];

  useEffect(() => {
    if (!reviewMenuOpen) return;

    const dismiss = (event: PointerEvent) => {
      if (!inspectorRef.current?.contains(event.target as Node)) {
        setReviewMenuOpen(false);
      }
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setReviewMenuOpen(false);
    };

    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [reviewMenuOpen]);

  // F5 task 19: does the Page section speak for the current write error? Only
  // the two route refusals it can provoke and word itself.
  const pageSectionOwnsError =
    pageSection !== null && pageWriteMessage(pageSection.errorEngineCode, null) !== null;

  const reviewMenu = reviewMenuEnabled && reviewMenuOpen ? (
    <div aria-label="Preview inspector element types" className={styles.inspectorVariantMenu} role="menu">
      <span className={styles.inspectorVariantMenuLabel}>Element controls</span>
      {WEB_INSPECTOR_SELECTIONS.map((variant) => (
        <button
          aria-checked={webSelection === variant}
          className={webSelection === variant ? styles.inspectorVariantMenuItemActive : ""}
          key={variant}
          onClick={() => {
            onSelectionChange(variant);
            setReviewMenuOpen(false);
          }}
          role="menuitemradio"
          type="button"
        >
          <span>{INSPECTOR_REVIEW_LABELS[variant]}</span>
          <span aria-hidden="true">{selection === variant ? "✓" : ""}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <aside aria-label="Web inspector" className={styles.inspector} ref={inspectorRef}>
      <div className={styles.inspectorRail}>
        <InspectorHeader
          actionMenu={reviewMenu}
          elementActions={webSelection !== "canvas"}
          locked={activeController.state.locked}
          moreActionsExpanded={reviewMenuEnabled ? reviewMenuOpen : undefined}
          moreActionsHasPopup={reviewMenuEnabled}
          onLockToggle={() => activeController.setValue("locked", !activeController.state.locked)}
          onMoreActions={() => {
            activeController.requestAction("more-actions");
            if (reviewMenuEnabled) setReviewMenuOpen((open) => !open);
          }}
          onVisibilityToggle={() => activeController.setValue("visible", !activeController.state.visible)}
          title={INSPECTOR_TITLES[webSelection]}
          visible={activeController.state.visible}
        />
        {/* W3.2 floor pending the W3.3 founder gate: one inline line for the
            write path's note (409 quiet reload) / error (422 diagnostic). */}
        {note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {note}
          </p>
        ) : null}
        {/* F5 task 19: a ROUTE refusal is said beside the route field that
            caused it, in the section's own words — so this line stands down for
            exactly those two codes rather than repeating the same failure
            twice. Every other failure still lands here, unchanged. */}
        {error && !pageSectionOwnsError ? (
          <p className={styles.inspectorStatusError} role="alert">
            {error}
          </p>
        ) : null}
        {pageSection ? <PageSection binding={pageSection} /> : null}
        {cloneTextEdits && cloneTextEdits.overrides.length > 0 ? (
          <CloneTextEditsSection binding={cloneTextEdits} />
        ) : null}
        <ThemeColorsContext.Provider value={themeColors}>
          <DocumentLayersContext.Provider value={documentLayers}>
            {webSelection === "canvas" ? <CanvasControls controller={canvasController} layerTree={canvasLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {webSelection === "text" ? <TextControls controller={textController} layerTree={textLayerTree} onSelectionChange={onSelectionChange} richTextRange={richTextRange} showLayers={showLayers} /> : null}
            {webSelection === "image" ? <ImageControls controller={imageController} layerTree={imageLayerTree} onReplaceImage={onReplaceImage} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {webSelection === "button" ? <ButtonControls controller={buttonController} layerTree={buttonLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {webSelection === "icon" ? <IconControls controller={iconController} layerTree={iconLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {webSelection === "container" ? <ContainerControls controller={containerController} customComponentForm={customComponentForm} layerTree={containerLayerTree} layoutOnly={layoutOnly} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
            {webSelection === "section" ? <SectionControls controller={sectionController} layerTree={sectionLayerTree} onSelectionChange={onSelectionChange} showLayers={showLayers} /> : null}
          </DocumentLayersContext.Provider>
        </ThemeColorsContext.Provider>
      </div>
    </aside>
  );
}
