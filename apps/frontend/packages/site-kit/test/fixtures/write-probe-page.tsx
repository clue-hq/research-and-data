// The design API's state-CSS fixture (Wave 2 A9, Task 16b): a page site-kit draws from the probe kit
// (its theme, a measured button look with its icon, and a measured reveal below the fold).
// Run: cd apps/frontend/packages/site-kit && npx tsx test/fixtures/write-probe-page.tsx
import fs from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { colorOf } from "../../src/brand-values";
import { buttonLooks, motionEntries } from "../../src/looks";
import { Button } from "../../src/sections";
import { themeCss } from "../../src/theme";
import { kitBrand } from "./kits";

export const PROBE_PAGE = new URL("../../../../../../subsystems/clue-design/apps/api/tests/fixtures/site/probe_page.html", import.meta.url);

export function probePage(): string {
  const brand = kitBrand("probe.minted");
  const solid = buttonLooks(brand).find((look) => colorOf(brand, look.measured?.rest.fill) === "#047464")!;
  const reveal = motionEntries(brand).find((entry) => entry.kind === "reveal")!;
  const body = renderToStaticMarkup(
    <div className="brand-root">
      <style dangerouslySetInnerHTML={{ __html: themeCss(brand) }} />
      <section className="bg-surface-page text-on-surface-page">
        <Button brand={brand} label="Request the analysis" href="/analysis" surface="page" look={solid.name} />
      </section>
      <div data-test="spacer" />
      <div data-test="reveal" className={reveal.className}>Revealed</div>
    </div>,
  );
  // The fixture's own layout (a tall spacer, a coloured box) is test scaffolding, not site-kit's.
  return `<!doctype html><html><head><meta charset="utf-8"><title>probe</title><style>[data-test=spacer]{height:2400px}[data-test=reveal]{height:200px;background:#014036}</style></head><body>${body}</body></html>\n`;
}

if (process.argv[1]?.endsWith("write-probe-page.tsx")) fs.writeFileSync(PROBE_PAGE, probePage());
