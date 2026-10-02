"use client";

import {
  createContext,
  useContext,
  useRef,
  type FocusEvent,
} from "react";
import { usePathname } from "next/navigation";
import { DesignIcon } from "@/components/ui/design-icon";
import { AppSidebar } from "./app-sidebar";
import {
  useDesktopSidebar,
  type DesktopSidebarController,
  type SidebarState,
} from "./use-desktop-sidebar";
import { useMobileNavigation } from "./use-mobile-navigation";

const ApplicationSidebarContext = createContext<DesktopSidebarController | null>(
  null,
);

export function useApplicationSidebar(): DesktopSidebarController {
  const sidebar = useContext(ApplicationSidebarContext);
  if (!sidebar) {
    throw new Error("project sidebar control requires the shared application shell");
  }
  return sidebar;
}

export function ProjectApplicationShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const projectRoute = pathname === "/" || pathname.startsWith("/projects");
  if (!projectRoute) return children;
  // Founder ruling 2026-08-17: the navigation rail stays visible on every
  // project route — including the workspace, chats, and artifact/editor
  // screens — matching the design build's persistent sidebar. This supersedes
  // the earlier collapsed-overlay default for project workspaces (the
  // 2026-08-10 state table remains for user-initiated collapse; only the
  // default changed). It also satisfies Phase C's (C-3) constraint: with the
  // in-pane thread switcher removed (ruling R4) the sidebar is the ONLY
  // thread switcher, so it must stay reachable on the chats route. (The
  // Phase C lane, merged 2026-08-18, carried a pre-ruling overlay/collapsed
  // carve-out for the artifact route; the dated founder ruling wins here.)
  return (
    <ApplicationShell
      activeHref={pathname === "/" ? "/" : "/projects"}
      desktopMode="rail"
      initialDesktopState="pinned-expanded"
    >
      {children}
    </ApplicationShell>
  );
}

export function ApplicationShell({
  activeHref,
  children,
  desktopMode = "rail",
  initialDesktopState = "pinned-expanded",
}: {
  activeHref: string;
  children: React.ReactNode;
  desktopMode?: "overlay" | "rail";
  initialDesktopState?: SidebarState;
}) {
  const navigation = useMobileNavigation();
  const mobileTrigger = useRef<HTMLButtonElement | null>(null);
  const sidebar = useDesktopSidebar(initialDesktopState);
  const desktopCollapsed = sidebar.state === "collapsed";
  const overlayMode = desktopMode === "overlay";

  function handleSidebarBlur(event: FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    sidebar.scheduleDismissal();
  }

  function closeMobileNavigation() {
    navigation.close();
    requestAnimationFrame(() => mobileTrigger.current?.focus());
  }

  return (
    <ApplicationSidebarContext.Provider value={sidebar}>
        <div
          className="relative flex h-dvh min-h-0 w-full overflow-hidden bg-white"
          data-sidebar-state={sidebar.state}
        >
        <div
          aria-hidden={overlayMode && desktopCollapsed ? true : undefined}
          className={
            overlayMode
              ? `absolute inset-y-0 left-0 z-50 hidden h-full transition-[transform,visibility] duration-200 ease-out lg:block ${
                  desktopCollapsed
                    ? "invisible -translate-x-full pointer-events-none"
                    : "visible translate-x-0 shadow-[8px_0_32px_rgba(15,23,42,0.12)]"
                } ${sidebar.state === "pinned-expanded" ? "lg:relative lg:z-auto lg:shrink-0 lg:shadow-none" : ""}`
              : "hidden h-full shrink-0 lg:block"
          }
          data-sidebar-placement={
            overlayMode && sidebar.state === "hover-preview" ? "overlay" : "layout"
          }
          inert={overlayMode && desktopCollapsed ? true : undefined}
          onBlurCapture={handleSidebarBlur}
          onFocusCapture={sidebar.cancelDismissal}
          onPointerEnter={sidebar.cancelDismissal}
          onPointerLeave={sidebar.scheduleDismissal}
        >
          <AppSidebar
            activeHref={activeHref}
            collapsed={overlayMode ? false : desktopCollapsed}
            id="application-sidebar"
            onToggle={
              overlayMode
                ? sidebar.closeFromSidebar
                : (trigger) => sidebar.toggle(trigger)
            }
            toggleLabel={
              overlayMode && sidebar.state === "hover-preview"
                ? "Close sidebar preview"
                : undefined
            }
          />
        </div>

        {navigation.open ? (
          <div className="fixed inset-0 z-50 flex lg:hidden">
            <button
              aria-label="Close navigation"
              className="absolute inset-0 bg-[#111827]/20 backdrop-blur-[1px]"
              onClick={closeMobileNavigation}
              type="button"
            />
            <AppSidebar
              activeHref={activeHref}
              className="relative z-10 shadow-[8px_0_32px_rgba(15,23,42,0.12)]"
              id="mobile-navigation"
              onToggle={closeMobileNavigation}
              toggleLabel="Close navigation"
            />
          </div>
        ) : null}

        <button
          aria-controls="mobile-navigation"
          aria-expanded={navigation.open}
          aria-label="Open navigation"
          className="absolute top-3 left-3 z-40 flex size-8 items-center justify-center rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[var(--clue-shadow-low)] lg:hidden"
          onClick={navigation.show}
          ref={mobileTrigger}
          type="button"
        >
          <DesignIcon name="sidebar-toggle" size={14} />
        </button>

          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            {children}
          </div>
        </div>
    </ApplicationSidebarContext.Provider>
  );
}
