"use client";

import { useEffect, useRef, useState } from "react";

import {
  type AssetDescription,
  type DescriptionPatch,
  saveDescription
} from "@/engine/brandLibrary";
import { AssetPreviewImage } from "./AssetPreviewImage";
import {
  type LibraryItem,
  assetDimensions,
  formatBytes
} from "./libraryModel";

type EditField = "title" | "description" | "usage";

const FIELD_LABELS: Record<EditField, string> = {
  title: "Title",
  description: "Description",
  usage: "Usage"
};

function fieldValue(description: AssetDescription | undefined, field: EditField): string {
  if (!description) {
    return "";
  }
  return (description[field] ?? "") as string;
}

/**
 * Ploy's asset-detail anatomy in the Cursor skin: large preview on the left,
 * a 320px meta panel on the right whose Title / Description / Usage rows each
 * toggle into an editable textarea that PUTs through `saveDescription` (which
 * flips the row's origin to human).
 */
export function AssetLightbox({
  apiBaseUrl,
  item,
  onClose,
  onDescriptionSaved
}: {
  apiBaseUrl: string;
  item: LibraryItem;
  onClose: () => void;
  onDescriptionSaved: (assetId: string, description: AssetDescription) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [description, setDescription] = useState<AssetDescription | undefined>(
    item.description
  );
  const [editing, setEditing] = useState<EditField | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDescription(item.description);
    setEditing(null);
    setError(null);
  }, [item.record.id, item.description]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const record = item.record;
  const dimensions = assetDimensions(record);
  const bytes = formatBytes(item.byteLength);
  const isHumanEdited = (description?.origin ?? item.description?.origin) === "human";

  function startEdit(field: EditField) {
    setDraft(fieldValue(description, field));
    setEditing(field);
    setError(null);
  }

  async function save(field: EditField) {
    setSaving(true);
    setError(null);
    const patch: DescriptionPatch = { [field]: draft } as DescriptionPatch;
    try {
      const saved = await saveDescription({ apiBaseUrl }, record.id, patch);
      setDescription(saved);
      onDescriptionSaved(record.id, saved);
      setEditing(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  function renderEditableRow(field: EditField) {
    const value = fieldValue(description, field);
    const isEditing = editing === field;
    return (
      <div className="lib-detail-row" key={field}>
        <div className="lib-detail-row-head">
          <span className="eyebrow">{FIELD_LABELS[field]}</span>
          {!isEditing ? (
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() => startEdit(field)}
            >
              Edit
            </button>
          ) : null}
        </div>
        {isEditing ? (
          <div className="lib-detail-edit">
            <textarea
              aria-label={`${FIELD_LABELS[field]} value`}
              value={draft}
              rows={field === "title" ? 1 : 3}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="lib-detail-edit-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={saving}
                onClick={() => save(field)}
              >
                Save
              </button>
              <button
                type="button"
                className="btn btn-quiet btn-sm"
                disabled={saving}
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <p className="lib-detail-value">
            {value ? value : <span className="caption">Not set</span>}
          </p>
        )}
      </div>
    );
  }

  return (
    <div
      className="lightbox-overlay"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="lightbox-panel"
        role="dialog"
        aria-modal="true"
        aria-label={item.title}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="lib-lightbox-preview">
          <AssetPreviewImage
            assetId={record.id}
            alt={item.title}
            full
          />
        </div>
        <div className="lib-lightbox-meta">
          <div className="lib-lightbox-meta-head">
            <span className="title">{item.title}</span>
            {isHumanEdited ? <span className="caption">edited</span> : null}
            <button
              type="button"
              className="btn btn-quiet btn-sm lib-lightbox-close"
              aria-label="Close"
              onClick={onClose}
            >
              Close
            </button>
          </div>

          {renderEditableRow("title")}
          {renderEditableRow("description")}
          {renderEditableRow("usage")}

          {error ? <span className="status-pill is-error">{error}</span> : null}

          <dl className="lib-detail-facts">
            <dt className="eyebrow">Filename</dt>
            <dd className="mono">{record.media?.filename ?? record.id}</dd>
            <dt className="eyebrow">Type</dt>
            <dd>{record.kind}</dd>
            {dimensions ? (
              <>
                <dt className="eyebrow">Dimensions</dt>
                <dd className="mono">{dimensions}</dd>
              </>
            ) : null}
            {bytes ? (
              <>
                <dt className="eyebrow">Size</dt>
                <dd className="mono">{bytes}</dd>
              </>
            ) : null}
            {item.createdAt ? (
              <>
                <dt className="eyebrow">Created</dt>
                <dd className="mono">{item.createdAt}</dd>
              </>
            ) : null}
          </dl>

          {item.tags.length > 0 ? (
            <div className="lib-detail-tags">
              {item.tags.map((tag) => (
                <span className="chip" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
