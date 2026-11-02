"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import { createBrowserDirectMailStore } from "./direct-mail.storage";
import { loadPilotMailers } from "./direct-mail.pilot";
import { StateSchema } from "../model/direct-mail";

import { createIllumioDemo, illumioSimulation } from "./illumio-demo";

const Context = createContext({ enabled: false, repository: unavailableDirectMailRepository });
export function DirectMailProvider({ enabled, children, v2 = false }: { enabled: boolean; children: ReactNode; v2?: boolean }) {
  const value = useMemo(() => ({ enabled, repository: enabled
    ? createDirectMailRepository(v2 ? createBrowserDirectMailStore(createIllumioDemo, "clue-direct-mail-illumio-demo", (value) => StateSchema.parse(value)) : createBrowserDirectMailStore(), v2 ? undefined : loadPilotMailers, v2, illumioSimulation)
    : unavailableDirectMailRepository }), [enabled, v2]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useDirectMailRepository() { return useContext(Context); }
