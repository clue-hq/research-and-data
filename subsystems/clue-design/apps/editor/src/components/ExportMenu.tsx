"use client";

import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import type { ExportProfile } from "@/engine/contracts";

/**
 * The topbar Export popover (moda's export card, Cursor skin): pick a file
 * type, page scope, and a per-format quality option, then Download. Purely
 * presentational — choices compose an ExportProfile and go out through
 * `onDownload`; whether/how the export runs is the shell's decision.
 */

type ExportFormat = "png" | "svg" | "pdf";
export type ExportMenuScope = "active" | "all";

const FORMAT_COPY: Record<ExportFormat, { label: string; description: string }> = {
  png: { label: "PNG", description: "Sharp raster — best for social, decks, and web." },
  svg: { label: "SVG", description: "Vector — crisp at any size, editable elsewhere." },
  pdf: { label: "PDF", description: "Document pages with embedded fonts." }
};

export function ExportMenu({
  pageCount,
  activePageName,
  isExporting,
  onDownload,
  onClose
}: {
  pageCount: number;
  activePageName: string | null;
  isExporting: boolean;
  onDownload: (profile: ExportProfile, scope: ExportMenuScope) => void;
  onClose: () => void;
}) {
  const [format, setFormat] = useState<ExportFormat>("png");
  const [scope, setScope] = useState<ExportMenuScope>(pageCount > 1 ? "all" : "active");
  const [pngScale, setPngScale] = useState<1 | 2>(2);
  const [pdfIntent, setPdfIntent] = useState<"preview" | "print">("preview");
  const [pdfColor, setPdfColor] = useState<"srgb" | "cmyk">("srgb");
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    rootRef.current?.querySelector("select")?.focus();
  }, []);

  const download = () => {
    onDownload(profileForChoices(format, pngScale, pdfIntent, pdfColor), scope);
  };

  return (
    <div
      ref={rootRef}
      className="export-menu"
      role="dialog"
      aria-label="Export options"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <label className="export-menu-field">
        <span>File type</span>
        <select
          value={format}
          onChange={(event) => setFormat(event.target.value as ExportFormat)}
        >
          {(Object.keys(FORMAT_COPY) as ExportFormat[]).map((value) => (
            <option key={value} value={value}>
              {FORMAT_COPY[value].label}
            </option>
          ))}
        </select>
      </label>
      <p className="export-menu-hint">{FORMAT_COPY[format].description}</p>

      <label className="export-menu-field">
        <span>Pages</span>
        <select
          value={scope}
          onChange={(event) => setScope(event.target.value as ExportMenuScope)}
        >
          <option value="all">All pages ({pageCount})</option>
          <option value="active">
            {activePageName ? `Current — ${activePageName}` : "Current page"}
          </option>
        </select>
      </label>

      {format === "png" ? (
        <label className="export-menu-field">
          <span>Size</span>
          <select
            value={pngScale}
            onChange={(event) => setPngScale(Number(event.target.value) === 2 ? 2 : 1)}
          >
            <option value={1}>1× (96 DPI)</option>
            <option value={2}>2× (192 DPI)</option>
          </select>
        </label>
      ) : null}

      {format === "pdf" ? (
        <label className="export-menu-field">
          <span>Intent</span>
          <select
            value={pdfIntent}
            onChange={(event) => {
              const nextIntent = event.target.value === "print" ? "print" : "preview";
              setPdfIntent(nextIntent);
              // CMYK is a print-only server concern (export.cmyk_requires_print_intent);
              // flipping back to preview must drop it so we never emit an invalid combo.
              if (nextIntent !== "print") {
                setPdfColor("srgb");
              }
            }}
          >
            <option value="preview">Digital (preview)</option>
            <option value="print">Print (bleed, embedded fonts)</option>
          </select>
        </label>
      ) : null}

      {format === "pdf" && pdfIntent === "print" ? (
        <label className="export-menu-field">
          <span>Color</span>
          <select
            value={pdfColor}
            onChange={(event) => setPdfColor(event.target.value === "cmyk" ? "cmyk" : "srgb")}
          >
            <option value="srgb">sRGB (digital press)</option>
            <option value="cmyk">CMYK (offset press)</option>
          </select>
        </label>
      ) : null}

      <button
        type="button"
        className="btn-primary export-menu-download"
        disabled={isExporting || pageCount === 0}
        onClick={download}
      >
        <Download aria-hidden size={15} />
        {isExporting ? "Exporting…" : "Download"}
      </button>
      {pageCount === 0 ? (
        <p className="export-menu-hint">Add an artboard before exporting.</p>
      ) : null}
    </div>
  );
}

function profileForChoices(
  format: ExportFormat,
  pngScale: 1 | 2,
  pdfIntent: "preview" | "print",
  pdfColor: "srgb" | "cmyk"
): ExportProfile {
  switch (format) {
    case "png":
      return {
        name: `topbar_png_${pngScale}x`,
        format: "png",
        pdf_intent: null,
        raster: { scale: pngScale, dpi: 96 * pngScale },
        include_bleed: false,
        include_marks: false,
        embed_fonts: false
      };
    case "svg":
      return {
        name: "topbar_svg",
        format: "svg",
        pdf_intent: null,
        raster: null,
        include_bleed: false,
        include_marks: false,
        embed_fonts: false
      };
    case "pdf":
      return {
        name: `topbar_pdf_${pdfIntent}`,
        format: "pdf",
        pdf_intent: pdfIntent,
        raster: null,
        include_bleed: pdfIntent === "print",
        include_marks: pdfIntent === "print",
        // CMYK is print-intent-only; emit the field solely on print PDFs, and
        // only when the user chose it — sRGB is the default and emits nothing.
        ...(pdfIntent === "print" && pdfColor === "cmyk" ? { color: "cmyk" } : {}),
        embed_fonts: true
      };
  }
}
