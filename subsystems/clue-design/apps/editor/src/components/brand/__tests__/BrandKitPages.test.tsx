import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BrandKitListPage from "@/app/brand/page";
import BrandKitDetailPage from "@/app/brand/kits/[kitId]/page";

const API_BASE = "http://localhost:8000";

// --- next/navigation useParams stub (client route param) -------------------
let mockParams: Record<string, string> = { kitId: "kit_insight" };
vi.mock("next/navigation", () => ({
  useParams: () => mockParams
}));

// --- fixtures ---------------------------------------------------------------
function listSummary(overrides: Record<string, unknown> = {}) {
  return {
    id: "kit_insight",
    version: 1,
    name: "Insight Health",
    approval_status: "draft",
    product_ready: false,
    source: "website",
    description: "Digital-first primary care.",
    created_at: "2026-07-05",
    updated_at: "2026-07-05",
    ...overrides
  };
}

function colorToken(value: string, dark: string, role: string) {
  return {
    role,
    provenance: { source: "website:example :: body" },
    value: { default: { kind: "hex", value }, modes: { "theme.dark": { kind: "hex", value: dark } } }
  };
}

function paletteToken(value: string) {
  return { role: "palette", provenance: {}, value: { default: { kind: "hex", value }, modes: {} } };
}

/** A compact kit JSON reusing the golden-fixture shapes. `noFaces` drops the
 * font faces so the availability-warning branch renders. */
function kitJson(options: { noFaces?: boolean } = {}) {
  return {
    description: "Digital-first primary care.",
    sources: [{ kind: "website", url: "https://insight.example", captured_at: "2026-07-05" }],
    constraints: {
      tone: ["Warm, human, and clinically credible."],
      accessibility_notes: [],
      imagery: [],
      print_constraints: ["Confirm font embeddability before print export."]
    },
    assets: {
      fonts: {
        brand: {
          family: "Aeonik",
          fallback_stack: ["Helvetica Neue", "Arial", "sans-serif"],
          faces: options.noFaces
            ? []
            : [{ weight: 400, style: "normal", source_url: "https://insight.example/a.woff2" }]
        }
      },
      logos: {
        primary: {
          usage: "primary",
          variants: [{ name: "full_color", color_mode: "full_color", asset_id: "asset_logo_primary" }]
        }
      },
      images: {
        "img.1": { asset_id: "asset_hero", role: "photo", title: "Hero", description: "Warm clinic scene." }
      }
    },
    tokens: {
      colors: {
        "surface.page": colorToken("#F5F5F5", "#00170E", "surface"),
        "text.primary": colorToken("#1D1C1D", "#E3F3EC", "text"),
        "border.default": colorToken("#C1C1C1", "#2D493E", "border"),
        "surface.accent": colorToken("#19C092", "#12EAB1", "surface"),
        "palette.primary.100": paletteToken("#D6FAEA"),
        "palette.primary.500": paletteToken("#009E76"),
        "palette.neutral.100": paletteToken("#EFF0F2"),
        "palette.extra.aqua": { role: "palette", description: "Aqua", value: { default: { kind: "hex", value: "#00E3E1" }, modes: {} } }
      },
      typography: {
        "type.display": {
          role: "display",
          value: { default: { font_family: "Aeonik", font_size: 77, font_weight: 700, line_height: 1.05 }, modes: {} }
        }
      }
    }
  };
}

function ingestionSummary() {
  return {
    ingestion: {
      schema_version: 1,
      dark_colorway: "synthesized",
      source: { kind: "website", url: "https://insight.example", captured_at: "2026-07-05" },
      stats: { colors_observed: 5, fonts: 1, logos: 2, images: 3 },
      gaps: ["logo.reversed", "logo.wordmark"],
      rules: [
        { kind: "clearspace", text: "Maintain clearspace of 16px around the logo." },
        { kind: "tone", text: "Warm, human, and clinically credible." }
      ],
      role_assignments: [
        { basis: "evidence", pointer: "website:example :: body background", token: "surface.page", value: "#F5F5F5" },
        { basis: "derived", pointer: "derived:text.secondary", token: "text.secondary", value: "#504F50" }
      ]
    }
  };
}

function detailPayload(options: { noFaces?: boolean; approved?: boolean } = {}) {
  return {
    schema_version: 1,
    brand_kit: listSummary({ approval_status: options.approved ? "approved" : "draft" }),
    brand_kit_json: kitJson({ noFaces: options.noFaces }),
    brand_summary: ingestionSummary(),
    diagnostics: {
      audit: [],
      current: [],
      latest: [{ severity: "info", code: "LUMI0210", message: "dark colorway synthesized from light palette" }]
    }
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  mockParams = { kitId: "kit_insight" };
});

