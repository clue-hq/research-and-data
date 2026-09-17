"use client";

import { useState } from "react";
import styles from "./settings.module.css";

/**
 * A settings field that commits on blur (settings spec §6.4). A rejected save
 * restores the last saved value so the screen never shows an unsaved edit as if
 * it had landed; the confirmation card reports why.
 */
export function SettingsAutosaveInput({
  ariaLabel,
  value,
  onSave,
  readOnly = false,
  multiline = false,
  placeholder,
}: {
  ariaLabel: string;
  value: string;
  onSave: (next: string | null) => Promise<void>;
  readOnly?: boolean;
  multiline?: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(value);
  const [saving, setSaving] = useState(false);
  const commit = async () => {
    const next = draft.trim();
    if (next === saved.trim()) return;
    setSaving(true);
    try {
      await onSave(next === "" ? null : next);
      setSaved(next);
    } catch {
      setDraft(saved);
    } finally {
      setSaving(false);
    }
  };
  const common = {
    "aria-label": ariaLabel,
    value: draft,
    readOnly: readOnly || saving,
    placeholder,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setDraft(event.target.value),
    onBlur: () => void commit(),
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Escape") setDraft(saved);
      if (event.key === "Enter" && !multiline) void commit();
    },
  };
  return multiline ? (
    <textarea className={styles.textarea} rows={3} {...common} />
  ) : (
    <input className={styles.input} {...common} />
  );
}
