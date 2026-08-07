"use client";

import type {
  BrandTokenCatalog,
  Diagnostic,
  DiagnosticSubject,
  Operation,
  Page,
  Rect,
  Scene,
  Unit
} from "@/engine/contracts";
import {
  updateDocumentArtifactType,
  updateDocumentTitle,
  updatePageBackground,
  updatePageBleed,
  updatePageName,
  updatePageSafeArea,
  updatePageSize
} from "@/engine/operations";
import { normalizePageSize } from "@/engine/pageGeometry";
import { SlotOverview } from "../SlotInspector";
import { InspectorDiagnosticsSection } from "./diagnostics";
import {
  NumberField,
  TokenSelect,
  normalizePositiveDimension,
  roundForEditor,
  tokenFill,
  tokenFromFill
} from "./fields";
import { SelectedArtboardSummary } from "./summaries";

/** The no-selection inspector: document metadata plus the active page's
 * surface, print guides, and brand style. */
export function DocumentPageSection({
  scene,
  activePage,
  brandTokens,
  pageDiagnostics,
  onOperation,
  onSelectSubject,
  layoutManagedEditing,
  onSetLayoutManagedEditing
}: {
  scene: Scene;
  activePage: Page | null;
  brandTokens?: BrandTokenCatalog | null;
  pageDiagnostics: Diagnostic[];
  onOperation: (operation: Operation) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
  /** Advanced per-document opt-out from handoff-absolute: this section only
   * binds the checkbox; the freeze-seam policy lives with the setting. */
  layoutManagedEditing?: boolean;
  onSetLayoutManagedEditing?: (enabled: boolean) => void;
}) {
  return (
      <section className="inspector-section">
        <div className="section-heading">Document</div>
        <label className="field">
          <span>Document Title</span>
          <input value={scene.meta.title} onChange={(event) => onOperation(updateDocumentTitle(event.target.value))} />
        </label>
        <label className="field">
          <span>Artifact Type</span>
          <input
            value={scene.meta.artifact_type ?? ""}
            placeholder="ad, report, email, mailer"
            onChange={(event) => onOperation(updateDocumentArtifactType(event.target.value))}
          />
        </label>
        {onSetLayoutManagedEditing ? (
          <>
            <label className="toggle-field">
              <input
                type="checkbox"
                checked={layoutManagedEditing ?? false}
                onChange={(event) => onSetLayoutManagedEditing(event.target.checked)}
              />
              Layout-managed editing
            </label>
            <p className="muted">
              Advanced: keep agent auto-layout live after Accept; managed elements re-flow and use Detach.
            </p>
          </>
        ) : null}
        {activePage ? (
          <>
            <div className="section-heading">Page</div>
            <SelectedArtboardSummary activePage={activePage} diagnostics={pageDiagnostics} />
            <label className="field">
              <span>Name</span>
              <input value={activePage.name} onChange={(event) => onOperation(updatePageName(activePage, event.target.value))} />
            </label>
            <div className="field-grid two">
              <label className="field">
                <span>Preset</span>
                <input value={activePage.size.preset ?? "custom"} readOnly />
              </label>
              <label className="field">
                <span>Orientation</span>
                <input value={orientationLabel(activePage.size.width, activePage.size.height)} readOnly />
              </label>
            </div>
            <div className="field-grid two">
              <NumberField
                label="W"
                value={activePage.size.width}
                min={1}
                onCommit={(value) => onOperation(updatePageSize(activePage, customPageSize(activePage, { width: value })))}
              />
              <NumberField
                label="H"
                value={activePage.size.height}
                min={1}
                onCommit={(value) => onOperation(updatePageSize(activePage, customPageSize(activePage, { height: value })))}
              />
              <label className="field">
                <span>Unit</span>
                <select
                  value={activePage.size.unit}
                  onChange={(event) =>
                    onOperation(updatePageSize(activePage, customPageSize(activePage, { unit: event.target.value as Unit })))
                  }
                >
                  <option value="pt">pt</option>
                  <option value="px">px</option>
                  <option value="mm">mm</option>
                  <option value="in">in</option>
                </select>
              </label>
            </div>
            <div className="section-heading nested-heading">Print guides</div>
            <div className="field-grid two">
              <NumberField
                label="Safe Margin"
                value={safeAreaMargin(activePage)}
                min={0}
                onCommit={(value) => onOperation(updatePageSafeArea(activePage, safeAreaFromMargin(activePage, value)))}
              />
              <NumberField
                label="Bleed"
                value={bleedMargin(activePage)}
                min={0}
                onCommit={(value) => onOperation(updatePageBleed(activePage, bleedFromMargin(activePage, value)))}
              />
            </div>
            {brandTokens ? (
              <>
                <div className="section-heading nested-heading">Brand style</div>
                <div className="field-grid two">
                  <TokenSelect
                    label="Page Fill Token"
                    value={tokenFromFill(activePage.background[0])}
                    tokens={brandTokens.surface_tokens}
                    onChange={(token) => onOperation(updatePageBackground(activePage, token ? [tokenFill(activePage.id, "background", token)] : []))}
                  />
                </div>
              </>
            ) : null}
            <InspectorDiagnosticsSection
              title="Page Issues"
              diagnostics={pageDiagnostics}
              onSelectSubject={onSelectSubject}
            />
            <SlotOverview scene={scene} activePageId={activePage.id} />
            <p className="muted contract-note">
              Page/artboard dimensions are canonical scene data. Presets are shortcuts only; custom sizes export exactly as authored.
              Safe area and bleed are canonical page guides for print/export readiness.
            </p>
          </>
        ) : (
          <p className="muted">Select a page or node on the canvas.</p>
        )}
      </section>
  );
}

