"use client";

import { ChevronDownIcon, DownloadIcon } from "lucide-react";
import { useEffect } from "react";
import {
  type useImageExportController,
} from "../hooks/use-image-export-controller";
import {
  IMAGE_EXPORT_FORMATS,
  IMAGE_EXPORT_SCALES,
  imageExportSupportsScale,
  type ImageExportFormat,
  type ImageExportPreview,
  type ImageExportScale,
} from "../model/image-export";
import styles from "./chat-shell.module.css";

type ImageExportController = ReturnType<typeof useImageExportController>;
type ImageExportControllerState = ImageExportController["controller"];

function ExportChoice<Value extends string>({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: Value) => void;
  options: readonly Value[];
  value: Value;
}) {
  return (
    <div className={styles.imageExportField}>
      <span>{label}</span>
      <div className={styles.imageExportChoiceGrid}>
        {options.map((option) => (
          <button
            aria-pressed={value === option}
            className={value === option ? styles.imageExportChoiceActive : ""}
            key={option}
            onClick={() => onChange(option)}
            type="button"
          >
            <span>{option}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function ImageExportMenu({
  controller,
  exportPreview,
  exportStatus,
  onRequestExportPreview,
}: {
  controller: ImageExportControllerState;
  /** AD4.D step 3 (§1.11): the ad session's render of the CURRENT settings and
   * the element that hosts it. Both decisions are made upstream — the session
   * hands this a value only while it is true of the live document, the live
   * scene and the selected `(format, scale)`, and only when one of the two
   * elements can actually show it — so there is no staleness and no format
   * sniffing for this component to do. `null`/absent leaves the designed empty
   * region exactly as it renders today, which IS the pending, failed and
   * fixture state (ruling R-D14). */
  exportPreview?: ImageExportPreview | null;
  /** AD4.D step 2: what the ad session's export listener says the request
   * actually DID — in flight, downloaded, or refused in the engine's own
   * words. It outranks the controller's optimistic "…export requested" line,
   * which is true only until the listener answers. Absent (the fixture path,
   * a web artifact) leaves the controller's line exactly as it renders today. */
  exportStatus?: string | null;
  /** AD4.D step 3: ask the ad session to render these settings. Absent on the
   * fixture path and for web artifacts, which keeps the effect below inert. */
  onRequestExportPreview?: (format: ImageExportFormat, scale: ImageExportScale) => void;
}) {
  // §1.11: opening the region — and every settings change while it is open —
  // asks for the render those settings produce. The session answers from its
  // per-scene cache when it already has one, so reopening or flipping back to a
  // format already looked at costs no export.
  const { format, previewOpen, scale } = controller;
  useEffect(() => {
    if (!previewOpen) return;
    onRequestExportPreview?.(format, scale);
  }, [format, onRequestExportPreview, previewOpen, scale]);

  return (
    <div aria-label="Export image output" className={styles.imageExportMenu} role="dialog">
      <div className={styles.imageExportHeading}>
        <strong>Export image</strong>
      </div>
      <ExportChoice label="Format" onChange={controller.setFormat} options={IMAGE_EXPORT_FORMATS} value={controller.format} />
      {imageExportSupportsScale(controller.format) ? (
        <ExportChoice label="Scale" onChange={controller.setScale} options={IMAGE_EXPORT_SCALES} value={controller.scale} />
      ) : null}
      {/* Gate G-E: the dummy's "Transparent background" toggle row is held —
          no engine support verified (2026-08-20). Restore verbatim if the
          founder authorizes the §8 engine change. */}
      <div className={styles.imageExportPreviewSection}>
        <button
          aria-expanded={controller.previewOpen}
          className={styles.imageExportPreviewTrigger}
          onClick={() => controller.setPreviewOpen(!controller.previewOpen)}
          type="button"
        >
          <span>Preview</span>
          <ChevronDownIcon aria-hidden="true" className={controller.previewOpen ? styles.imageExportPreviewChevronOpen : ""} size={13} strokeWidth={1.5} />
        </button>
        {controller.previewOpen ? (
          <div
            aria-label={`${controller.format} export preview`}
            className={styles.imageExportPreview}
            data-export-format={controller.format.toLowerCase()}
          >
            {/* §1.11: the designed hook hosts the real render. Two elements,
                mirroring the standalone editor's own branch
                (`ExportPreviewSurface.tsx:64-77`): a PDF is shown by the
                browser's PDF viewer in a frame, everything else is an image.
                Which one is a prop, never a test on the payload here. */}
            <div data-artifact-export-preview="ad">
              {exportPreview?.mode === "img" ? (
                // An EMPTY alt: the region is already labelled "<format> export
                // preview" above, so an alt would announce the same thing twice.
                // A data URL already in memory is not a served asset either —
                // nothing for `next/image` to fetch, hence the house suppression
                // every other raw `<img>` in this app carries.
                // eslint-disable-next-line @next/next/no-img-element
                <img alt="" src={exportPreview.dataUrl} />
              ) : null}
              {exportPreview?.mode === "iframe" ? (
                // A frame is its own document, so unlike the img it needs its
                // own accessible name — the parent's label does not carry into
                // it. Upstream titles it the same way.
                <iframe src={exportPreview.dataUrl} title="Export preview" />
              ) : null}
            </div>
            <span>{controller.format} preview</span>
          </div>
        ) : null}
      </div>
      <button className={styles.imageExportDownloadButton} onClick={controller.requestExport} type="button">
        <span>Export {controller.format}</span>
        <DownloadIcon aria-hidden="true" className={styles.imageExportDownloadIcon} size={13} strokeWidth={1.5} />
      </button>
      <span aria-live="polite" className={styles.srOnly}>{exportStatus ?? controller.statusMessage}</span>
    </div>
  );
}
