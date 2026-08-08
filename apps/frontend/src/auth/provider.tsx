import { ClerkProvider } from "@clerk/nextjs";
import { connection } from "next/server";
import {
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "./config";

export async function AuthenticationProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Auth mode and Clerk state are deployment/request data. Never bake a disabled provider or a
  // signed-in shell into a static build that can later run under different runtime settings.
  await connection();
  if (!isAuthenticationEnabled()) return children;
  requireAuthenticationConfiguration();
  return <ClerkProvider>{children}</ClerkProvider>;
}
