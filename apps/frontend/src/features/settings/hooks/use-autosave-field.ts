"use client";
import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
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
  options: { multiline?: boolean; onComplete?: (fromKeyboard: boolean) => void; onCancel?: () => void } = {},
) {
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const saved = useRef(initial);
  const busy = useRef(false);
  const cancelled = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const notify = useConfirmation();
  async function commit(fromKeyboard = false) {
    if (busy.current || cancelled.current) return;
    busy.current = true;
    setSaving(true);
    try {
      const result = await saveFieldValue(value, saved.current, save);
      if (!mounted.current) return;
      saved.current = result.value;
      setValue(result.value);
      if (result.changed) notify(message);
    } catch (error) {
      if (!mounted.current) return;
      setValue(saved.current);
      notify(
        error instanceof Error
          ? error.message
          : "Your change could not be saved.",
        true,
      );
    } finally {
      busy.current = false;
      if (mounted.current) {
        setSaving(false);
        options.onComplete?.(fromKeyboard);
      }
    }
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || busy.current) return;
    if (event.key === "Enter" && (!options.multiline || event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void commit(true);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancelled.current = true;
      setValue(saved.current);
      options.onCancel?.();
    }
  }
  return {
    value,
    readOnly: saving,
    "aria-busy": saving,
    onFocus: () => { cancelled.current = false; },
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      cancelled.current = false;
      setValue(event.target.value);
    },
    onBlur: () => void commit(),
    onKeyDown,
  };
}
