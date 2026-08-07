import { useState } from "react";

export function useMobileNavigation() {
  const [open, setOpen] = useState(false);

  return {
    close: () => setOpen(false),
    open,
    show: () => setOpen(true),
  };
}
