import "server-only";
import { accountRecoveryFor } from "@/features/accounts/data/accounts-read-result";
import { getSettingsProfile } from "./profile.repository";
import { getSettingsWorkspace } from "./workspace.repository";
import { getSettingsMembers } from "./members.repository";

export async function readSettingsSection(section: string) {
  try {
    switch (section) {
      case "profile":
        return { section, data: await getSettingsProfile() } as const;
      case "workspace":
        return { section, data: await getSettingsWorkspace() } as const;
      case "members":
        return { section, data: await getSettingsMembers() } as const;
      default:
        return { section: "static" } as const;
    }
  } catch (error) {
    const recovery = accountRecoveryFor(error);
    if (!recovery) throw error;
    return { section: "recovery", recovery } as const;
  }
}
