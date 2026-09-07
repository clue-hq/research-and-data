import React, { useState } from "react";

import {
  buildWebButtonProps,
  classifyEmbedUrl,
  composeSlotKey,
  duplicateSubtree,
  insertNodeOp,
  isValidSlotKey,
  moveNodeOp,
  parentOfInPage,
  richTextDocumentHasStructure,
  removeNodeOp,
  setNodeClassesOp,
  setNodePropsOp,
  setPageMetaOp,
  setSlotKeyOp,
  slotKeyParts,
  textVariantAllowsStructuredRichText,
  webNodeButtonAction,
  type WebButtonAction,
  type WebBackgroundImage,
  type WebDialogOption,
  type WebNode,
  type WebNodeProps,
  type WebOperation,
  type WebPageSummary,
  type WebTheme
} from "@/engine/webDocuments";
import type { CustomComponentArtifact } from "@/engine/webDocuments";
import { routeFieldDecision } from "@/components/web/inspectorPageField";
import {
  alignItemsFacet,
  bgColorFacet,
  directionFacet,
  displayFacet,
  elementDimensionValue,
  flexWrapFacet,
  fontWeightFacet,
  gapFacet,
  gridColumnsFacet,
  italicFacet,
  justifyContentFacet,
  lineHeightFacet,
  lineThroughFacet,
  marginXFacet,
  marginYFacet,
  objectFitFacet,
  objectPositionFacet,
  paddingXFacet,
  paddingYFacet,
  setElementDimensionClass,
  textAlignFacet,
  textColorFacet,
  textSizeFacet,
  underlineFacet,
  ALIGN_ITEMS_VALUES,
  FLEX_WRAP_VALUES,
  FONT_WEIGHT_VALUES,
  GRID_COLUMN_VALUES,
  JUSTIFY_CONTENT_VALUES,
  LINE_HEIGHT_VALUES,
  OBJECT_FIT_VALUES,
  OBJECT_POSITION_VALUES,
  TEXT_SIZE_RAMP,
  SPACING_STEPS,
  type ClassFacet
} from "@/engine/webClassFacets";
import type {
  RichTextFormat,
  RichTextFormatState,
  RichTextFormatValue,
  WebNodeInfo
} from "@/engine/webBridge";
import type { WebCustomComponentRuntimeState } from "@/engine/webBridge";
import {
  RICH_TEXT_MARK_CONTROLS,
  richTextAriaPressed
} from "@/engine/webRichText";
import {
  WebCustomComponentInspector,
  type CustomComponentArtifactStatus
} from "@/components/web/WebCustomComponentInspector";
import {
  WebDormantSectionsCard,
  WebFragmentInspector,
  type FragmentAssetOption,
  type FragmentCardStatus
} from "@/components/web/WebFragmentInspector";
import type { FragmentCard } from "@/engine/webFragmentCards";

/**
 * The Inspect-mode panel: reads the selected node from the loaded WebDoc and
 * exposes per-kind property controls plus a universal class escape hatch. Pure
 * presentation per docs/frontend-practices.md rule 2 — every control builds ONE
 * operation (a class rewrite via {@link ClassFacet}, or a whole-props edit) and
 * fires `applyOps`; the hook owns persistence, base-version, and 409/422.
 *
 * Solid vs derived: a facet control shows the parsed value when the utility is
 * present (solid) and "Default" otherwise (derived). The computed-layout card
 * reports the browser's resolved value separately; it does not turn an
 * inherited/default value into an authored utility.
 */

interface WebInspectorPanelProps {
  node: WebNode | null;
  /** Read-only measurements from the instrumented iframe render. */
  nodeInfo: WebNodeInfo | null;
  /** The page the node lives in — the `page_id` every op carries. */
  pageId: string;
  /** The full page summary — the sibling/parent lookup the header's
   * reorder/duplicate/delete actions need. */
  page: WebPageSummary | null;
  /** Every page in the document — the Page card's route field needs the OTHER
   * pages' routes to refuse a collision before the round trip. */
  pages: readonly WebPageSummary[];
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
  /** Open the asset drawer to set/replace this section/container background. */
  onChooseBackground: (nodeId: string) => void;
  editingNodeId: string | null;
  richTextFormats: RichTextFormatState | null;
  formatRichText: (nodeId: string, format: RichTextFormat) => void;
  customComponentArtifact: CustomComponentArtifact | null;
  customComponentArtifactStatus: CustomComponentArtifactStatus;
  customComponentArtifactError: string | null;
  customComponentRuntime: WebCustomComponentRuntimeState | null;
  customComponentRepublishRequired: boolean;
  onEditCustomComponentWithAI: (node: WebNode) => void;
  onRepublish: () => void;
  /** The selected cloned section's registry card (F3.2) — its status, condition,
   * repair lineage, hidden-on-source provenance and slot manifest. */
  fragmentCard: FragmentCard | null;
  fragmentCardStatus: FragmentCardStatus;
  fragmentCardError: string | null;
  /** Every section the source site HIDES (D-F8). They are on no page, so nothing can select
   * one — and the inspector is the only place a human is shown them. */
  dormantSections: FragmentCard[];
  /** The document's own asset records — what an asset slot may resolve to (LUMW0035). */
  documentAssets: FragmentAssetOption[];
  onGenerateFragmentPreview: (fragmentId: string) => void;
  onActivateFragment: (fragmentId: string) => void;
  onRetireFragment: (fragmentId: string) => void;
  fragmentActionBusy: boolean;
  fragmentActionError: string | null;
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
  nodeInfo,
  pageId,
  page,
  pages,
  theme,
  dialogs,
  previewComponent,
  selectNode,
  onReplaceImage,
  onChooseBackground,
  editingNodeId,
  richTextFormats,
  formatRichText,
  customComponentArtifact,
  customComponentArtifactStatus,
  customComponentArtifactError,
  customComponentRuntime,
  customComponentRepublishRequired,
  onEditCustomComponentWithAI,
  onRepublish,
  fragmentCard,
  fragmentCardStatus,
  fragmentCardError,
  dormantSections,
  documentAssets,
  onGenerateFragmentPreview,
  onActivateFragment,
  onRetireFragment,
  fragmentActionBusy,
  fragmentActionError,
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
        {/* F5: the page itself is only describable when NO node is selected — a
            selected node means this panel is describing that node, and the page
            is not part of it. The dev shell carries the route field alone; the
            platform shell owns add/remove. */}
        {page ? (
          <PageCard page={page} pages={pages} busy={busy} applyOps={applyOps} />
        ) : null}
        {/* D-F8: a hidden-on-source section is on no page, so it can never be selected — and
            the inspector is the ONE place a human sees and activates one. The empty state is
            where it is always reachable, rather than only while some other node happens to be
            selected. */}
        <WebDormantSectionsCard
          sections={dormantSections}
          busy={fragmentActionBusy}
          error={fragmentActionError}
          onGeneratePreview={onGenerateFragmentPreview}
          onActivate={onActivateFragment}
        />
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

