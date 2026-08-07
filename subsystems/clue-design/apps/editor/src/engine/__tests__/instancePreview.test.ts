import { afterEach, describe, expect, it, vi } from "vitest";

import mailerRevision from "../../../../../crates/lumen-core/fixtures/conformance/phase_g_mailer_revision.json";
import type { Scene } from "../contracts";
import { buildWorstCaseBindingSet, fetchInstancePreview } from "../instancePreview";

const scene = mailerRevision as unknown as Scene;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildWorstCaseBindingSet", () => {
  it("binds every slot at its declared worst case", () => {
    const binding = buildWorstCaseBindingSet(scene);

    expect(binding.schema_version).toBe(1);
    expect(binding.template_revision_id).toBe("tmpl_mailer_v1");

    expect(binding.values["contact.full_name"]).toEqual({
      kind: "text",
      value: "Dr. Maximilian Whitmore-Kensington"
    });
    expect(binding.values["campaign.cta"]).toEqual({
      kind: "text",
      value: "Reserve your personalized onboarding session"
    });
    // Quote slot has no worst_case fixture; the longest sample stands in.
    expect(binding.values["research.quote"]).toEqual({
      kind: "text",
      value: "Their team shipped twice as fast."
    });
    // Logo reuses the template's own placeholder asset.
    expect(binding.values["account.logo"]).toEqual({
      kind: "asset",
      asset_id: "asset_placeholder_logo"
    });
  });

  it("expands repeaters to max_items of the item worst case", () => {
    const binding = buildWorstCaseBindingSet(scene);
    const insights = binding.values["research.key_insights"] as {
      kind: string;
      items: Array<{ kind: string; value: string }>;
    };
    expect(insights.kind).toBe("list");
    expect(insights.items).toHaveLength(4);
    for (const item of insights.items) {
      expect(item.value).toBe(
        "Consolidated eleven legacy intake workflows into one branded patient journey"
      );
    }
    // Item slots bind through the repeater list, never directly.
    expect(binding.values["research.key_insights.item"]).toBeUndefined();
  });

  it("chains UrlQr slots through a preview landing link", () => {
    const binding = buildWorstCaseBindingSet(scene);
    expect(binding.links.landing_page.url).toContain("https://");
    const generated = binding.generated["qr_campaign_qr"];
    expect(generated).toEqual({
      provider: "qr",
      input: { url_from: "links.landing_page.url", ec_level: "h" },
      bind_to_slot: "campaign.qr"
    });
  });
});

describe("fetchInstancePreview", () => {
  it("posts the scene and binding set and returns the preview", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ok",
        fit_report: { status: "fits", slots: [] },
        diagnostics: [],
        artifact: { format: "svg", content: "<svg/>" }
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    const binding = buildWorstCaseBindingSet(scene);
    const result = await fetchInstancePreview(
      "http://localhost:8000",
      scene,
      binding,
      "svg"
    );

    expect(result.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toBe("http://localhost:8000/instances/preview");
    const body = JSON.parse(String(init.body));
    expect(body.binding_set.binding_set_id).toBe("bind_worst_case_preview");
    expect(body.format).toBe("svg");
  });

  it("surfaces API failures as errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: { code: "instance.binding_invalid" } })
      })
    );
    await expect(
      fetchInstancePreview(
        "http://localhost:8000",
        scene,
        buildWorstCaseBindingSet(scene)
      )
    ).rejects.toThrow(/422/);
  });
});
