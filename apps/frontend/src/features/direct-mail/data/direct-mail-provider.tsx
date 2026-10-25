"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import { createBrowserDirectMailStore } from "./direct-mail.storage";
import { loadPilotMailers } from "./direct-mail.pilot";

const Context = createContext({ enabled: false, repository: unavailableDirectMailRepository });
export function DirectMailProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const value = useMemo(() => ({ enabled, repository: enabled ? createDirectMailRepository(createBrowserDirectMailStore(), loadPilotMailers) : unavailableDirectMailRepository }), [enabled]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useDirectMailRepository() { return useContext(Context); }
