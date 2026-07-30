import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";

import { compileComponent } from "../src/compiler.mjs";

function request(source, overrides = {}) {
  return {
    protocol_version: 1,
    slug: "pricing-card",
    entry: "pricing-card.tsx",
    files: { "pricing-card.tsx": source },
    component_artifacts: {},
    ...overrides,
  };
}

function codes(result) {
  return result.diagnostics.map((item) => item.code);
}

const VALID_SOURCE = `
import React from "react";

type Props = {
  headline?: string;
  accent?: "blue" | "green";
  planCount?: number;
  showBadge?: boolean;
  tags?: string[];
};

export const meta = {
  name: "Pricing Card",
  description: "A compact pricing callout."
};

export default function PricingCard({
  props: {
    headline = "Pricing",
    accent = "blue",
    planCount = 3,
    showBadge = true
  },
  theme
}: {
  props: Props;
  theme: { colors: { primary: string } };
  overrideVariables?: Record<string, string>;
}) {
  return (
    <section className={accent === "blue" ? "rounded-xl bg-primary p-6" : "rounded-xl bg-secondary p-6"}>
      <h2 className="font-heading text-2xl">{headline}</h2>
      <p>{planCount} plans</p>
      {showBadge ? <span className="font-body">Popular</span> : null}
      <i>{theme.colors.primary}</i>
    </section>
  );
}
`;

test("extracts metadata, supported props, defaults, Tailwind, and a first frame", async () => {
  const result = await compileComponent(request(VALID_SOURCE));
  assert.equal(result.status, "success", JSON.stringify(result.diagnostics));
  assert.deepEqual(result.manifest.meta, {
    name: "Pricing Card",
    description: "A compact pricing callout.",
  });
  assert.deepEqual(result.manifest.defaults, {
    accent: "blue",
    headline: "Pricing",
    planCount: 3,
    showBadge: true,
  });
  assert.deepEqual(result.manifest.props_schema.properties.accent.enum, [
    "blue",
    "green",
  ]);
  assert.equal(result.manifest.curated_package_versions.motion, "12.23.12");
  assert.equal(result.manifest.toolchain_package_versions.postcss, "8.5.25");
  assert.equal(result.manifest.props_schema.properties.planCount.type, "number");
  assert.ok(codes(result).includes("CCW0203"));
  assert.match(result.outputs.component_css, /\.bg-primary/);
  assert.match(result.outputs.first_frame_html, />Pricing</);
  assert.match(result.outputs.first_frame_html, />3 plans</);
  assert.ok(result.outputs.browser_bundle.length > 100);
});

test("curated Visx, Motion, GSAP, and relative-helper imports compile", async () => {
  const source = `
import React, { useRef } from "react";
import { LinePath } from "@visx/shape";
import { curveMonotoneX } from "@visx/curve";
import { Group } from "@visx/group";
import { scaleLinear } from "@visx/scale";
import { motion } from "motion/react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { points } from "./lib/points";

export default function Chart() {
  const ref = useRef<HTMLDivElement>(null);
  const x = scaleLinear({ domain: [0, 1], range: [0, 100] });
  useGSAP(() => { if (ref.current) gsap.to(ref.current, { opacity: 1 }); }, { scope: ref });
  return (
    <motion.div ref={ref} initial={false} animate={{ opacity: 1 }} className="p-4">
      <svg viewBox="0 0 120 60">
        <Group left={10} top={10}>
          <LinePath data={points} x={(d: { x: number; y: number }) => x(d.x)} y={(d: { x: number; y: number }) => d.y} curve={curveMonotoneX} />
        </Group>
      </svg>
    </motion.div>
  );
}
`;
  const result = await compileComponent(
    request(source, {
      files: {
        "pricing-card.tsx": source,
        "lib/points.ts": "export const points = [{ x: 0, y: 10 }, { x: 1, y: 40 }];",
      },
    }),
  );
  assert.equal(result.status, "success", JSON.stringify(result.diagnostics));
  assert.match(result.outputs.first_frame_html, /<svg/);
});

test("pins account-resolved cross-component dependencies", async () => {
  const artifact = `ccart_${"a".repeat(64)}`;
  const result = await compileComponent(
    request(`
      import React from "react";
      import Badge from "components/status-badge";
      export default function Parent() { return <main><Badge /></main>; }
    `, {
      component_artifacts: { "status-badge": artifact },
    }),
  );
  assert.equal(result.status, "success", JSON.stringify(result.diagnostics));
  assert.deepEqual(result.manifest.dependency_artifacts, {
    "status-badge": artifact,
  });
  assert.match(result.outputs.browser_bundle, /components\/status-badge/);
  assert.match(result.outputs.first_frame_html, /data-artifact-id/);
});

