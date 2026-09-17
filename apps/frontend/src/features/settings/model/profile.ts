import { z } from "zod";
import {
  WORKSPACE_AVATAR_COLOR,
  workspaceInitials,
  type WorkspaceProfile,
} from "@/features/accounts/model/workspace-profile";

export const ProfileSchema = z.object({
  user_id: z.string(),
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  full_name: z.string(),
  display_name: z.string().nullable(),
  email: z.string().nullable(),
});
export type SettingsProfile = z.infer<typeof ProfileSchema>;
export function shellProfile(profile: SettingsProfile): WorkspaceProfile {
  const name = profile.display_name || profile.full_name;
  return {
    id: profile.user_id,
    fullName: profile.full_name,
    displayName: name,
    initials: workspaceInitials(name),
    avatarColor: WORKSPACE_AVATAR_COLOR,
  };
}
