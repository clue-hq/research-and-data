"use client";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import { AssetLibrary } from "@/components/brand/AssetLibrary";

export default function BrandLibraryPage() {
  return (
    <>
      <header className="brand-section-head">
        <div>
          <p className="eyebrow">Asset library</p>
          <h1 className="headline">Every asset, described.</h1>
        </div>
      </header>
      <AssetLibrary apiBaseUrl={editorApiBaseUrl()} />
    </>
  );
}
