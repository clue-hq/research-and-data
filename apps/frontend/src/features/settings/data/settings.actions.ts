import { z } from "zod";
import { fetchMutation } from "@/features/accounts/data/frontend-mutation";
import { ProfileSchema } from "../model/profile";
import { WorkspaceSchema } from "../model/workspace";
import { ResearchFieldSchema, type ResearchEntity, type ResearchFieldEdit } from "../model/research-fields";
import {
  MembersSchema,
  InvitationOutcomesSchema,
  type MemberRole,
} from "../model/members";

export async function patchSettingsProfile(
  body: { full_name?: string; display_name?: string | null },
  request?: typeof fetch,
) {
  return ProfileSchema.parse(
    await fetchMutation(
      "/settings/profile",
      { method: "PATCH", body: JSON.stringify(body) },
      request,
    ),
  );
}

export async function createSettingsResearchField(
  body: { entity: ResearchEntity; label: string; description: string },
  request?: typeof fetch,
) {
  return ResearchFieldSchema.parse(await fetchMutation(
    "/settings/research-fields", { method: "POST", body: JSON.stringify(body) }, request,
  ));
}

export async function patchSettingsResearchField(
  key: string, body: ResearchFieldEdit, request?: typeof fetch,
) {
  return ResearchFieldSchema.parse(await fetchMutation(
    `/settings/research-fields/${encodeURIComponent(key)}`,
    { method: "PATCH", body: JSON.stringify(body) }, request,
  ));
}

export async function retireSettingsResearchField(key: string, request?: typeof fetch) {
  return z.object({ ok: z.literal(true) }).parse(await fetchMutation(
    `/settings/research-fields/${encodeURIComponent(key)}`, { method: "DELETE" }, request,
  ));
}
export async function patchSettingsWorkspace(
  name: string,
  request?: typeof fetch,
) {
  return WorkspaceSchema.parse(
    await fetchMutation(
      "/settings/workspace",
      { method: "PATCH", body: JSON.stringify({ name }) },
      request,
    ),
  );
}
export async function refreshSettingsMembers(request?: typeof fetch) {
  return MembersSchema.parse(
    await fetchMutation(
      "/settings/members",
      { method: "GET", cache: "no-store" },
      request,
    ),
  );
}
export async function inviteSettingsMembers(
  emails: string[],
  role: MemberRole,
  request?: typeof fetch,
) {
  return InvitationOutcomesSchema.parse(
    await fetchMutation(
      "/settings/members/invitations",
      { method: "POST", body: JSON.stringify({ emails, role }) },
      request,
    ),
  );
}
export async function changeSettingsMember(
  id: string,
  action: "role" | "remove" | "readmit" | "revoke",
  role: MemberRole = "operator",
  request?: typeof fetch,
) {
  const path =
    action === "revoke"
      ? `/settings/members/invitations/${encodeURIComponent(id)}`
      : `/settings/members/${encodeURIComponent(id)}${action === "readmit" ? "/readmit" : ""}`;
  return z.object({ ok: z.literal(true) }).parse(
    await fetchMutation(
      path,
      {
        method:
          action === "role"
            ? "PATCH"
            : action === "readmit"
              ? "POST"
              : "DELETE",
        ...(["role", "readmit"].includes(action)
          ? { body: JSON.stringify({ role }) }
          : {}),
      },
      request,
    ),
  );
}
