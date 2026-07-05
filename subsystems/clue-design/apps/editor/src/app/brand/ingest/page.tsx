"use client";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import { IngestConsole } from "@/components/brand/IngestConsole";

export default function BrandIngestPage() {
  return (
    <>
      <header className="brand-section-head">
        <div>
          <p className="eyebrow">Ingest a brand</p>
          <h1 className="headline">Bring your brand in.</h1>
        </div>
      </header>
      <IngestConsole apiBaseUrl={editorApiBaseUrl()} />
    </>
  );
}
