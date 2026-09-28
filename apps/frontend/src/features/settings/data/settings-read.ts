import "server-only";
import { accountRecoveryFor } from "@/features/accounts/data/accounts-read-result";
import { getSettingsProfile } from "./profile.repository";
import { getSettingsWorkspace } from "./workspace.repository";
import { getSettingsMembers } from "./members.repository";
import { getSettingsResearchFields } from "./research-fields.repository";
import { getPagesSettings } from "./pages.repository";
import type { ResearchEntity } from "../model/research-fields";

export async function readSettingsSection(section: string, entity?: ResearchEntity) {
  try {
    switch (section) {
      case "profile":
        return { section, data: await getSettingsProfile() } as const;
      case "workspace":
        return { section, data: await getSettingsWorkspace() } as const;
      case "members":
        return { section, data: await getSettingsMembers() } as const;
      case "pages":
        return { section: "pages", data: await getPagesSettings() } as const;
      case "data-model":
        return entity
          ? { section: "research-fields", data: await getSettingsResearchFields(entity) } as const
          : { section: "research-overview" } as const;
      default:
        return { section: "static" } as const;
    }
  } catch (error) {
    const recovery = accountRecoveryFor(error);
    if (!recovery) throw error;
    return { section: "recovery", recovery } as const;
  }
}
