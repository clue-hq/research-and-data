"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Copy, FileText, Plus, Trash2 } from "lucide-react";
import type { Diagnostic, PageId, Scene, Unit } from "@/engine/contracts";
import { listPages } from "@/engine/sceneQueries";
import { createWorkspaceModel } from "@/engine/workspaceLayout";

interface PageRailProps {
  scene: Scene;
  activePageId: PageId | null;
  diagnostics?: Diagnostic[];
  /** Print workstream W3: when on, the print presets (A4 / US Letter) appear
   * and pages created from them seed a bleed + safe-area default. */
  printFeatureEnabled?: boolean;
  onSelectPage: (pageId: PageId) => void;
  onAddCustomPage: (input: CustomPageInput) => void;
  onDuplicatePage: (pageId: PageId) => void;
  onRemovePage: (pageId: PageId) => void;
}

export interface CustomPageInput {
  name: string;
  width: number;
  height: number;
  unit: Unit;
  /** Marks a page created from a print preset — the host applies bleed/safe
   * defaults (only while the print feature is on). */
  print?: boolean;
}

type QuickSize = Pick<CustomPageInput, "name" | "width" | "height" | "unit"> & { print?: boolean };

const quickSizes: QuickSize[] = [
  {
    name: "Square Ad",
    width: 1080,
    height: 1080,
    unit: "px"
  },
  {
    name: "LinkedIn Wide",
    width: 1200,
    height: 628,
    unit: "px"
  },
  {
    name: "Portrait Social",
    width: 1080,
    height: 1350,
    unit: "px"
  },
  {
    name: "Email Header",
    width: 600,
    height: 800,
    unit: "px"
  }
];

/** Print-only presets — physical page sizes that carry commercial-print
 * bleed/safe defaults when created. Shown only when the print feature is on. */
const printQuickSizes: QuickSize[] = [
  {
    name: "A4 print",
    width: 210,
    height: 297,
    unit: "mm",
    print: true
  },
  {
    name: "US Letter print",
    width: 8.5,
    height: 11,
    unit: "in",
    print: true
  }
];