function customPageSize(page: Page, patch: Partial<Pick<Page["size"], "width" | "height" | "unit">>): Page["size"] {
  const source = page.size.source;
  const width = normalizePositiveDimension(patch.width ?? source?.width ?? page.size.width);
  const height = normalizePositiveDimension(patch.height ?? source?.height ?? page.size.height);
  return normalizePageSize({
    width,
    height,
    unit: patch.unit ?? "pt",
    preset: "custom"
  });
}

function safeAreaFromMargin(page: Page, rawMargin: number): Rect | null {
  const margin = normalizeGuideMargin(rawMargin, page);
  if (margin === 0) {
    return null;
  }
  return {
    x: margin,
    y: margin,
    width: Math.max(1, page.size.width - margin * 2),
    height: Math.max(1, page.size.height - margin * 2)
  };
}

function bleedFromMargin(page: Page, rawMargin: number): Rect | null {
  const margin = normalizeGuideMargin(rawMargin, page);
  if (margin === 0) {
    return null;
  }
  return {
    x: -margin,
    y: -margin,
    width: page.size.width + margin * 2,
    height: page.size.height + margin * 2
  };
}

function safeAreaMargin(page: Page): number {
  if (!page.safe_area) {
    return 0;
  }
  return roundForEditor(
    Math.max(
      0,
      Math.min(
        page.safe_area.x,
        page.safe_area.y,
        page.size.width - page.safe_area.x - page.safe_area.width,
        page.size.height - page.safe_area.y - page.safe_area.height
      )
    )
  );
}

function bleedMargin(page: Page): number {
  if (!page.bleed) {
    return 0;
  }
  return roundForEditor(Math.max(0, Math.min(-page.bleed.x, -page.bleed.y)));
}

function normalizeGuideMargin(value: number, page: Page): number {
  if (!Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return roundForEditor(Math.min(value, Math.max(0, Math.min(page.size.width, page.size.height) / 2 - 1)));
}


function orientationForDimensions(width: number, height: number): Page["size"]["orientation"] {
  return width >= height ? "landscape" : "portrait";
}

function orientationLabel(width: number, height: number): string {
  return orientationForDimensions(width, height);
}
