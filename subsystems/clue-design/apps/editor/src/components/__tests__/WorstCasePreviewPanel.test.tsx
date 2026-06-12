import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import mailerRevision from "../../../../../crates/lumen-core/fixtures/conformance/phase_g_mailer_revision.json";
import type { Scene } from "../../engine/contracts";
import { WorstCasePreviewPanel } from "../WorstCasePreviewPanel";

const scene = mailerRevision as unknown as Scene;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorstCasePreviewPanel", () => {
  it("derives the worst-case binding set and renders the result read-only", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "failed",
        fit_report: {
          status: "overflow",
          slots: [
            {
              slot_key: "contact.full_name",
              verdict: {
                kind: "overflow",
                policy: "shrink_font",
                reason: "content does not fit even at min font size 6"
              },
              beyond_worst_case: false
            },
            {
              slot_key: "campaign.cta",
              verdict: { kind: "fits" },
              beyond_worst_case: false
            }
          ]
        },
        diagnostics: [],
        artifact: null
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<WorstCasePreviewPanel apiBaseUrl="http://localhost:8000" scene={scene} />);
    fireEvent.click(screen.getByRole("button", { name: /render worst case/i }));

    await waitFor(() => {
      expect(screen.getByTestId("worst-case-fit-status")).toHaveTextContent("overflow");
    });
    expect(screen.getByText(/instance would fail/)).toBeInTheDocument();
    expect(screen.getByText("contact.full_name")).toBeInTheDocument();
    expect(screen.getByText(/min font size 6/)).toBeInTheDocument();
    // Fitting slots are not listed as issues.
    expect(screen.queryByText("campaign.cta")).not.toBeInTheDocument();

    // The request carried the worst-case binding set built from the scene.
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.binding_set.values["contact.full_name"].value).toBe(
      "Dr. Maximilian Whitmore-Kensington"
    );
  });

  it("renders the returned SVG artifact when every slot fits", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: "ok",
          fit_report: { status: "fits", slots: [] },
          diagnostics: [],
          artifact: {
            format: "svg",
            content: '<svg data-testid="derived-svg"></svg>'
          }
        })
      })
    );

    render(<WorstCasePreviewPanel apiBaseUrl="http://localhost:8000" scene={scene} />);
    fireEvent.click(screen.getByRole("button", { name: /render worst case/i }));

    await waitFor(() => {
      expect(screen.getByTestId("worst-case-render")).toBeInTheDocument();
    });
    expect(screen.getByText(/every slot fits/i)).toBeInTheDocument();
  });

  it("surfaces preview failures without crashing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: { code: "instance.binding_invalid" } })
      })
    );

    render(<WorstCasePreviewPanel apiBaseUrl="http://localhost:8000" scene={scene} />);
    fireEvent.click(screen.getByRole("button", { name: /render worst case/i }));

    await waitFor(() => {
      expect(screen.getByText(/422/)).toBeInTheDocument();
    });
  });
});
