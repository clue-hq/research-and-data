import { clerkMiddleware } from "@clerk/nextjs/server";
import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";
import {
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "@/auth/config";
import { normalizeClerkProxyResponse } from "@/auth/clerk-proxy-response";

const clerkProxy = clerkMiddleware();

export default async function proxy(
  request: NextRequest,
  event: NextFetchEvent,
) {
  if (!isAuthenticationEnabled()) return NextResponse.next();
  requireAuthenticationConfiguration();
  return normalizeClerkProxyResponse(
    request.url,
    await clerkProxy(request, event),
  );
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
