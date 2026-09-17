import { useMemo, useState, useSyncExternalStore } from "react";
import { useCopyFeedback } from "@/hooks/use-copy-feedback";

export function useAccountWorkspaceHeaderController(copyLinkLabel = "Copy account link") {
  const copy = useCopyFeedback({
    copiedLabel: "Link copied",
    idleLabel: copyLinkLabel,
    resetAfter: 1600,
  });
  const [menuOpen, setMenuOpen] = useState(false);

  return {
    closeMenu: () => setMenuOpen(false),
    copy,
    menuOpen,
    toggleMenu: () => setMenuOpen((current) => !current),
  };
}

function subscribeDesktop(listener: () => void) {
  const desktop = window.matchMedia("(min-width: 1280px)");
  desktop.addEventListener("change", listener);
  return () => desktop.removeEventListener("change", listener);
}

export function useAccountDetailsPanelController() {
  // CSS handles the initial breakpoint before hydration. User preference lives
  // in the shared account layout so navigating tabs cannot reopen a closed rail.
  const [detailsPreference, setDetailsVisible] = useState<boolean | undefined>();
  const desktop = useSyncExternalStore(subscribeDesktop,
    () => window.matchMedia("(min-width: 1280px)").matches, () => true);
  const detailsVisible = detailsPreference ?? desktop;

  return useMemo(
    () => ({ detailsVisible, detailsPreference: detailsPreference ?? "auto" as const, setDetailsVisible }),
    [detailsVisible, detailsPreference],
  );
}
