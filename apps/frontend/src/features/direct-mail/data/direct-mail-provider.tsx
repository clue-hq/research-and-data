"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import { createBrowserDirectMailStore } from "./direct-mail.storage";
import { loadPilotMailers } from "./direct-mail.pilot";
import { withMaterialsMail } from "@/features/account-materials/data/materials.fixture";
import { StateSchema } from "../model/direct-mail";
import { createV2MailFixture } from "@/features/orchestration/data/mail.fixture";

const Context = createContext({ enabled: false, repository: unavailableDirectMailRepository });
export function DirectMailProvider({ enabled, children, v2 = false }: { enabled: boolean; children: ReactNode; v2?: boolean }) {
  const value = useMemo(() => ({ enabled, repository: enabled ? createDirectMailRepository(v2 ? createBrowserDirectMailStore(createV2MailFixture, "clue-direct-mail-preview-v2", (value) => withMaterialsMail(StateSchema.parse(value))) : createBrowserDirectMailStore(), v2 ? undefined : loadPilotMailers) : unavailableDirectMailRepository }), [enabled, v2]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useDirectMailRepository() { return useContext(Context); }
