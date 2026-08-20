"use client";

import { ChevronDownIcon, DownloadIcon } from "lucide-react";
import {
  type useImageExportController,
} from "../hooks/use-image-export-controller";
import {
  IMAGE_EXPORT_FORMATS,
  IMAGE_EXPORT_SCALES,
  imageExportSupportsScale,
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

export function ImageExportMenu({ controller }: { controller: ImageExportControllerState }) {
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
            <div data-artifact-export-preview="ad" />
            <span>{controller.format} preview</span>
          </div>
        ) : null}
      </div>
      <button className={styles.imageExportDownloadButton} onClick={controller.requestExport} type="button">
        <span>Export {controller.format}</span>
        <DownloadIcon aria-hidden="true" className={styles.imageExportDownloadIcon} size={13} strokeWidth={1.5} />
      </button>
      <span aria-live="polite" className={styles.srOnly}>{controller.statusMessage}</span>
    </div>
  );
}
