"use client";

import { useEffect, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { DesignIcon } from "@/components/ui/design-icon";
import type { SettingsSection } from "../model/settings";
import { SettingsNavigation } from "./settings-sidebar";
import styles from "./settings.module.css";

export function SettingsMobileNavigation({
  activeSection,
}: {
  activeSection: SettingsSection;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // Keep the modal/focus trap from surviving a resize back to the desktop sidebar.
    const narrowViewport = window.matchMedia("(max-width: 860px)");
    function onResize(event: MediaQueryListEvent) {
      if (!event.matches) setOpen(false);
    }
    narrowViewport.addEventListener("change", onResize);
    return () => narrowViewport.removeEventListener("change", onResize);
  }, []);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        aria-label="Open settings navigation"
        className={`${styles.sidebarToggle} ${styles.mobileSidebarTrigger}`}
        type="button"
      >
        <DesignIcon name="sidebar-toggle" size={16} />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className={styles.mobileSidebarBackdrop} />
        <Dialog.Popup className={styles.mobileSidebarPanel}>
          <header className={styles.mobileSidebarHeader}>
            <Dialog.Title className={styles.mobileSidebarTitle}>
              Settings
            </Dialog.Title>
            <Dialog.Close
              aria-label="Close settings navigation"
              className={styles.sidebarToggle}
              type="button"
            >
              <DesignIcon name="sidebar-toggle" size={16} />
            </Dialog.Close>
          </header>
          <SettingsNavigation
            activeSection={activeSection}
            onNavigate={() => setOpen(false)}
          />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