      <ComputedLayoutCard info={nodeInfo} />

      {/* Field state (text inputs, textarea) is seeded from the node, so remount
          it when the selection changes. */}
      <WebInspectorBody
        key={node.id}
        node={node}
        nodeInfo={nodeInfo}
        pageId={pageId}
        theme={theme}
        dialogs={dialogs}
        previewComponent={previewComponent}
        selectNode={selectNode}
        onReplaceImage={onReplaceImage}
        onChooseBackground={onChooseBackground}
        editingNodeId={editingNodeId}
        richTextFormats={richTextFormats}
        formatRichText={formatRichText}
        customComponentArtifact={customComponentArtifact}
        customComponentArtifactStatus={customComponentArtifactStatus}
        customComponentArtifactError={customComponentArtifactError}
        customComponentRuntime={customComponentRuntime}
        customComponentRepublishRequired={customComponentRepublishRequired}
        onEditCustomComponentWithAI={onEditCustomComponentWithAI}
        onRepublish={onRepublish}
        fragmentCard={fragmentCard}
        fragmentCardStatus={fragmentCardStatus}
        fragmentCardError={fragmentCardError}
        documentAssets={documentAssets}
        onGenerateFragmentPreview={onGenerateFragmentPreview}
        onActivateFragment={onActivateFragment}
        onRetireFragment={onRetireFragment}
        fragmentActionBusy={fragmentActionBusy}
        fragmentActionError={fragmentActionError}
        applyOps={applyOps}
        busy={busy}
      />
    </div>
  );
}

function metricNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function boxValues(
  top: string,
  right: string,
  bottom: string,
  left: string
): string {
  return `${top} ${right} ${bottom} ${left}`;
}

