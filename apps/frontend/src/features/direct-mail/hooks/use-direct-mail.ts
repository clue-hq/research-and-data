"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDirectMailRepository } from "../data/direct-mail-provider";
import { registerHandwriting } from "../data/direct-mail.uploads";
import type { DirectMailState } from "../model/direct-mail";

export function useDirectMailEnabled() { return useDirectMailRepository().enabled; }

export function useDirectMail() {
  const { enabled, repository } = useDirectMailRepository();
  const [data, setData] = useState<DirectMailState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const serial = useRef(0);
  const reload = useCallback(async () => {
    const token = ++serial.current;
    try { const next = await repository.read(); await registerHandwriting(next.styles); if (token === serial.current) { setData(next); setError(null); } }
    catch (error) { if (token === serial.current) setError(error instanceof Error ? error.message : "Direct Mail could not be loaded."); }
  }, [repository]);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const token = ++serial.current;
    repository.read().then(async (next) => {
      await registerHandwriting(next.styles);
      if (active && token === serial.current) { setData(next); setError(null); }
    }).catch((error) => { if (active && token === serial.current) setError(error instanceof Error ? error.message : "Direct Mail could not be loaded."); });
    const stop = repository.subscribe(() => void reload());
    return () => { active = false; stop(); };
  }, [enabled, repository, reload]);
  const run = useCallback(async <T,>(operation: () => Promise<T>): Promise<T | null> => {
    setPending(true); setError(null);
    try { const value = await operation(); await reload(); return value; }
    catch (error) { setError(error instanceof Error ? error.message : "Changes could not be saved. Try again."); return null; }
    finally { setPending(false); }
  }, [reload]);
  return { data, error, pending, enabled, repository, reload, run, clearError: () => setError(null) };
}
export type DirectMailController = ReturnType<typeof useDirectMail>;