export function PageRail({
  scene,
  activePageId,
  diagnostics = [],
  printFeatureEnabled = false,
  onSelectPage,
  onAddCustomPage,
  onDuplicatePage,
  onRemovePage
}: PageRailProps) {
  const [name, setName] = useState("Custom Artboard");
  const [width, setWidth] = useState(1080);
  const [height, setHeight] = useState(1080);
  const [unit, setUnit] = useState<Unit>("px");
  // Tracks whether the current draft came from a print preset (so its bleed/
  // safe defaults apply on Add). Any manual field edit clears it — the draft
  // is no longer a pristine print preset.
  const [pendingPrint, setPendingPrint] = useState(false);
  const availableQuickSizes = printFeatureEnabled ? [...quickSizes, ...printQuickSizes] : quickSizes;
  // Collapsible add-artboard form: null = untouched → open only when the
  // document has no pages yet.
  const [creatorToggled, setCreatorToggled] = useState<boolean | null>(null);
  const pages = listPages(scene);
  const creatorOpen = creatorToggled ?? pages.length === 0;
  const workspaceModel = useMemo(
    () => createWorkspaceModel(scene, activePageId, diagnostics),
    [activePageId, diagnostics, scene]
  );
  const canAdd = Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;

  const addPage = () => {
    if (!canAdd) {
      return;
    }
    onAddCustomPage({
      name: name.trim() || `${width} x ${height} ${unit}`,
      width,
      height,
      unit,
      print: pendingPrint
    });
  };

  return (
    <nav className="page-rail" aria-label="Artboards">
      <div className="page-rail-head">
        <div className="panel-title">
          <FileText aria-hidden size={16} />
          Pages
        </div>
      </div>
      {pages.length > 0 ? (
        <ul className="page-list">
          {pages.map((page) => {
            const artboard = workspaceModel.artboards.find((item) => item.pageId === page.id);
            return (
              <li key={page.id} className="page-row">
                <button
                  type="button"
                  className={page.id === activePageId ? "page-button active" : "page-button"}
                  title={`${page.name} · ${pageSizeLabel(page)}`}
                  onClick={() => onSelectPage(page.id)}
                >
                  <span className="page-row-title">
                    <span className="page-row-name">{page.name}</span>
                    {artboard ? <DiagnosticDot summary={artboard.diagnosticsSummary} /> : null}
                  </span>
                  <small className="visually-hidden">{pageSizeLabel(page)}</small>
                </button>
                <button
                  type="button"
                  className="icon-button page-duplicate-button"
                  aria-label={`Duplicate artboard ${page.name}`}
                  title={`Duplicate artboard ${page.name}`}
                  onClick={() => onDuplicatePage(page.id)}
                >
                  <Copy aria-hidden size={13} />
                </button>
                <button
                  type="button"
                  className="icon-button page-remove-button"
                  aria-label={`Remove artboard ${page.name}`}
                  title={`Remove artboard ${page.name}`}
                  onClick={() => onRemovePage(page.id)}
                >
                  <Trash2 aria-hidden size={13} />
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="muted page-list-empty">No artboards yet.</p>
      )}
      <section className="custom-page-creator-section" aria-label="Add artboard">
        <button
          type="button"
          className="custom-page-creator-toggle"
          aria-expanded={creatorOpen}
          onClick={() => setCreatorToggled(!creatorOpen)}
        >
          <ChevronRight aria-hidden size={14} className="custom-page-creator-chevron" />
          Add artboard
        </button>
        {creatorOpen ? (
          <div className="custom-page-creator">
            <label>
              Name
              <input
                aria-label="Custom artboard name"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setPendingPrint(false);
                }}
              />
            </label>
            <div className="compact-grid">
              <div className="compact-field">
                <span>W</span>
                <input
                  aria-label="Custom artboard width"
                  type="number"
                  min={1}
                  step={unit === "px" || unit === "pt" ? 1 : 0.1}
                  value={width}
                  onChange={(event) => {
                    setWidth(Number(event.target.value));
                    setPendingPrint(false);
                  }}
                />
              </div>
              <div className="compact-field">
                <span>H</span>
                <input
                  aria-label="Custom artboard height"
                  type="number"
                  min={1}
                  step={unit === "px" || unit === "pt" ? 1 : 0.1}
                  value={height}
                  onChange={(event) => {
                    setHeight(Number(event.target.value));
                    setPendingPrint(false);
                  }}
                />
              </div>
              <div className="compact-field">
                <span>Unit</span>
                <select
                  aria-label="Custom artboard unit"
                  value={unit}
                  onChange={(event) => {
                    setUnit(event.target.value as Unit);
                    setPendingPrint(false);
                  }}
                >
                  <option value="pt">pt</option>
                  <option value="px">px</option>
                  <option value="mm">mm</option>
                  <option value="in">in</option>
                </select>
              </div>
            </div>
            <div className="quick-size-list" aria-label="Common custom sizes">
              {availableQuickSizes.map((size) => (
                <button
                  key={`${size.name}-${size.width}-${size.height}-${size.unit}`}
                  type="button"
                  title={size.name}
                  onClick={() => {
                    setName(size.name);
                    setWidth(size.width);
                    setHeight(size.height);
                    setUnit(size.unit);
                    setPendingPrint(size.print ?? false);
                  }}
                >
                  {size.print ? size.name : `${size.width}x${size.height}`}
                </button>
              ))}
            </div>
            <button type="button" className="secondary-action" onClick={addPage} disabled={!canAdd}>
              <Plus aria-hidden size={15} />
              Add artboard
            </button>
          </div>
        ) : null}
      </section>
    </nav>
  );
}

function DiagnosticDot({
  summary
}: {
  summary: { errorCount: number; warningCount: number };
}) {
  const status =
    summary.errorCount > 0 ? "error" : summary.warningCount > 0 ? "warning" : "ready";
  const label =
    summary.errorCount > 0
      ? `${summary.errorCount} error${summary.errorCount === 1 ? "" : "s"}`
      : summary.warningCount > 0
        ? `${summary.warningCount} warning${summary.warningCount === 1 ? "" : "s"}`
        : "Ready";
  return <span className={`artboard-status-dot ${status}`} aria-label={label} title={label} />;
}

function pageSizeLabel(page: Scene["pages"][PageId]): string {
  const size = page.size.source ?? page.size;
  return `${formatDimension(size.width)} x ${formatDimension(size.height)} ${size.unit}`;
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, "");
}