function ComputedLayoutCard({ info }: { info: WebNodeInfo | null }): React.ReactElement {
  if (!info) {
    return (
      <Card title="Computed layout">
        <p className="web-insp-hint">Waiting for the rendered node measurement.</p>
      </Card>
    );
  }
  const rect = info.geometry.document;
  const style = info.computedStyle;
  const isFlex = style.display.includes("flex");
  const isGrid = style.display.includes("grid");
  return (
    <Card title="Computed layout">
      <dl className="web-insp-metrics">
        <div>
          <dt>Size</dt>
          <dd>
            {metricNumber(rect.width)} × {metricNumber(rect.height)} px
          </dd>
        </div>
        <div>
          <dt>Position</dt>
          <dd>
            {metricNumber(rect.x)}, {metricNumber(rect.y)} px
          </dd>
        </div>
        <div>
          <dt>Parent</dt>
          <dd>{info.parentNodeId ?? "page"}</dd>
        </div>
        <div>
          <dt>Children</dt>
          <dd>{info.childNodeIds.length}</dd>
        </div>
        <div>
          <dt>Display</dt>
          <dd>{style.display || "—"}</dd>
        </div>
        <div>
          <dt>Positioning</dt>
          <dd>{style.position || "—"}</dd>
        </div>
        <div>
          <dt>CSS size</dt>
          <dd>
            {style.width || "—"} × {style.height || "—"}
          </dd>
        </div>
        <div>
          <dt>Constraints</dt>
          <dd>
            {style.minWidth || "0"}…{style.maxWidth || "none"} ·{" "}
            {style.minHeight || "0"}…{style.maxHeight || "none"}
          </dd>
        </div>
        <div className="is-wide">
          <dt>Padding</dt>
          <dd>
            {boxValues(
              style.paddingTop,
              style.paddingRight,
              style.paddingBottom,
              style.paddingLeft
            )}
          </dd>
        </div>
        <div className="is-wide">
          <dt>Margin</dt>
          <dd>
            {boxValues(
              style.marginTop,
              style.marginRight,
              style.marginBottom,
              style.marginLeft
            )}
          </dd>
        </div>
        {isFlex ? (
          <>
            <div>
              <dt>Flex</dt>
              <dd>
                {style.flexDirection} · {style.flexWrap}
              </dd>
            </div>
            <div>
              <dt>Alignment</dt>
              <dd>
                {style.justifyContent} · {style.alignItems}
              </dd>
            </div>
          </>
        ) : null}
        {isFlex || isGrid ? (
          <div>
            <dt>Gap</dt>
            <dd>{style.gap || "—"}</dd>
          </div>
        ) : null}
        {isGrid ? (
          <div className="is-wide">
            <dt>Grid columns</dt>
            <dd>{style.gridTemplateColumns || "—"}</dd>
          </div>
        ) : null}
        {info.tv || info.btn ? (
          <>
            <div>
              <dt>Type</dt>
              <dd>
                {style.fontSize} / {style.lineHeight} · {style.fontWeight}
              </dd>
            </div>
            <div>
              <dt>Text align</dt>
              <dd>{style.textAlign || "—"}</dd>
            </div>
          </>
        ) : null}
        <div>
          <dt>Radius</dt>
          <dd>{style.borderRadius || "—"}</dd>
        </div>
        <div>
          <dt>Opacity</dt>
          <dd>{style.opacity || "—"}</dd>
        </div>
        {info.tag === "img" ? (
          <div className="is-wide">
            <dt>Image fit</dt>
            <dd>
              {style.objectFit || "—"} · {style.objectPosition || "—"}
            </dd>
          </div>
        ) : null}
        <div className="is-wide">
          <dt>Colors</dt>
          <dd>
            {style.color || "—"} on {style.backgroundColor || "—"}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

/** The nothing-selected state's Page card: the active page's route, editable.
 *
 * Commit is blur/Enter (the same shape every other text field in this panel
 * uses) and goes through `routeFieldDecision`, so an unchanged draft writes
 * nothing and an ungrammatical or already-taken route is refused HERE — no op
 * is built at all, and the typed text survives its own refusal so it can be
 * corrected. Parity with the platform shell's Page section, minus add/remove:
 * the dev shell stays minimal. */
function PageCard({
  page,
  pages,
  busy,
  applyOps
}: {
  page: WebPageSummary;
  pages: readonly WebPageSummary[];
  busy: boolean;
  applyOps: (operations: WebOperation[], intent?: string) => void;
}): React.ReactElement {
  const [draft, setDraft] = useState(page.route);
  const [message, setMessage] = useState<string | null>(null);
  // The DOCUMENT's route outranks the box: a committed write, an undo, or a
  // page switch all mean the page on screen now says something different, and
  // a stale draft would be this card lying about the document.
  React.useEffect(() => {
    setDraft(page.route);
    setMessage(null);
  }, [page.id, page.route]);

  const commit = () => {
    if (busy) {
      return;
    }
    const siblingRoutes = pages
      .filter((candidate) => candidate.id !== page.id)
      .map((candidate) => candidate.route);
    const decision = routeFieldDecision(draft, page.route, siblingRoutes);
    if (decision.kind === "noop") {
      setMessage(null);
      return;
    }
    if (decision.kind === "refuse") {
      setMessage(decision.message);
      return;
    }
    setMessage(null);
    applyOps([setPageMetaOp(page.id, { route: decision.route })], "set_page_route");
  };

  return (
    <Card title="Page">
      <p className="web-insp-hint">{page.name}</p>
      <label className="field web-insp-field">
        <span className="field-label">Route</span>
        <input
          type="text"
          value={draft}
          disabled={busy}
          spellCheck={false}
          aria-label="Page route"
          onChange={(event) => {
            setDraft(event.target.value);
            setMessage(null);
          }}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
      </label>
      {message ? (
        <p className="web-insp-error" role="alert">
          {message}
        </p>
      ) : null}
    </Card>
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
  nodeInfo: WebNodeInfo | null;
  pageId: string;
  theme: WebTheme | null;
  dialogs: WebDialogOption[];
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  selectNode: (nodeId: string) => void;
  onReplaceImage: (nodeId: string) => void;
  onChooseBackground: (nodeId: string) => void;
  editingNodeId: string | null;
  richTextFormats: RichTextFormatState | null;
  formatRichText: (nodeId: string, format: RichTextFormat) => void;
  customComponentArtifact: CustomComponentArtifact | null;
  customComponentArtifactStatus: CustomComponentArtifactStatus;
  customComponentArtifactError: string | null;
  customComponentRuntime: WebCustomComponentRuntimeState | null;
  customComponentRepublishRequired: boolean;
  onEditCustomComponentWithAI: (node: WebNode) => void;
  onRepublish: () => void;
  fragmentCard: FragmentCard | null;
  fragmentCardStatus: FragmentCardStatus;
  fragmentCardError: string | null;
  documentAssets: FragmentAssetOption[];
  onGenerateFragmentPreview: (fragmentId: string) => void;
  onActivateFragment: (fragmentId: string) => void;
  onRetireFragment: (fragmentId: string) => void;
  fragmentActionBusy: boolean;
  fragmentActionError: string | null;
  applyOps: (operations: WebOperation[], intent?: string) => void;
  busy: boolean;
}

function WebInspectorBody({
  node,
  nodeInfo,
  pageId,
  theme,
  dialogs,
  previewComponent,
  selectNode,
  onReplaceImage,
  onChooseBackground,
  editingNodeId,
  richTextFormats,
  formatRichText,
  customComponentArtifact,
  customComponentArtifactStatus,
  customComponentArtifactError,
  customComponentRuntime,
  customComponentRepublishRequired,
  onEditCustomComponentWithAI,
  onRepublish,
  fragmentCard,
  fragmentCardStatus,
  fragmentCardError,
  documentAssets,
  onGenerateFragmentPreview,
  onActivateFragment,
  onRetireFragment,
  fragmentActionBusy,
  fragmentActionError,
  applyOps,
  busy
}: BodyProps): React.ReactElement {
  const applyClasses = (facet: ClassFacet, value: string | null, intent: string) => {
    const classes = facet.set(node.classes, value);
    if (classes !== node.classes) {
      applyOps([setNodeClassesOp(pageId, node.id, classes)], intent);
    }
  };
  const applyDimension = (axis: "width" | "height", value: string | null) => {
    const classes = setElementDimensionClass(node.classes, axis, value);
    if (classes !== node.classes) {
      applyOps([setNodeClassesOp(pageId, node.id, classes)], `resize_${axis}`);
    }
  };
  const applyProps = (props: WebNodeProps, intent: string) => {
    applyOps([setNodePropsOp(pageId, node.id, props)], intent);
  };

  // A cloned section gets its OWN body and none of the generic cards (F3.2). That is the D-F3
  // ruling made structural rather than remembered: the class escape hatch would let somebody
  // write `h-[3000px]` onto a frozen band — the manual resize the ruling forbids — and the
  // spacing card would re-lay-out somebody else's section from the outside. The slot values are
  // the whole editing surface a clone has, and they are what this card offers.
  if (node.kind === "fragment") {
    return (
      <div className="web-insp-cards">
        <WebFragmentInspector
          node={node}
          card={fragmentCard}
          cardStatus={fragmentCardStatus}
          cardError={fragmentCardError}
          documentAssets={documentAssets}
          busy={busy}
          applyProps={applyProps}
          onGeneratePreview={onGenerateFragmentPreview}
          onActivate={onActivateFragment}
          onRetire={onRetireFragment}
          actionBusy={fragmentActionBusy}
          actionError={fragmentActionError}
        />
      </div>
    );
  }

  return (
    <div className="web-insp-cards">
      {node.kind === "text" ? (
        <TextCard
          node={node}
          busy={busy}
          editing={editingNodeId === node.id}
          richTextFormats={editingNodeId === node.id ? richTextFormats : null}
          formatRichText={formatRichText}
          applyClasses={applyClasses}
          applyProps={applyProps}
        />
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
      {node.kind === "custom_component" ? (
        <WebCustomComponentInspector
          node={node}
          artifact={customComponentArtifact}
          artifactStatus={customComponentArtifactStatus}
          artifactError={customComponentArtifactError}
          runtime={customComponentRuntime}
          republishRequired={customComponentRepublishRequired}
          busy={busy}
          applyProps={(props) =>
            applyProps(
              {
                kind: "custom_component",
                slug: node.slug ?? "",
                artifact_id: node.artifact_id ?? "",
                props
              },
              "set_custom_component_props"
            )
          }
          onEditWithAI={() => onEditCustomComponentWithAI(node)}
          onRepublish={onRepublish}
        />
      ) : null}
      {(node.kind === "container" || node.kind === "section") ? (
        <ContainerCard node={node} busy={busy} applyClasses={applyClasses} />
      ) : null}
      {node.kind === "container" ? (
        <ContainerLinkCard node={node} busy={busy} applyProps={applyProps} />
      ) : null}
      {node.kind === "container" || node.kind === "section" ? (
        <BackgroundImageCard
          node={node}
          busy={busy}
          applyProps={applyProps}
          onChooseBackground={onChooseBackground}
        />
      ) : null}
      {node.kind === "image" ? (
        <ImageCard
          node={node}
          busy={busy}
          applyClasses={applyClasses}
          applyProps={applyProps}
          onReplaceImage={onReplaceImage}
        />
      ) : null}
      {node.kind === "embed" ? <EmbedCard node={node} busy={busy} applyProps={applyProps} /> : null}

      {["text", "button", "container", "section"].includes(node.kind) ? (
        <AppearanceCard
          node={node}
          nodeInfo={nodeInfo}
          theme={theme}
          busy={busy}
          applyClasses={applyClasses}
        />
      ) : null}
      {["container", "text", "button", "image", "custom_component"].includes(node.kind) ? (
        <SizeCard
          node={node}
          nodeInfo={nodeInfo}
          busy={busy}
          applyDimension={applyDimension}
        />
      ) : null}
      <SpacingCard node={node} busy={busy} applyClasses={applyClasses} />
      <PersonalizationCard node={node} pageId={pageId} busy={busy} applyOps={applyOps} />
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
  disabledOptions = [],
  disabled,
  onChange
}: {
  label: string;
  value: string;
  options: readonly string[];
  disabledOptions?: readonly string[];
  disabled: boolean;
  onChange: (value: string) => void;
}): React.ReactElement {
  return (
    <label className="field web-insp-field">
      <span className="field-label">{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option
            key={option}
            value={option}
            disabled={disabledOptions.includes(option)}
          >
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function ThemeColorControl({
  label,
  facet,
  classes,
  theme,
  computedValue,
  busy,
  onChange
}: {
  label: string;
  facet: ClassFacet;
  classes: string;
  theme: WebTheme | null;
  computedValue: string;
  busy: boolean;
  onChange: (value: string | null) => void;
}): React.ReactElement {
  const value = facet.parse(classes);
  // Theme payloads also carry implementation aliases (`palette-*`,
  // `surface-*`, `text-*`, border roles). The picker should feel like the
  // compact brand palette from the recordings, not a dump of every compiled
  // CSS variable; raw aliases remain editable through CSS classes.
  const tokens = theme
    ? Object.entries(theme.tokens).filter(
        ([token]) =>
          !/^(?:palette-|surface-|text-|border-)/.test(token) &&
          token !== "focus-ring" &&
          token !== "accent-primary"
      )
    : [];
  return (
    <div className="field web-insp-field">
      <span className="field-label">{label}</span>
      <span className="web-insp-value-state">
        {value ? `Authored · ${value}` : `Derived · ${computedValue || "browser default"}`}
      </span>
      {tokens.length > 0 ? (
        <div className="web-swatch-grid" role="group" aria-label={label}>
          {tokens.map(([token, cssColor]) => (
            <button
              key={token}
              type="button"
              title={token}
              aria-label={`${label}: ${token}`}
              aria-pressed={value === token}
              disabled={busy}
              className={`web-swatch${value === token ? " is-selected" : ""}`}
              style={{ backgroundColor: cssColor }}
              onClick={() => onChange(token)}
            />
          ))}
          <button
            type="button"
            className={`web-swatch is-clear${value === null ? " is-selected" : ""}`}
            aria-label={`Default ${label.toLowerCase()}`}
            title="Clear authored color"
            disabled={busy}
            onClick={() => onChange(null)}
          >
            ×
          </button>
        </div>
      ) : (
        <p className="web-insp-hint">No theme colors available.</p>
      )}
    </div>
  );
}

function AppearanceCard({
  node,
  nodeInfo,
  theme,
  busy,
  applyClasses
}: {
  node: WebNode;
  nodeInfo: WebNodeInfo | null;
  theme: WebTheme | null;
  busy: boolean;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
}): React.ReactElement {
  return (
    <Card title="Appearance">
      <ThemeColorControl
        label="Text color"
        facet={textColorFacet}
        classes={node.classes}
        theme={theme}
        computedValue={nodeInfo?.computedStyle.color ?? ""}
        busy={busy}
        onChange={(next) => applyClasses(textColorFacet, next, "text_color")}
      />
      <ThemeColorControl
        label="Background color"
        facet={bgColorFacet}
        classes={node.classes}
        theme={theme}
        computedValue={nodeInfo?.computedStyle.backgroundColor ?? ""}
        busy={busy}
        onChange={(next) => applyClasses(bgColorFacet, next, "background_color")}
      />
    </Card>
  );
}

type DimensionParseResult =
  | { kind: "ok"; value: string | null }
  | { kind: "error"; message: string };

function parseDimensionDraft(axis: "width" | "height", draft: string): DimensionParseResult {
  let value = draft.trim();
  if (value === "" || value.toLowerCase() === "default") {
    return { kind: "ok", value: null };
  }
  const ownPrefix = axis === "width" ? "w-" : "h-";
  const otherPrefix = axis === "width" ? "h-" : "w-";
  if (value.startsWith(otherPrefix)) {
    return { kind: "error", message: `Use a ${ownPrefix} class for ${axis}.` };
  }
  if (value.startsWith(ownPrefix)) {
    value = value.slice(ownPrefix.length);
  }
  if (/^\d+(?:\.\d+)?(?:px)?$/.test(value)) {
    const pixels = Number.parseFloat(value);
    if (!Number.isFinite(pixels) || pixels < 16 || pixels > 10_000) {
      return { kind: "error", message: "Fixed size must be between 16 and 10,000 px." };
    }
    return { kind: "ok", value: `[${Math.round(pixels)}px]` };
  }
  if (/^(?:[A-Za-z0-9_.%/]+|\[[A-Za-z0-9_.%(),+*/-]+\])$/.test(value)) {
    return { kind: "ok", value };
  }
  return {
    kind: "error",
    message: `Enter Default, ${ownPrefix}full, ${ownPrefix}auto, or a pixel value.`
  };
}

function dimensionLabel(axis: "width" | "height", value: string | null): string {
  if (!value) return "";
  return `${axis === "width" ? "w" : "h"}-${value}`;
}

function SizeCard({
  node,
  nodeInfo,
  busy,
  applyDimension
}: {
  node: WebNode;
  nodeInfo: WebNodeInfo | null;
  busy: boolean;
  applyDimension: (axis: "width" | "height", value: string | null) => void;
}): React.ReactElement {
  const authoredWidth = elementDimensionValue(node.classes, "width");
  const authoredHeight = elementDimensionValue(node.classes, "height");
  const [widthDraft, setWidthDraft] = useState(dimensionLabel("width", authoredWidth));
  const [heightDraft, setHeightDraft] = useState(dimensionLabel("height", authoredHeight));
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    setWidthDraft(dimensionLabel("width", authoredWidth));
    setHeightDraft(dimensionLabel("height", authoredHeight));
    setError(null);
  }, [authoredWidth, authoredHeight]);

  const commit = (axis: "width" | "height", draft: string) => {
    const result = parseDimensionDraft(axis, draft);
    if (result.kind === "error") {
      setError(result.message);
      return;
    }
    setError(null);
    const current = axis === "width" ? authoredWidth : authoredHeight;
    if (current !== result.value) {
      applyDimension(axis, result.value);
    }
  };

  return (
    <Card title="Size">
      <label className="field web-insp-field">
        <span className="field-label">Width</span>
        <input
          type="text"
          value={widthDraft}
          disabled={busy}
          spellCheck={false}
          onChange={(event) => setWidthDraft(event.target.value)}
          onBlur={() => commit("width", widthDraft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
          placeholder={`Default · ${nodeInfo?.computedStyle.width || "computed width"}`}
        />
        <span className="web-insp-value-state">
          {authoredWidth
            ? `Authored · w-${authoredWidth}`
            : `Derived · ${nodeInfo?.computedStyle.width || "browser default"}`}
        </span>
      </label>
      <label className="field web-insp-field">
        <span className="field-label">Height</span>
        <input
          type="text"
          value={heightDraft}
          disabled={busy}
          spellCheck={false}
          onChange={(event) => setHeightDraft(event.target.value)}
          onBlur={() => commit("height", heightDraft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
          placeholder={`Default · ${nodeInfo?.computedStyle.height || "computed height"}`}
        />
        <span className="web-insp-value-state">
          {authoredHeight
            ? `Authored · h-${authoredHeight}`
            : `Derived · ${nodeInfo?.computedStyle.height || "browser default"}`}
        </span>
      </label>
      <p className="web-insp-hint">
        Drag the canvas handles for fixed pixels, or enter Tailwind values such
        as w-full, w-fit, h-auto, or 320px.
      </p>
      {error ? (
        <span className="web-insp-error" role="alert">
          {error}
        </span>
      ) : null}
    </Card>
  );
}

function SpacingCard({
  node,
  busy,
  applyClasses
}: {
  node: WebNode;
  busy: boolean;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
}): React.ReactElement {
  return (
    <Card title="Spacing">
      <FacetSelect
        label="Margin X"
        value={marginXFacet.parse(node.classes)}
        options={SPACING_STEPS}
        disabled={busy}
        onChange={(next) => applyClasses(marginXFacet, next, "margin_x")}
      />
      <FacetSelect
        label="Margin Y"
        value={marginYFacet.parse(node.classes)}
        options={SPACING_STEPS}
        disabled={busy}
        onChange={(next) => applyClasses(marginYFacet, next, "margin_y")}
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

// ── per-kind cards ───────────────────────────────────────────────────────────

function TextCard({
  node,
  busy,
  editing,
  richTextFormats,
  formatRichText,
  applyClasses,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  editing: boolean;
  richTextFormats: RichTextFormatState | null;
  formatRichText: (nodeId: string, format: RichTextFormat) => void;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const variant = node.variant ?? "body";
  const content = node.content ?? "";
  const hasStructuredContent = richTextDocumentHasStructure(content);
  const disabledVariants = hasStructuredContent
    ? TEXT_VARIANTS.filter(
        (candidate) => !textVariantAllowsStructuredRichText(candidate)
      )
    : [];
  const size = textSizeFacet.parse(node.classes);
  const align = textAlignFacet.parse(node.classes);
  const weight = fontWeightFacet.parse(node.classes);
  const lineHeight = lineHeightFacet.parse(node.classes);
  const italic = italicFacet.parse(node.classes) === "italic";
  const underline = underlineFacet.parse(node.classes) === "underline";
  const lineThrough = lineThroughFacet.parse(node.classes) === "line-through";
  const wholeNodeFormats: RichTextFormatState = {
    bold: weight === "bold" ? "on" : "off",
    italic: italic ? "on" : "off",
    underline: underline ? "on" : "off",
    strikethrough: lineThrough ? "on" : "off"
  };
  const formats = editing && richTextFormats ? richTextFormats : wholeNodeFormats;
  const applyFormat = (format: RichTextFormat, current: RichTextFormatValue) => {
    if (editing) {
      formatRichText(node.id, format);
      return;
    }
    if (format === "bold") {
      applyClasses(fontWeightFacet, current === "on" ? null : "bold", "font_weight");
    } else if (format === "italic") {
      applyClasses(italicFacet, current === "on" ? null : "italic", "font_style");
    } else if (format === "underline") {
      applyClasses(
        underlineFacet,
        current === "on" ? null : "underline",
        "text_decoration"
      );
    } else {
      applyClasses(
        lineThroughFacet,
        current === "on" ? null : "line-through",
        "text_decoration"
      );
    }
  };
  const formatButtonProps = (format: RichTextFormat) => {
    const current = formats[format];
    return {
      className: `web-format-btn${current === "on" ? " is-selected" : ""}${
        current === "mixed" ? " is-mixed" : ""
      }`,
      "aria-pressed": richTextAriaPressed(current),
      disabled: busy || (editing && richTextFormats === null),
      onMouseDown: (event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault(),
      onClick: () => applyFormat(format, current)
    };
  };

  return (
    <Card title="Text">
      <PropSelect
        label="Style"
        value={variant}
        options={TEXT_VARIANTS}
        disabledOptions={disabledVariants}
        disabled={busy}
        onChange={(next) => applyProps({ kind: "text", variant: next, content }, "text_variant")}
      />
      {hasStructuredContent ? (
        <p className="web-insp-hint">
          Convert this text to one paragraph before choosing a heading style.
        </p>
      ) : null}

      <FacetSelect
        label="Size"
        value={size}
        options={TEXT_SIZE_RAMP}
        disabled={busy}
        onChange={(next) => applyClasses(textSizeFacet, next, "text_size")}
      />
      <FacetSelect
        label="Weight"
        value={weight}
        options={FONT_WEIGHT_VALUES}
        disabled={busy}
        onChange={(next) => applyClasses(fontWeightFacet, next, "font_weight")}
      />
      <FacetSelect
        label="Line spacing"
        value={lineHeight}
        options={LINE_HEIGHT_VALUES}
        disabled={busy}
        onChange={(next) => applyClasses(lineHeightFacet, next, "line_height")}
      />

      <div className="field web-insp-field">
        <span className="field-label">Formatting</span>
        <div className="web-align-row" role="group" aria-label="Text formatting">
          {RICH_TEXT_MARK_CONTROLS.map((control) => (
            <button
              key={control.format}
              type="button"
              aria-label={control.label}
              title={`${control.label} (${control.shortcut})`}
              {...formatButtonProps(control.format)}
            >
              <span
                className={`web-rich-glyph is-${control.format}`}
                aria-hidden="true"
              >
                {control.glyph}
              </span>
            </button>
          ))}
        </div>
        <p className="web-insp-hint">
          {editing
            ? "Formatting applies to the current text selection and saves when you finish editing."
            : "Double-click this text on the canvas to format only a selected range."}
        </p>
      </div>

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

function containerProps(
  node: WebNode,
  href: string | null,
  newTab: boolean,
  background: WebBackgroundImage | null
): WebNodeProps {
  return {
    kind: "container",
    href,
    new_tab: href ? newTab : false,
    background
  };
}

function branchPropsWithBackground(
  node: WebNode,
  background: WebBackgroundImage | null
): WebNodeProps {
  if (node.kind === "section") {
    return {
      kind: "section",
      tag: node.tag ?? "section",
      anchor_id: node.anchor_id ?? null,
      background
    };
  }
  return containerProps(node, node.href?.trim() || null, node.new_tab ?? false, background);
}

function ContainerLinkCard({
  node,
  busy,
  applyProps
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const [href, setHref] = useState(node.href ?? "");
  const newTab = node.new_tab ?? false;
  React.useEffect(() => {
    setHref(node.href ?? "");
  }, [node.id, node.href]);
  const commit = (nextHref: string, nextNewTab: boolean, intent: string) => {
    applyProps(
      containerProps(node, nextHref.trim() || null, nextNewTab, node.background ?? null),
      intent
    );
  };
  return (
    <Card title="Click action">
      <label className="field web-insp-field">
        <span className="field-label">Link URL</span>
        <input
          type="text"
          value={href}
          disabled={busy}
          onChange={(event) => setHref(event.target.value)}
          onBlur={() => {
            if (href.trim() !== (node.href ?? "")) {
              commit(href, newTab, "container_href");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="https://… or /path"
        />
      </label>
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={newTab}
          disabled={busy || href.trim() === ""}
          onChange={(event) => commit(href, event.target.checked, "container_new_tab")}
        />
        Open in a new tab
      </label>
      <p className="web-insp-hint">
        Clicking still selects this container here. The link is active on the published/exported
        page.
      </p>
    </Card>
  );
}

function BackgroundImageCard({
  node,
  busy,
  applyProps,
  onChooseBackground
}: {
  node: WebNode;
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
  onChooseBackground: (nodeId: string) => void;
}): React.ReactElement {
  const background = node.background ?? null;
  const [scrimOpacity, setScrimOpacity] = useState(background?.scrim?.opacity ?? 50);
  React.useEffect(() => {
    setScrimOpacity(background?.scrim?.opacity ?? 50);
  }, [node.id, background?.scrim?.opacity]);
  const commit = (next: WebBackgroundImage | null, intent: string) => {
    applyProps(branchPropsWithBackground(node, next), intent);
  };
  const commitScrimOpacity = (opacity: number) => {
    if (background?.scrim && opacity !== background.scrim.opacity) {
      commit(
        {
          ...background,
          scrim: {
            ...background.scrim,
            opacity
          }
        },
        "background_scrim_opacity"
      );
    }
  };
  return (
    <Card title="Background image">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={busy}
        onClick={() => onChooseBackground(node.id)}
      >
        {background ? "Replace background image" : "Add background image"}
      </button>
      {background ? (
        <>
          <p className="web-insp-hint">Asset: {background.asset_id}</p>
          <PropSelect
            label="Fit"
            value={background.fit}
            options={["cover", "contain"]}
            disabled={busy}
            onChange={(fit) =>
              commit(
                { ...background, fit: fit as WebBackgroundImage["fit"] },
                "background_fit"
              )
            }
          />
          <PropSelect
            label="Position"
            value={background.position}
            options={["center", "top", "right", "bottom", "left"]}
            disabled={busy}
            onChange={(position) =>
              commit(
                {
                  ...background,
                  position: position as WebBackgroundImage["position"]
                },
                "background_position"
              )
            }
          />
          <label className="web-insp-checkbox">
            <input
              type="checkbox"
              checked={background.scrim != null}
              disabled={busy}
              onChange={(event) =>
                commit(
                  {
                    ...background,
                    scrim: event.target.checked ? { color: "dark", opacity: 50 } : null
                  },
                  "background_scrim"
                )
              }
            />
            Add readable-text scrim
          </label>
          {background.scrim ? (
            <>
              <PropSelect
                label="Scrim color"
                value={background.scrim.color}
                options={["dark", "light", "primary", "accent", "black", "white"]}
                disabled={busy}
                onChange={(color) =>
                  commit(
                    {
                      ...background,
                      scrim: {
                        ...background.scrim!,
                        color: color as NonNullable<WebBackgroundImage["scrim"]>["color"]
                      }
                    },
                    "background_scrim_color"
                  )
                }
              />
              <label className="field web-insp-field">
                <span className="field-label">Scrim opacity ({scrimOpacity}%)</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={scrimOpacity}
                  disabled={busy}
                  onChange={(event) => setScrimOpacity(Number(event.target.value))}
                  onPointerUp={(event) =>
                    commitScrimOpacity(Number(event.currentTarget.value))
                  }
                  onKeyUp={(event) =>
                    commitScrimOpacity(Number(event.currentTarget.value))
                  }
                  onBlur={(event) => commitScrimOpacity(Number(event.currentTarget.value))}
                />
              </label>
            </>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy}
            onClick={() => commit(null, "remove_background")}
          >
            Remove background
          </button>
        </>
      ) : (
        <p className="web-insp-hint">
          Choose a library or uploaded image, then control its crop and optional text scrim.
        </p>
      )}
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
  const display = displayFacet.parse(node.classes);
  const direction = directionFacet.parse(node.classes);
  const horizontalFacet = direction === "col" ? alignItemsFacet : justifyContentFacet;
  const verticalFacet = direction === "col" ? justifyContentFacet : alignItemsFacet;
  return (
    <Card title="Layout">
      <FacetSelect
        label="Display"
        value={display}
        options={["flex", "grid", "block", "inline-flex", "hidden"]}
        disabled={busy}
        onChange={(next) => applyClasses(displayFacet, next, "display")}
      />
      {display === "flex" || display === "inline-flex" ? (
        <>
          <FacetSelect
            label="Direction"
            value={direction}
            options={["row", "col"]}
            disabled={busy}
            onChange={(next) => applyClasses(directionFacet, next, "direction")}
          />
          <FacetSelect
            label="Horizontal"
            value={horizontalFacet.parse(node.classes)}
            options={direction === "col" ? ALIGN_ITEMS_VALUES : JUSTIFY_CONTENT_VALUES}
            disabled={busy}
            onChange={(next) => applyClasses(horizontalFacet, next, "horizontal_alignment")}
          />
          <FacetSelect
            label="Vertical"
            value={verticalFacet.parse(node.classes)}
            options={direction === "col" ? JUSTIFY_CONTENT_VALUES : ALIGN_ITEMS_VALUES}
            disabled={busy}
            onChange={(next) => applyClasses(verticalFacet, next, "vertical_alignment")}
          />
          <FacetSelect
            label="Wrap"
            value={flexWrapFacet.parse(node.classes)}
            options={FLEX_WRAP_VALUES}
            disabled={busy}
            onChange={(next) => applyClasses(flexWrapFacet, next, "flex_wrap")}
          />
        </>
      ) : null}
      {display === "grid" ? (
        <FacetSelect
          label="Columns"
          value={gridColumnsFacet.parse(node.classes)}
          options={GRID_COLUMN_VALUES}
          disabled={busy}
          onChange={(next) => applyClasses(gridColumnsFacet, next, "grid_columns")}
        />
      ) : null}
      {display === "flex" || display === "inline-flex" || display === "grid" ? (
        <FacetSelect
          label="Gap"
          value={gapFacet.parse(node.classes)}
          options={SPACING_STEPS}
          disabled={busy}
          onChange={(next) => applyClasses(gapFacet, next, "gap")}
        />
      ) : null}
    </Card>
  );
}

function ImageCard({
  node,
  busy,
  applyClasses,
  applyProps,
  onReplaceImage
}: {
  node: WebNode;
  busy: boolean;
  applyClasses: (facet: ClassFacet, value: string | null, intent: string) => void;
  applyProps: (props: WebNodeProps, intent: string) => void;
  onReplaceImage: (nodeId: string) => void;
}): React.ReactElement {
  const [alt, setAlt] = useState(node.alt ?? "");
  const [href, setHref] = useState(node.href ?? "");
  const newTab = node.new_tab ?? false;
  const commit = (
    over: Partial<{ alt: string; href: string; newTab: boolean }>,
    intent: string
  ) => {
    applyProps(
      {
        kind: "image",
        asset_id: node.asset_id ?? "",
        alt: over.alt ?? alt,
        href: (over.href ?? href).trim() || null,
        new_tab: over.newTab ?? newTab
      },
      intent
    );
  };
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
              commit({ alt }, "image_alt");
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
      <label className="field web-insp-field">
        <span className="field-label">Link</span>
        <input
          type="text"
          value={href}
          disabled={busy}
          onChange={(event) => setHref(event.target.value)}
          onBlur={() => {
            if (href !== (node.href ?? "")) {
              commit({ href }, "image_href");
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="Add a link URL"
        />
      </label>
      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={newTab}
          disabled={busy || href.trim() === ""}
          onChange={(event) => commit({ newTab: event.target.checked }, "image_new_tab")}
        />
        Open in a new tab
      </label>
      <FacetSelect
        label="Fit"
        value={objectFitFacet.parse(node.classes)}
        options={OBJECT_FIT_VALUES}
        disabled={busy}
        onChange={(next) => applyClasses(objectFitFacet, next, "image_fit")}
      />
      <FacetSelect
        label="Position"
        value={objectPositionFacet.parse(node.classes)}
        options={OBJECT_POSITION_VALUES}
        disabled={busy}
        onChange={(next) => applyClasses(objectPositionFacet, next, "image_position")}
      />
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

/** The personalization row (P5): bind this node to an account value at
 * generation via a slot key. The key text drives a `set_slot_key` op through
 * the SAME ops path every other inspector edit uses. On Section/Container nodes
 * a "show only when bound" toggle wraps the key in the `when:` presence prefix
 * (kept-when-bound / removed-when-absent at derive). The current content is the
 * fallback the derived page shows when the account has no value for the key. */
function PersonalizationCard({
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
  const initial = slotKeyParts(node.slot_key);
  // The `when:` gate is only legal on Section/Container carriers.
  const supportsWhen = node.kind === "section" || node.kind === "container";
  const [key, setKey] = useState(initial.key);
  const [whenBound, setWhenBound] = useState(initial.whenBound && supportsWhen);

  const trimmed = key.trim();
  const invalid = trimmed.length > 0 && !isValidSlotKey(trimmed);

  // Emit a set_slot_key op for the given key + gate, unless the key is invalid
  // (wait for a fix — the inline error explains) or the value is unchanged.
  const commit = (nextKey: string, nextWhen: boolean) => {
    const nextTrimmed = nextKey.trim();
    if (nextTrimmed.length > 0 && !isValidSlotKey(nextTrimmed)) {
      return;
    }
    const stored = composeSlotKey(nextTrimmed, nextWhen && supportsWhen);
    if ((node.slot_key ?? null) === stored) {
      return;
    }
    applyOps([setSlotKeyOp(pageId, node.id, stored)], "set_slot_key");
  };

  return (
    <Card title="Personalization">
      <label className="field web-insp-field">
        <span className="field-label">Slot key</span>
        <input
          type="text"
          value={key}
          disabled={busy}
          spellCheck={false}
          onChange={(event) => setKey(event.target.value)}
          onBlur={() => commit(key, whenBound)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          placeholder="account.name"
        />
      </label>
      {invalid ? (
        <span className="web-insp-error" role="alert">
          Use a–z, 0–9, and . _ - (max 64 characters).
        </span>
      ) : null}
      {supportsWhen ? (
        <label className="web-insp-checkbox">
          <input
            type="checkbox"
            checked={whenBound}
            disabled={busy || trimmed.length === 0}
            onChange={(event) => {
              setWhenBound(event.target.checked);
              commit(key, event.target.checked);
            }}
          />
          Show only when bound
        </label>
      ) : null}
      <p className="web-insp-hint">
        Binds this element to an account value when generating pages. The current
        content is the fallback shown when an account has no value.
      </p>
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
  React.useEffect(() => {
    setDraft(node.classes);
  }, [node.classes]);
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
