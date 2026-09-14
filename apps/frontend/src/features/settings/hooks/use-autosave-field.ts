"use client";
import { useRef, useState, type KeyboardEvent } from "react";
import { useConfirmation } from "@/components/ui/confirmation-card";

export async function saveFieldValue(
  value: string,
  saved: string,
  save: (value: string) => Promise<string>,
) {
  const trimmed = value.trim();
  if (trimmed === saved.trim())
    return { value: saved, changed: false } as const;
  return { value: await save(trimmed), changed: true } as const;
}
export function useAutosaveField(
  initial: string,
  save: (value: string) => Promise<string>,
  message: string,
) {
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const saved = useRef(initial);
  const busy = useRef(false);
  const notify = useConfirmation();
  async function commit() {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    try {
      const result = await saveFieldValue(value, saved.current, save);
      saved.current = result.value;
      setValue(result.value);
      if (result.changed) notify(message);
    } catch (error) {
      setValue(saved.current);
      notify(
        error instanceof Error
          ? error.message
          : "Your change could not be saved.",
        true,
      );
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      void commit();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setValue(saved.current);
    }
  }
  return {
    value,
    readOnly: saving,
    "aria-busy": saving,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
      setValue(event.target.value),
    onBlur: () => void commit(),
    onKeyDown,
  };
}
