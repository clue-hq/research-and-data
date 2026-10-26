import type { ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import s from "./workspace.module.css";

export function DetailPanel({ title, description, close, children }: {
  title: string; description: string; close: () => void; children: ReactNode;
}) {
  return <Dialog.Root open onOpenChange={(open) => { if (!open) close(); }}>
    <Dialog.Portal>
      <Dialog.Backdrop className={s.backdrop} />
      <Dialog.Popup className={s.drawer}>
        <header className={s.drawerHeader}>
          <div><Dialog.Title className={s.panelTitle}>{title}</Dialog.Title><Dialog.Description className={s.caption}>{description}</Dialog.Description></div>
          <Button variant="transparent" size="icon-sm" aria-label="Close account preview" onClick={close}><X size={16} /></Button>
        </header>
        {children}
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}
