"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkspaceRepository } from "../data/workspace-provider";
import type { WorkspaceState } from "../model/workspace";
export function useWorkspace() {
  const repository = useWorkspaceRepository();
  const [data, setData] = useState<WorkspaceState | null>(null), [error, setError] = useState<string | null>(null), [pending, setPending] = useState(false);
  const serial = useRef(0);
  const reload = useCallback(async () => { if (!repository) return; const token = ++serial.current; try { const next = await repository.read(); if (serial.current === token) { setData(next); setError(null); } } catch (error) { if (serial.current === token) setError(error instanceof Error ? error.message : "The account plan could not be loaded."); } }, [repository]);
  useEffect(() => {
    if (!repository) return;
    let active = true;
    const token = ++serial.current;
    repository.read().then((next) => {
      if (active && token === serial.current) { setData(next); setError(null); }
    }).catch((error) => {
      if (active && token === serial.current) setError(error instanceof Error ? error.message : "The account plan could not be loaded.");
    });
    const stop = repository.subscribe(() => void reload());
    return () => { active = false; stop(); };
  }, [repository, reload]);
  const run = async (operation: () => Promise<WorkspaceState>) => { setPending(true); setError(null); try { await operation(); await reload(); return true; } catch (error) { setError(error instanceof Error ? error.message : "Changes could not be saved."); return false; } finally { setPending(false); } };
  return { data, error, pending, repository, run, reload };
}
export type WorkspaceController = ReturnType<typeof useWorkspace>;
