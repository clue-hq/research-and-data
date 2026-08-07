import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HeuristicMeasurementBanner } from "../EditorChrome";

/**
 * The loud, always-on signal for degraded text measurement: when CanvasKit or
 * its fonts fail to load the wasm engine silently falls back to a heuristic
 * measurer (text can misfit or vanish). This banner is that failure made loud,
 * mirroring the EngineDisabledBanner alert affordance.
 */
describe("HeuristicMeasurementBanner", () => {
  it("renders an always-on alert naming the degradation and the fix", () => {
    render(<HeuristicMeasurementBanner />);
    const banner = screen.getByTestId("heuristic-measurement-banner");
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveTextContent(/Text measurement degraded/i);
    expect(banner).toHaveTextContent(/font engine unavailable/i);
    expect(banner).toHaveTextContent(/npm run build:canvaskit/);
    expect(banner).toHaveTextContent(/npm run build:fonts/);
  });
});
