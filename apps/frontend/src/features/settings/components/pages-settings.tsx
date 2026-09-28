// Built from spec §8.2 pending the co-founder's frames (2026-09-18); re-lift when they land.
"use client";

import { Upload } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

import { usePagesSettings } from "../hooks/use-pages-settings";
import type { PagesSettingsRead } from "../model/pages";
import { CustomDomainCard } from "./custom-domain-card";
import styles from "./settings.module.css";
import { SettingsCard, SettingsInput } from "./settings-primitives";

function FormRow({
  children,
  description,
  label,
}: {
  children: ReactNode;
  description?: string;
  label: string;
}) {
  return (
    <div className={styles.formRow}>
      <div className={styles.formLabel}>
        <p>{label}</p>
        {description ? <span>{description}</span> : null}
      </div>
      <div className={styles.formControl}>{children}</div>
    </div>
  );
}

/** Spec §8.2 / A1: the system hostname is read-only; only its label is editable. */
function ClueAddressRow({
  busy,
  canManage,
  hostname,
  label,
  onSave,
}: {
  busy: boolean;
  canManage: boolean;
  hostname: string;
  label: string;
  onSave: (label: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(label);
  return (
    <FormRow description="Changing it makes existing links stop working" label="Your Clue address">
      {editing ? (
        <div className="flex items-center gap-2">
          <input
            aria-label="Clue address label"
            className={styles.input}
            onChange={(event) => setDraft(event.target.value)}
            value={draft}
          />
          <Button
            disabled={busy}
            onClick={() => {
              void onSave(draft.trim()).then((saved) => {
                if (saved) setEditing(false);
              });
            }}
            size="sm"
            variant="secondary"
          >
            Save
          </Button>
          <Button
            onClick={() => {
              setDraft(label);
              setEditing(false);
            }}
            size="sm"
            variant="ghost"
          >
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span>{hostname}</span>
          {canManage ? (
            <Button
              onClick={() => {
                setDraft(label);
                setEditing(true);
              }}
              size="sm"
              variant="ghost"
            >
              Edit
            </Button>
          ) : null}
        </div>
      )}
    </FormRow>
  );
}

export function PagesSettings({
  canManage,
  initial,
}: {
  canManage: boolean;
  initial: PagesSettingsRead;
}) {
  const pages = usePagesSettings(initial);
  const { settings, systemHostname, customHostname } = pages.state;
  const faviconInput = useRef<HTMLInputElement>(null);
  const previewInput = useRef<HTMLInputElement>(null);

  return (
    <div className={styles.pagesStack}>
      <SettingsCard className={styles.formCard}>
        <ClueAddressRow
          busy={pages.busy}
          canManage={canManage}
          hostname={systemHostname.hostname}
          label={systemHostname.label}
          onSave={pages.changeLabel}
        />
        <FormRow description="Broken or audited links send visitors here" label="Fallback URL">
          <SettingsInput
            ariaLabel="Fallback URL"
            {...pages.fallbackUrl}
            readOnly={!canManage || pages.fallbackUrl.readOnly}
          />
        </FormRow>
        <FormRow description="128 × 128px recommended" label="Favicon">
          <div className="flex items-center gap-3">
            {settings.faviconUrl ? (
              // A workspace-uploaded favicon is served from the page origin, which is
              // not a configured `next/image` host, so it stays a plain `<img>`.
              // eslint-disable-next-line @next/next/no-img-element
              <img alt="Current favicon" className="size-8" src={settings.faviconUrl} />
            ) : null}
            <button
              aria-label="Upload favicon"
              className={styles.uploadSquare}
              disabled={!canManage || pages.busy}
              onClick={() => faviconInput.current?.click()}
              type="button"
            >
              <Upload size={15} strokeWidth={1.25} />
            </button>
            <input
              accept="image/png,image/x-icon,image/svg+xml"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void pages.upload("favicon", file);
              }}
              ref={faviconInput}
              type="file"
            />
          </div>
        </FormRow>
        <FormRow description="Used when a page is shared" label="Social preview">
          <div className="flex flex-col gap-3">
            {settings.socialPreviewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                alt="Current social preview"
                className="w-full"
                src={settings.socialPreviewUrl}
              />
            ) : null}
            <button
              className={styles.uploadPreview}
              disabled={!canManage || pages.busy}
              onClick={() => previewInput.current?.click()}
              type="button"
            >
              <Upload size={16} strokeWidth={1.25} />
              <span>Upload image</span>
            </button>
            <input
              accept="image/png,image/jpeg"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void pages.upload("social-preview", file);
              }}
              ref={previewInput}
              type="file"
            />
          </div>
        </FormRow>
        <FormRow label="Page title">
          <SettingsInput
            ariaLabel="Page title"
            {...pages.pageTitle}
            readOnly={!canManage || pages.pageTitle.readOnly}
          />
        </FormRow>
        <FormRow label="Page description">
          <textarea
            aria-label="Page description"
            className={styles.textarea}
            rows={3}
            {...pages.pageDescription}
            readOnly={!canManage || pages.pageDescription.readOnly}
          />
        </FormRow>
      </SettingsCard>

      <CustomDomainCard
        busy={pages.busy}
        canManage={canManage}
        custom={customHostname}
        onCheck={() => void pages.check()}
        onConnect={(hostname) => void pages.connect(hostname)}
        onRemove={() => void pages.remove()}
        refusal={pages.refusal}
      />
    </div>
  );
}
