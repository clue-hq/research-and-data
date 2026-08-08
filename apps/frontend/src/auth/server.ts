import "server-only";

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import {
  clerkJwtTemplate,
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "./config";

export async function providerSessionToken(): Promise<string | null> {
  if (!isAuthenticationEnabled()) return null;
  requireAuthenticationConfiguration();
  const session = await auth({ acceptsToken: "session_token" });
  if (!session.isAuthenticated) return null;
  return session.getToken({ template: clerkJwtTemplate() });
}

export async function requireProviderSessionToken(): Promise<string> {
  const token = await providerSessionToken();
  if (!token) redirect("/sign-in?reason=session_expired");
  return token;
}