// ---------------------------------------------------------------------------
describe("BrandKitListPage", () => {
  it("renders each kit card from the list payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify([listSummary(), listSummary({ id: "kit_two", name: "Second" })]), { status: 200 }))
    );

    render(<BrandKitListPage />);

    await waitFor(() => expect(screen.getByTestId("kit-card-kit_insight")).toBeTruthy());
    expect(screen.getByText("Insight Health")).toBeTruthy();
    expect(screen.getByText("Second")).toBeTruthy();
    expect(screen.getByText("Your brand, distilled.")).toBeTruthy();
  });

  it("renders the empty state linking to ingest when no kits exist", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })));

    render(<BrandKitListPage />);

    await waitFor(() => expect(screen.getByTestId("kit-empty")).toBeTruthy());
    const empty = screen.getByTestId("kit-empty") as HTMLAnchorElement;
    expect(empty.getAttribute("href")).toBe("/brand/ingest");
  });
});

describe("BrandKitDetailPage", () => {
  function stubDetail(payload: unknown, onApproval?: () => void) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/approval") && init?.method === "POST") {
        onApproval?.();
        return new Response(JSON.stringify(detailPayload({ approved: true })), { status: 200 });
      }
      return new Response(JSON.stringify(payload), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("renders the section content from the detail payload", async () => {
    stubDetail(detailPayload());

    render(<BrandKitDetailPage />);

    // Identity name carries the terminal period.
    await waitFor(() => expect(screen.getByText("Insight Health.")).toBeTruthy());
    // Colors: hex value in mono somewhere.
    expect(screen.getAllByText("#F5F5F5").length).toBeGreaterThan(0);
    // Typography ramp role.
    expect(screen.getByText("display")).toBeTruthy();
    // Voice rule text.
    expect(screen.getByText("Maintain clearspace of 16px around the logo.")).toBeTruthy();
    // Ingestion role-assignment token.
    expect(screen.getByText("text.secondary")).toBeTruthy();
  });

  it("shows the synthesized dark-colorway pill", async () => {
    stubDetail(detailPayload());

    render(<BrandKitDetailPage />);

    await waitFor(() => expect(screen.getByText("Insight Health.")).toBeTruthy());
    expect(screen.getByText("synthesized")).toBeTruthy();
  });

  it("renders the font availability warning when faces are empty", async () => {
    stubDetail(detailPayload({ noFaces: true }));

    render(<BrandKitDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Font files not sourced — upload or pick an alternative")
      ).toBeTruthy()
    );
    expect(screen.getByText("Inter")).toBeTruthy();
  });

  it("choosing a logo from the library POSTs the selection and reloads the kit", async () => {
    let logoPost: { url: string; body: unknown } | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/logo") && init?.method === "POST") {
        logoPost = { url, body: JSON.parse(String(init.body)) };
        return new Response(JSON.stringify({ brand_kit: listSummary({ version: 2 }) }), {
          status: 200
        });
      }
      if (url.includes("/assets?") || url.endsWith("/assets")) {
        return new Response(
          JSON.stringify({
            assets: [
              {
                id: "asset_real_lockup",
                kind: "logo",
                label: "Real lockup",
                status: "active",
                media: {}
              }
            ]
          }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify(detailPayload()), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrandKitDetailPage />);

    await waitFor(() =>
      expect(screen.getByTestId("choose-logo-primary")).toBeTruthy()
    );
    fireEvent.click(screen.getByTestId("choose-logo-primary"));

    await waitFor(() => expect(screen.getByTestId("pick-asset_real_lockup")).toBeTruthy());
    fireEvent.click(screen.getByTestId("pick-asset_real_lockup"));

    await waitFor(() => expect(logoPost).not.toBeNull());
    expect(logoPost!.url).toContain("/brand-kits/kit_insight/logo");
    expect(logoPost!.body).toEqual({ asset_id: "asset_real_lockup", slot: "primary" });
    // Picker closes after the reload lands.
    await waitFor(() => expect(screen.queryByTestId("logo-picker")).toBeNull());
  });

  it("approving issues a POST and flips the pill to approved", async () => {
    let approvalCalled = false;
    stubDetail(detailPayload(), () => {
      approvalCalled = true;
    });

    render(<BrandKitDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(approvalCalled).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "Revert to draft" })).toBeTruthy());
    expect(screen.getByText("Approved")).toBeTruthy();
  });
});
