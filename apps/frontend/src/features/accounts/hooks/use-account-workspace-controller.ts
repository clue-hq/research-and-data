import { useEffect, useMemo, useState } from "react";
import { useCopyFeedback } from "@/hooks/use-copy-feedback";

export function useAccountWorkspaceHeaderController() {
  const copy = useCopyFeedback({
    copiedLabel: "Link copied",
    idleLabel: "Copy account link",
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

export function useAccountDetailsPanelController() {
  const [detailsVisible, setDetailsVisible] = useState(false);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1280px)");
    const sync = () => setDetailsVisible(desktop.matches);
    sync();
    desktop.addEventListener("change", sync);
    return () => desktop.removeEventListener("change", sync);
  }, []);

  return useMemo(
    () => ({ detailsVisible, setDetailsVisible }),
    [detailsVisible],
  );
}
