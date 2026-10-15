"use client";

import { useEffect, useState } from "react";
import { dismissProductNotice, readProductNotices } from "../data/product-notices";
import type { ProductNotice } from "../model/product-notice";

/** The project's "Products changed" notices (spec 2026-10-15 §7), loaded once per project. */
export function useProductNotices(projectId: string | undefined) {
  const [notices, setNotices] = useState<ProductNotice[]>([]);

  useEffect(() => {
    if (!projectId) return;
    let live = true;
    void readProductNotices(projectId).then((loaded) => {
      if (live) setNotices(loaded);
    });
    return () => {
      live = false;
    };
  }, [projectId]);

  async function dismiss(changeId: string) {
    if (!projectId) return;
    setNotices((current) => current.filter((notice) => notice.changeId !== changeId));
    await dismissProductNotice(projectId, changeId);
  }

  return { notices: projectId ? notices : [], dismiss };
}
