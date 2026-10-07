"use client";

// A Puck custom field: pick one of the brand kit's images or logos, shown with its description.
// The value stored on the page is the asset's file URL.
import type { BrandAsset } from "@/lib/brands";

export function AssetPicker({
  assets,
  value,
  onChange,
}: {
  assets: Record<string, BrandAsset>;
  value: string;
  onChange: (value: string) => void;
}) {
  const images = Object.values(assets).filter(
    (asset) => asset.mime?.startsWith("image/") || /\.(png|jpe?g|webp|avif|svg)$/.test(asset.file),
  );
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, maxHeight: 280, overflowY: "auto" }}>
      <button
        type="button"
        onClick={() => onChange("")}
        style={{
          border: value ? "1px solid #ddd" : "2px solid #2563eb",
          borderRadius: 6, fontSize: 11, color: "#666", minHeight: 64, background: "#fafafa",
        }}
      >
        None
      </button>
      {images.map((asset) => (
        <button
          key={asset.file}
          type="button"
          title={asset.description ?? asset.label ?? asset.file}
          onClick={() => onChange(asset.file)}
          style={{
            border: value === asset.file ? "2px solid #2563eb" : "1px solid #ddd",
            borderRadius: 6, padding: 2, background: "#f4f4f5", minHeight: 64, cursor: "pointer",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={asset.file} alt={asset.description ?? ""} style={{ width: "100%", height: 60, objectFit: "contain" }} />
        </button>
      ))}
    </div>
  );
}
