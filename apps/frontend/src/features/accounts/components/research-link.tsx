"use client";

import Link from "next/link";
import { createContext, useContext, type ComponentProps, type ReactNode } from "react";
import { researchHref, type ResearchContextQuery } from "../model/research-context";

const ResearchNavigation = createContext<{ accountId: string; context: ResearchContextQuery } | null>(null);

export function ResearchNavigationProvider({ accountId, context, children }: {
  accountId: string; context: ResearchContextQuery; children: ReactNode;
}) {
  return <ResearchNavigation.Provider value={{ accountId, context }}>{children}</ResearchNavigation.Provider>;
}

export function useResearchNavigation() {
  return useContext(ResearchNavigation);
}

export default function ResearchLink({ href, ...props }: ComponentProps<typeof Link>) {
  const navigation = useContext(ResearchNavigation);
  const contextualHref = navigation && typeof href === "string"
    ? researchHref(href, navigation.accountId, navigation.context) : href;
  return <Link {...props} href={contextualHref} />;
}
