"use client";

import { useState } from "react";
import { Copy, FileText, Plus, Trash2 } from "lucide-react";
import type { PageId, Scene, Unit } from "@/engine/contracts";
import { listPages } from "@/engine/sceneQueries";

interface PageRailProps {
  scene: Scene;
  activePageId: PageId | null;
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
}

const quickSizes: Array<Pick<CustomPageInput, "name" | "width" | "height" | "unit">> = [
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

export function PageRail({ scene, activePageId, onSelectPage, onAddCustomPage, onDuplicatePage, onRemovePage }: PageRailProps) {
  const [name, setName] = useState("Custom Page");
  const [width, setWidth] = useState(1080);
  const [height, setHeight] = useState(1080);
  const [unit, setUnit] = useState<Unit>("px");
  const pages = listPages(scene);
  const canAdd = Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;

  const addPage = () => {
    if (!canAdd) {
      return;
    }
    onAddCustomPage({
      name: name.trim() || `${width} x ${height} ${unit}`,
      width,
      height,
      unit
    });
  };

  return (
    <nav className="page-rail" aria-label="Pages">
      <div className="panel-title">
        <FileText aria-hidden size={16} />
        Pages
      </div>
      {pages.map((page) => (
        <div key={page.id} className="page-row">
          <button
            type="button"
            className={page.id === activePageId ? "page-button active" : "page-button"}
            onClick={() => onSelectPage(page.id)}
          >
            <span>{page.name}</span>
            <small>
              {page.size.width} x {page.size.height} {page.size.unit}
            </small>
          </button>
          <button
            type="button"
            className="icon-button page-duplicate-button"
            aria-label={`Duplicate page ${page.name}`}
            title={`Duplicate page ${page.name}`}
            onClick={() => onDuplicatePage(page.id)}
          >
            <Copy aria-hidden size={13} />
          </button>
          <button
            type="button"
            className="icon-button page-remove-button"
            aria-label={`Remove page ${page.name}`}
            title={`Remove page ${page.name}`}
            onClick={() => onRemovePage(page.id)}
          >
            <Trash2 aria-hidden size={13} />
          </button>
        </div>
      ))}
      <div className="custom-page-creator" aria-label="Create custom page">
        <div className="section-heading">
          <Plus aria-hidden size={15} />
          New custom size
        </div>
        <label>
          Name
          <input aria-label="Custom page name" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="compact-grid">
          <div className="compact-field">
            <span>W</span>
            <input
              aria-label="Custom page width"
              type="number"
              min={1}
              step={unit === "px" ? 1 : 0.1}
              value={width}
              onChange={(event) => setWidth(Number(event.target.value))}
            />
          </div>
          <div className="compact-field">
            <span>H</span>
            <input
              aria-label="Custom page height"
              type="number"
              min={1}
              step={unit === "px" ? 1 : 0.1}
              value={height}
              onChange={(event) => setHeight(Number(event.target.value))}
            />
          </div>
          <div className="compact-field">
            <span>Unit</span>
            <select aria-label="Custom page unit" value={unit} onChange={(event) => setUnit(event.target.value as Unit)}>
              <option value="px">px</option>
              <option value="mm">mm</option>
              <option value="in">in</option>
            </select>
          </div>
        </div>
        <div className="quick-size-list" aria-label="Common custom sizes">
          {quickSizes.map((size) => (
            <button
              key={`${size.name}-${size.width}-${size.height}-${size.unit}`}
              type="button"
              onClick={() => {
                setName(size.name);
                setWidth(size.width);
                setHeight(size.height);
                setUnit(size.unit);
              }}
            >
              {size.width}x{size.height}
            </button>
          ))}
        </div>
        <button type="button" className="secondary-action" onClick={addPage} disabled={!canAdd}>
          <Plus aria-hidden size={15} />
          Add page
        </button>
      </div>
    </nav>
  );
}
