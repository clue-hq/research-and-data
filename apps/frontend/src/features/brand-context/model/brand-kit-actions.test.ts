import assert from "node:assert/strict";
import test from "node:test";
import { HARVESTED_BRAND_KIT } from "../data/__fixtures__/harvest";
import { BrandKitDetailSchema } from "./brand-kit";
import {
  IngestionJobSchema,
  approvalChip,
  isJobActive,
  latestWebsiteUrl,
  panelEmptyMessage,
  reExtractState,
  toBrandKitMeta,
  type BrandKitMeta,
  type IngestionJob,
} from "./brand-kit-actions";

const harvestedBrandKit = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);

const KIT: BrandKitMeta = {
  approvalStatus: "draft",
  id: "brand_kit_ing_1",
  sourceUrl: "https://stripe.com",
  version: 1,
};

function job(overrides: Partial<IngestionJob> = {}): IngestionJob {
  return {
    job_id: "ingest_1",
    kind: "website",
    status: "succeeded",
    website_url: "https://stripe.com",
    ...overrides,
  };
}

test("the kit meta is projected from the real harvested kit", () => {
  const meta = toBrandKitMeta(harvestedBrandKit);

  assert.equal(meta.id, "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a");
  assert.equal(meta.version, 1);
  assert.equal(meta.approvalStatus, "draft");
  assert.equal(meta.sourceUrl, "https://stripe.com");
});

test("a kit that records no usable source has no source url", () => {
  const withoutSources = {
    ...harvestedBrandKit,
    brand_kit_json: { ...harvestedBrandKit.brand_kit_json, sources: [] },
  };
  const blankUrl = {
    ...harvestedBrandKit,
    brand_kit_json: {
      ...harvestedBrandKit.brand_kit_json,
      sources: [{ kind: "pdf", url: null }],
    },
  };

  assert.equal(toBrandKitMeta(withoutSources).sourceUrl, null);
  assert.equal(toBrandKitMeta(blankUrl).sourceUrl, null);
});

// --- the status chip --------------------------------------------------------------

test("each approval status maps to its own chip, and no kit means no chip", () => {
  assert.deepEqual(approvalChip({ ...KIT, approvalStatus: "draft" }), {
    label: "Draft",
    tone: "draft",
  });
  assert.deepEqual(approvalChip({ ...KIT, approvalStatus: "generated_unreviewed" }), {
    label: "Generated — unreviewed",
    tone: "unreviewed",
  });
  assert.deepEqual(approvalChip({ ...KIT, approvalStatus: "approved" }), {
    label: "Approved",
    tone: "approved",
  });
  assert.equal(approvalChip(null), null);
  assert.equal(approvalChip({ ...KIT, approvalStatus: null }), null);
  assert.equal(approvalChip({ ...KIT, approvalStatus: "  " }), null);
});

test("a status this build does not name is reported in the store's own word", () => {
  assert.deepEqual(approvalChip({ ...KIT, approvalStatus: "deprecated" }), {
    label: "deprecated",
    tone: "neutral",
  });
});

// --- Approve ----------------------------------------------------------------------



// --- Re-extract -------------------------------------------------------------------

test("a kit re-extracts into its own next version", () => {
  assert.deepEqual(reExtractState(KIT, [job()]), {
    kind: "ready",
    request: { brand_kit_id: "brand_kit_ing_1", url: "https://stripe.com" },
  });
});

test("a kit that records no source falls back to the newest website job's url", () => {
  assert.deepEqual(
    reExtractState({ ...KIT, sourceUrl: null }, [
      job({ job_id: "ingest_2", website_url: "https://linear.app" }),
      job({ website_url: "https://stripe.com" }),
    ]),
    {
      kind: "ready",
      request: { brand_kit_id: "brand_kit_ing_1", url: "https://linear.app" },
    },
  );
});

test("a kit-less workspace rescues its failed auto-ingestion with a FRESH run", () => {
  assert.deepEqual(reExtractState(null, [job({ status: "failed" })]), {
    kind: "ready",
    request: { url: "https://stripe.com" },
  });
});

test("a running or queued ingestion holds the button", () => {
  assert.deepEqual(reExtractState(KIT, [job({ status: "running" })]), { kind: "busy" });
  assert.deepEqual(reExtractState(KIT, [job({ status: "queued" })]), { kind: "busy" });
  assert.deepEqual(reExtractState(null, [job({ status: "queued" })]), { kind: "busy" });
  // A newer terminal job cannot hide an older runner: "disabled while A job runs" is global.
  assert.deepEqual(
    reExtractState(KIT, [job(), job({ job_id: "older", status: "running" })]),
    { kind: "busy" },
  );
});

test("an ad-assets job neither holds the button nor claims the brand is extracting", () => {
  // Onboarding runs an ad harvest beside the website ingestion; it builds no kit.
  const adsRunning = [job({ kind: "ad_assets", status: "running", website_url: null })];
  assert.deepEqual(reExtractState(KIT, adsRunning), {
    kind: "ready",
    request: { url: "https://stripe.com", brand_kit_id: "brand_kit_ing_1" },
  });
  assert.equal(panelEmptyMessage("colors", adsRunning), "No colors yet.");
});

test("neither a kit nor a url on record leaves nothing to re-extract", () => {
  assert.deepEqual(reExtractState(null, []), { kind: "unavailable" });
  assert.deepEqual(reExtractState({ ...KIT, sourceUrl: null }, []), { kind: "unavailable" });
  // A PDF job carries no website url, so it is no rescue.
  assert.deepEqual(
    reExtractState(null, [job({ kind: "pdf", status: "failed", website_url: null })]),
    { kind: "unavailable" },
  );
});

// --- the panels' empty states ------------------------------------------------------

test("an in-flight ingestion explains itself; otherwise the empties are minimal", () => {
  const running = [job({ status: "running" })];
  assert.equal(panelEmptyMessage("colors", running), "Extracting your brand from your website…");
  assert.equal(
    panelEmptyMessage("typography", running),
    "Extracting your brand from your website…",
  );
  assert.equal(panelEmptyMessage("colors", []), "No colors yet.");
  assert.equal(panelEmptyMessage("typography", []), "No text styles yet.");
  assert.equal(panelEmptyMessage("colors", [job({ status: "failed" })]), "No colors yet.");
});

// --- wire tolerance ----------------------------------------------------------------

test("an unknown job status reads as in-flight, never as a published kit", () => {
  const parsed = IngestionJobSchema.parse({
    job_id: "ingest_x",
    kind: "website",
    status: "reticulating",
    website_url: "https://stripe.com",
  });

  assert.equal(parsed.status, "running");
  assert.equal(isJobActive(parsed), true);
});

test("a pre-slice-4 job payload without website_url still parses", () => {
  const parsed = IngestionJobSchema.parse({
    job_id: "ingest_x",
    kind: "website",
    status: "succeeded",
  });

  assert.equal(parsed.website_url ?? null, null);
  assert.equal(latestWebsiteUrl([parsed]), null);
});

test("a job that finished with gaps is a finished job, not an active one", () => {
  const parsed = IngestionJobSchema.parse({
    job_id: "ingest_x",
    kind: "website",
    status: "succeeded_with_gaps",
  });

  assert.equal(parsed.status, "succeeded_with_gaps");
  assert.equal(isJobActive(parsed), false);
});
