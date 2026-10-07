"use client";

import { useMemo } from "react";
import { Puck, type Data, type Viewports } from "@puckeditor/core";
import type { BrandData } from "@/lib/brands";
import { makeConfig } from "@/puck/config";

// Our three review widths; desktop at 1440, the width the brand kits were measured at.
const VIEWPORTS: Viewports = [
  { width: 375, height: "auto", label: "Phone" },
  { width: 768, height: "auto", label: "Tablet" },
  { width: 1440, height: "auto", label: "Desktop" },
];

export function Editor({
  site,
  route,
  data,
  brand,
}: {
  site: string;
  route: string;
  data: Data;
  brand: BrandData;
}) {
  const config = useMemo(() => makeConfig(brand), [brand]);
  return (
    <Puck
      config={config}
      data={data}
      viewports={VIEWPORTS}
      ui={{ viewports: { current: { width: 1440, height: "auto" }, controlsVisible: true, options: VIEWPORTS } }}
      onPublish={async (next) => {
        await fetch("/api/save", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ site, route, data: next }),
        });
      }}
    />
  );
}
