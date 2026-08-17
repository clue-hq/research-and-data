/**
 * Asset type closure for the extracted web engine (W1.1).
 *
 * Copied verbatim from the design subsystem's editor contracts
 * (subsystems/clue-design/apps/editor/src/engine/contracts.ts) — the minimal
 * transitive closure webDocuments' `upsert_asset` operation needs. Type-only;
 * the platform frontend must not import design-subsystem internals (seam
 * discipline), so the closure is vendored rather than referenced.
 */

export type StableId = string;

export type AssetId = StableId;

export interface AssetRecord {
  id: AssetId;
  label: string;
  kind: AssetKind;
  status: AssetStatus;
  source: AssetSource;
  media?: AssetMediaMetadata;
  raster?: RasterAssetMetadata | null;
  vector?: VectorAssetMetadata | null;
  font?: FontAssetMetadata | null;
  logo?: LogoAssetMetadata | null;
  license?: AssetLicense | null;
  provenance?: AssetProvenance;
  tags?: string[];
}

export type AssetKind = "raster_image" | "vector" | "font" | "logo" | "document" | "other";

export type AssetStatus = "pending" | "ready" | "failed" | "archived";

export type AssetSource =
  | { kind: "uploaded"; asset_id?: AssetId | null; filename: string | null; uploaded_by: string | null }

export interface AssetMediaMetadata {
  mime_type?: string | null;
  filename?: string | null;
  byte_length?: number | null;
  digest?: AssetDigest | null;
  location?: AssetLocation | null;
  thumbnail?: AssetThumbnail | null;
}

export interface AssetThumbnail {
  location: AssetLocation;
  mime_type: string;
  pixel_width?: number | null;
  pixel_height?: number | null;
  /** Stamped by the API at the DTO boundary (public_asset_record) so the
   * editor can build /asset-store/{digest} URLs without parsing refs. */
  digest?: AssetDigest | null;
}

export interface AssetDigest {
  algorithm: string;
  value: string;
}

export interface AssetLocation {
  provider: string;
  opaque_ref: string;
  url: string | null;
}

export interface RasterAssetMetadata {
  pixel_width: number;
  pixel_height: number;
  dpi_x: number | null;
  dpi_y: number | null;
  has_alpha: boolean | null;
  color_profile: string | null;
  aspect_ratio: number | null;
}

export interface VectorAssetMetadata {
  width: number | null;
  height: number | null;
  view_box: [number, number, number, number] | null;
  has_transparency: boolean | null;
  path_data: string | null;
}

export interface FontAssetMetadata {
  family: string;
  postscript_name: string | null;
  weights: number[];
  styles: string[];
  scripts: string[];
  embeddable: boolean;
  subsettable: boolean;
}

export interface LogoAssetMetadata {
  pixel_width: number | null;
  pixel_height: number | null;
  width: number | null;
  height: number | null;
  dpi_x: number | null;
  dpi_y: number | null;
  has_transparency: boolean | null;
  color_mode: string | null;
  clearspace: number | null;
}

export interface AssetLicense {
  name: string;
  allow_export: boolean;
  allow_modification: boolean;
  allow_embedding?: boolean;
  allow_subsetting?: boolean;
  source_url?: string | null;
  restrictions?: string[];
}

export interface AssetProvenance {
  created_by?: string | null;
  created_at?: string | null;
  source_label?: string | null;
  confidence?: number | null;
  notes?: string[];
}
