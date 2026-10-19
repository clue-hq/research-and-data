/**
 * Slice 1 fixtures: a REAL brand kit, harvested from a real website
 * ingestion — not a hand-written shape.
 *
 * Harvest provenance (2026-08-18): `POST /brand-kits/ingest/website
 * {"url": "https://stripe.com"}` against the design API on the shared dev
 * Postgres, workspace `ws_8040294627e146ae93f753ec0d3e1726` ("Insight
 * Health"). Job `ingest_813df4f30f2d429a853dbccae2277a5a` → succeeded →
 * kit `brand_kit_ing_813df4f30f2d429a853dbccae2277a5a` v1, `approval_status:
 * "draft"`. Capture reached TIER 1 (static): the quality gate did not
 * escalate — the job's evidence carries no screenshots and no LUMI0505/0506
 * diagnostic. Vision assist left OFF (slice 6 owns that flip).
 *
 * - `brand-kit.harvested.json` — `GET /brand-kits/{id}` verbatim.
 * - `brand-kit-assets.harvested.json` — `GET /assets/{asset_id}` verbatim for
 *   every asset the kit references (2 logos + 13 images), keyed by asset id.
 */
import kitDetail from "./brand-kit.harvested.json";
import assetRecords from "./brand-kit-assets.harvested.json";
import measuredKitDetail from "./brand-kit.measured.json";

export const HARVESTED_BRAND_KIT: unknown = kitDetail;
export const HARVESTED_ASSET_RECORDS: Record<string, unknown> = assetRecords;

/**
 * Wave 2 A9 (Task X6): a kit carrying everything the extraction measures — `measured_components`,
 * the minted style and colour tokens, a minted section background — as `GET /brand-kits/{id}` serves
 * it. Written by `subsystems/clue-design/scripts/build_site_kit_brand_fixtures.py` from the probe's
 * committed harvest of `apps/api/tests/fixtures/capture/style_states.html` over Garner's kit, through
 * the real minting code and the real detail DTO; never edited by hand.
 */
export const MEASURED_BRAND_KIT: unknown = measuredKitDetail;
