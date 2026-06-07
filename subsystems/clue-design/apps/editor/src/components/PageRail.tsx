"use client";

import { FileText } from "lucide-react";
import type { PageId, Scene } from "@/engine/contracts";
import { listPages } from "@/engine/sceneQueries";

interface PageRailProps {
  scene: Scene;
  activePageId: PageId | null;
  onSelectPage: (pageId: PageId) => void;
}

export function PageRail({ scene, activePageId, onSelectPage }: PageRailProps) {
  return (
    <nav className="page-rail" aria-label="Pages">
      <div className="panel-title">
        <FileText aria-hidden size={16} />
        Pages
      </div>
      {listPages(scene).map((page) => (
        <button
          key={page.id}
          type="button"
          className={page.id === activePageId ? "page-button active" : "page-button"}
          onClick={() => onSelectPage(page.id)}
        >
          <span>{page.name}</span>
          <small>
            {page.size.width} x {page.size.height} {page.size.unit}
          </small>
        </button>
      ))}
    </nav>
  );
}
