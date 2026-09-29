import { z } from "zod";

export const WorkspaceRoleSchema = z.enum([
  "owner",
  "admin",
  "operator",
  "viewer",
]);

/**
 * `owner` reads as `Owner`. It lives here, beside the role schema, rather than in
 * the switcher's client module: the protected layout is a server component, and
 * Next refuses to call a `"use client"` module's function from the server.
 */
export function roleLabel(roleKey: string): string {
  return roleKey ? roleKey[0]!.toLocaleUpperCase() + roleKey.slice(1) : roleKey;
}

export const SessionMembershipSchema = z.object({
  membership_id: z.string().min(1),
  workspace_id: z.string().min(1),
  // The only workspace value a person is ever shown. The id is a routing key and
  // a cookie value; it never reaches a screen.
  workspace_name: z.string().min(1),
  role_key: WorkspaceRoleSchema,
  permissions: z.array(z.string().min(1)),
  // The company's logo for the workspace switcher: Brandfetch's embed-only Logo
  // API mark for the website given at onboarding, or null (initials instead).
  workspace_logo_url: z
    .string()
    .refine((value) => value.startsWith("https://cdn.brandfetch.io/"))
    .nullable()
    .optional(),
}).strict();

export const AuthenticatedSessionSchema = z.object({
  user_id: z.string().min(1),
  memberships: z.array(SessionMembershipSchema),
  // Distinguishes "never had access" (route to onboarding) from "had access, lost it"
  // (route to access-denied) without exposing the inactive membership rows.
  has_inactive_memberships: z.boolean(),
}).strict();

export const RequestPrincipalSchema = z.object({
  user_id: z.string().min(1),
  membership_id: z.string().min(1),
  workspace_id: z.string().min(1),
  role_key: WorkspaceRoleSchema,
  permissions: z.array(z.string().min(1)),
}).strict();

export const WORKSPACE_COOKIE = "clue_workspace_id";

export type SessionMembership = z.infer<typeof SessionMembershipSchema>;
export type AuthenticatedSession = z.infer<typeof AuthenticatedSessionSchema>;
export type RequestPrincipal = z.infer<typeof RequestPrincipalSchema>;

export interface ProtectedSession {
  userId: string;
  memberships: readonly SessionMembership[];
  principal: RequestPrincipal;
}

export function resolveWorkspaceMembership(
  session: AuthenticatedSession,
  requestedWorkspaceId: string | null | undefined,
  pinnedWorkspaceId: string | null = null,
): SessionMembership | null {
  const workspaceId = pinnedWorkspaceId ?? requestedWorkspaceId;
  if (workspaceId) {
    return (
      session.memberships.find(
        (membership) => membership.workspace_id === workspaceId,
      ) ?? null
    );
  }
  return null;
}
