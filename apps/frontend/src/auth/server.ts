import "server-only";

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import {
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "./config";

export async function providerSessionToken(): Promise<string | null> {
  if (!isAuthenticationEnabled()) return null;
  requireAuthenticationConfiguration();
  const session = await auth({ acceptsToken: "session_token" });
  if (!session.isAuthenticated) return null;
  // Default session token, no JWT template: it carries the session-bound `sid`/`azp` claims
  // the backend requires; template tokens cannot (and `aud` no longer participates).
  return session.getToken();
}

export async function requireProviderSessionToken(): Promise<string> {
  const token = await providerSessionToken();
  if (!token) redirect("/sign-in?reason=session_expired");
  return token;
}
