"use client";

import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import type { ExportProfile, Page, PageId } from "@/engine/contracts";
import { bleedlessPrintPages } from "@/engine/printReadiness";
import { RASTER_SCALE_PRESETS } from "./ExportPanel";

/**
 * The topbar Export popover (moda's export card, Cursor skin): pick a file
 * type, page scope, and a per-format quality option, then Download. Purely
 * presentational — choices compose an ExportProfile and go out through
 * `onDownload`; whether/how the export runs is the shell's decision. The
 * print-bleed predicate (which artboards would lose crop marks) lives in
 * engine/printReadiness, not inline here.
 */

type ExportFormat = "png" | "svg" | "pdf";
export type ExportMenuScope = "active" | "all";

const FORMAT_COPY: Record<ExportFormat, { label: string; description: string }> = {
  png: { label: "PNG", description: "Sharp raster — best for social, decks, and web." },
  svg: { label: "SVG", description: "Vector — crisp at any size, editable elsewhere." },
  pdf: { label: "PDF", description: "Document pages with embedded fonts." }
};

export function ExportMenu({
  pages,
  activePageId,
  isExporting,
  onDownload,
  onClose
}: {
  pages: readonly Page[];
  activePageId: PageId | null;
  isExporting: boolean;
  onDownload: (profile: ExportProfile, scope: ExportMenuScope) => void;
  onClose: () => void;
}) {
  const pageCount = pages.length;
  const activePage = pages.find((page) => page.id === activePageId) ?? null;
  const activePageName = activePage?.name ?? null;

  const [format, setFormat] = useState<ExportFormat>("png");
  const [scope, setScope] = useState<ExportMenuScope>(pageCount > 1 ? "all" : "active");
  const [pngScale, setPngScale] = useState<number>(2);
  const [pdfIntent, setPdfIntent] = useState<"preview" | "print">("preview");
  const [pdfColor, setPdfColor] = useState<"srgb" | "cmyk">("srgb");
  // Print bleed + crop marks: on for print PDFs (preserves the prior hardcoded
  // behavior) until the user opts out. Only surfaced for print-intent PDFs.
  const [includePrintMarks, setIncludePrintMarks] = useState(true);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    rootRef.current?.querySelector("select")?.focus();
  }, []);

  const isPrintPdf = format === "pdf" && pdfIntent === "print";
  const scopedPages = scope === "all" ? [...pages] : activePage ? [activePage] : [];
  const bleedlessPages = bleedlessPrintPages({ format, pdfIntent, pages: scopedPages });

  const download = () => {
    onDownload(profileForChoices(format, pngScale, pdfIntent, pdfColor, includePrintMarks), scope);
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
            onChange={(event) => {
              const next = Number(event.target.value);
              setPngScale(RASTER_SCALE_PRESETS.includes(next) ? next : 2);
            }}
          >
            {RASTER_SCALE_PRESETS.map((scale) => (
              <option key={scale} value={scale}>
                {scale}× ({Math.round(96 * scale)} DPI)
              </option>
            ))}
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

      {isPrintPdf ? (
        <label className="toggle-field" data-role="include-bleed-marks">
          <input
            type="checkbox"
            checked={includePrintMarks}
            onChange={(event) => setIncludePrintMarks(event.target.checked)}
          />
          Include bleed + crop marks
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

      {isPrintPdf && includePrintMarks && bleedlessPages.length > 0 ? (
        <p className="export-menu-hint" data-role="export-menu-bleed-note" role="note">
          {bleedlessPages.length === scopedPages.length
            ? scopedPages.length === 1
              ? "This artboard has no bleed area — bleed and crop marks will be skipped."
              : "These artboards have no bleed area — bleed and crop marks will be skipped."
            : `${bleedlessPages.length} of ${scopedPages.length} artboards have no bleed area — bleed and crop marks will be skipped for them.`}{" "}
          Enable “Print &amp; bleed” in the canvas toolbar to add print defaults first.
        </p>
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
  pngScale: number,
  pdfIntent: "preview" | "print",
  pdfColor: "srgb" | "cmyk",
  includePrintMarks: boolean
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
        // Fonts embed as @font-face subsets so the downloaded SVG renders
        // identically on machines without the design's fonts installed.
        embed_fonts: true
      };
    case "pdf": {
      // Bleed + crop marks are a coupled print-PDF pair (same coupling as the
      // export panel's checkbox): only print intent exposes them, and only when
      // the user leaves them enabled. Any other combination emits neither.
      const wantsPrintMarks = pdfIntent === "print" && includePrintMarks;
      return {
        name: `topbar_pdf_${pdfIntent}`,
        format: "pdf",
        pdf_intent: pdfIntent,
        raster: null,
        include_bleed: wantsPrintMarks,
        include_marks: wantsPrintMarks,
        // CMYK is print-intent-only; emit the field solely on print PDFs, and
        // only when the user chose it — sRGB is the default and emits nothing.
        ...(pdfIntent === "print" && pdfColor === "cmyk" ? { color: "cmyk" } : {}),
        embed_fonts: true
      };
    }
  }
}
