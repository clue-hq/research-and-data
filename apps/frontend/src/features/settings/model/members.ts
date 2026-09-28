import { z } from "zod";
export const MemberRoleSchema = z.enum(["admin", "operator"]);
export type MemberRole = z.infer<typeof MemberRoleSchema>;
export const MemberSchema = z.object({
  kind: z.enum(["member", "invitation"]),
  id: z.string(),
  name: z.string().nullable(),
  email: z.string().nullable(),
  role_key: z.enum(["owner", "admin", "operator", "viewer"]),
  state: z.enum(["active", "invited", "removed", "suspended"]),
  joined_on: z.string().nullable(),
  is_self: z.boolean(),
});
export const MembersSchema = z.object({
  rows: z.array(MemberSchema),
  invitations_configured: z.boolean(),
});
export const InvitationOutcomesSchema = z.object({
  outcomes: z.array(
    z.object({
      email: z.string(),
      outcome: z.enum([
        "sent",
        "created_no_email",
        "already_member",
        "already_invited",
        "invalid",
        "rate_limited",
        "delivery_failed",
      ]),
    }),
  ),
});
export type SettingsMember = z.infer<typeof MemberSchema>;
export type SettingsMembers = z.infer<typeof MembersSchema>;
export function memberRoleLabel(role: SettingsMember["role_key"]): string {
  return role === "owner" || role === "admin" ? "Admin" : "Member";
}
export function memberJoinedLabel(member: SettingsMember): string {
  if (member.state === "suspended") return "Suspended";
  if (member.state === "removed") return "Removed";
  if (member.state === "invited") return "Invited";
  return member.joined_on
    ? new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(`${member.joined_on}T00:00:00Z`))
    : "—";
}
const outcomeCopy = {
  sent: "invitations sent",
  created_no_email: "invited; will join on next sign-in (no email sent)",
  already_member: "already members",
  already_invited: "already invited",
  invalid: "invalid addresses",
  rate_limited: "rate limited; revoke and invite again later",
  delivery_failed: "emails could not be sent; revoke and invite again",
} as const;
export function invitationSummary(
  result: z.infer<typeof InvitationOutcomesSchema>,
): string {
  const counts = new Map<keyof typeof outcomeCopy, number>();
  for (const row of result.outcomes)
    counts.set(row.outcome, (counts.get(row.outcome) ?? 0) + 1);
  return [...counts]
    .map(([kind, count]) => `${count} ${outcomeCopy[kind]}`)
    .join(" · ");
}