test("forbidden syntax and imports fail with stable diagnostics", async (t) => {
  const cases = [
    ["eval", `export default function C(){ eval("1"); return <div />; }`, "CCC0111"],
    ["Function", `export default function C(){ new Function("return 1"); return <div />; }`, "CCC0113"],
    ["Function call", `export default function C(){ Function("return 1")(); return <div />; }`, "CCC0113"],
    ["dynamic import", `export default async function C(){ await import("./helper"); return <div />; }`, "CCC0110"],
    ["document.write", `export default function C(){ document.write("x"); return <div />; }`, "CCC0114"],
    ["script element", `export default function C(){ return <script>bad()</script>; }`, "CCC0115"],
    ["raw HTML", `export default function C(){ return <div dangerouslySetInnerHTML={{__html:"<script />"}} />; }`, "CCC0116"],
    ["require", `export default function C(){ require("react"); return <div />; }`, "CCC0112"],
    ["bare package", `import thing from "lodash"; export default function C(){ return <div>{thing}</div>; }`, "CCC0106"],
    ["css import", `import "./styles.css"; export default function C(){ return <div />; }`, "CCC0101"],
    ["missing default", `export function C(){ return <div />; }`, "CCC0301"],
    ["missing component", `import X from "components/missing"; export default function C(){ return <X />; }`, "CCC0105"],
    ["dynamic class", `export default function C({tone}:{tone:string}){ return <div className={"bg-" + tone} />; }`, "CCC0120"],
  ];
  for (const [name, source, expected] of cases) {
    await t.test(name, async () => {
      const result = await compileComponent(request(source));
      assert.equal(result.status, "failed");
      assert.ok(codes(result).includes(expected), JSON.stringify(result.diagnostics));
    });
  }
});

test("escaping and missing helper imports fail before bundling", async () => {
  const escape = await compileComponent(
    request(`import x from "../escape"; export default function C(){ return <div>{x}</div>; }`),
  );
  assert.equal(escape.status, "failed");
  assert.ok(codes(escape).includes("CCC0102"));

  const missing = await compileComponent(
    request(`import x from "./missing"; export default function C(){ return <div>{x}</div>; }`),
  );
  assert.equal(missing.status, "failed");
  assert.ok(codes(missing).includes("CCC0103"));
});

test("a contained helper may provide the entry's default export", async () => {
  const result = await compileComponent(
    request(`export { default } from "./lib/component";`, {
      files: {
        "pricing-card.tsx": `export { default } from "./lib/component";`,
        "lib/component.tsx": `
          import React from "react";
          export default function Component(){ return <aside>Contained</aside>; }
        `,
      },
    }),
  );
  assert.equal(result.status, "success", JSON.stringify(result.diagnostics));
  assert.match(result.outputs.first_frame_html, /Contained/);
});

test("TypeScript errors are deterministic authoring failures", async () => {
  const result = await compileComponent(
    request(`import React from "react"; export default function C(){ const value: string = 3; return <div>{value}</div>; }`),
  );
  assert.equal(result.status, "failed");
  assert.ok(codes(result).includes("TS2322"), JSON.stringify(result.diagnostics));
});

test("render smoke timeout is a deterministic failure", async () => {
  const result = await compileComponent(
    request(`import React from "react"; while (true) {} export default function C(){ return <div />; }`),
  );
  assert.equal(result.status, "failed");
  assert.ok(codes(result).includes("CCC0502"), JSON.stringify(result.diagnostics));
});

test("the first-frame VM exposes no ambient network capability", async () => {
  const result = await compileComponent(
    request(`
      import React from "react";
      const request = fetch("https://example.com");
      export default function C(){ return <div>{String(request)}</div>; }
    `),
  );
  assert.equal(result.status, "failed");
  assert.ok(codes(result).includes("CCC0502"), JSON.stringify(result.diagnostics));
});

test("identical inputs produce byte-identical output digests", async () => {
  const first = await compileComponent(request(VALID_SOURCE));
  const second = await compileComponent(request(VALID_SOURCE));
  assert.equal(first.status, "success");
  assert.equal(second.status, "success");
  assert.deepEqual(first.digests, second.digests);
  for (const key of [
    "browser_bundle",
    "component_css",
    "first_frame_html",
  ]) {
    assert.equal(
      crypto.createHash("sha256").update(first.outputs[key]).digest("hex"),
      crypto.createHash("sha256").update(second.outputs[key]).digest("hex"),
    );
  }
});

test("first-frame time and randomness are deterministic", async () => {
  const input = request(`
    import React from "react";
    export default function Deterministic() {
      return <output>{Date.now()}:{Math.random()}:{new Date().toISOString()}</output>;
    }
  `);
  const first = await compileComponent(input);
  const second = await compileComponent(input);
  assert.equal(first.status, "success", JSON.stringify(first.diagnostics));
  assert.equal(second.status, "success", JSON.stringify(second.diagnostics));
  assert.equal(first.outputs.first_frame_html, second.outputs.first_frame_html);
  assert.match(
    first.outputs.first_frame_html,
    /0:0\.5:1970-01-01T00:00:00\.000Z/,
  );
});
