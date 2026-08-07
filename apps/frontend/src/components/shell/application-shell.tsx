"use client";

import { useState } from "react";
import { DesignIcon } from "@/components/ui/design-icon";
import { AppSidebar } from "./app-sidebar";
import { useMobileNavigation } from "./use-mobile-navigation";

export function ApplicationShell({
  activeHref,
  children,
}: {
  activeHref: string;
  children: React.ReactNode;
}) {
  const navigation = useMobileNavigation();
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);

  return (
    <div className="relative flex h-dvh min-h-0 w-full overflow-hidden bg-white">
      <div className="hidden h-full shrink-0 lg:block">
        <AppSidebar
          activeHref={activeHref}
          collapsed={desktopCollapsed}
          onToggle={() => setDesktopCollapsed((current) => !current)}
        />
      </div>

      {navigation.open ? (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-[#111827]/20 backdrop-blur-[1px]"
            onClick={navigation.close}
            type="button"
          />
          <AppSidebar
            activeHref={activeHref}
            className="relative z-10 shadow-[8px_0_32px_rgba(15,23,42,0.12)]"
            onToggle={navigation.close}
          />
        </div>
      ) : null}

      <button
        aria-expanded={navigation.open}
        aria-label="Open navigation"
        className="absolute top-3 left-3 z-40 flex size-8 items-center justify-center rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[var(--clue-shadow-low)] lg:hidden"
        onClick={navigation.show}
        type="button"
      >
        <DesignIcon name="sidebar-toggle" size={14} />
      </button>

      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
