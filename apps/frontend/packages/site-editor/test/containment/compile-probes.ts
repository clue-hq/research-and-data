// Compiles the D2 spike's hostile and evasion probes (and ApiRead) the way Lane B6 compiles an agent
// section — esbuild ESM, automatic JSX, react / react/jsx-runtime / zod external — and NEVER imports
// the result (plan Global Constraints: Node only transforms agent code). Prints {name: {digest, file}}.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../../..");
const HOSTILE = path.join(REPO, "trials/puck-spike/scripts/hostile");
const PROBES: Record<string, string> = {
  ApiRead: path.join(REPO, "apps/frontend/packages/site-editor/test/containment/probes/ApiRead.tsx"),
  ConstructorEscape: path.join(HOSTILE, "evasion/ConstructorEscape.tsx"),
  CookieRead: path.join(HOSTILE, "CookieRead.tsx"),
  InjectedScript: path.join(HOSTILE, "InjectedScript.tsx"),
  NetworkCall: path.join(HOSTILE, "NetworkCall.tsx"),
  ParentFrame: path.join(HOSTILE, "ParentFrame.tsx"),
  TopFrame: path.join(HOSTILE, "evasion/TopFrame.tsx"),
  TrackingPixel: path.join(HOSTILE, "evasion/TrackingPixel.tsx"),
};

const out = process.argv[2];
if (!out) throw new Error("usage: tsx compile-probes.ts <output directory>");
await fs.mkdir(out, { recursive: true });
const compiled: Record<string, { digest: string; file: string }> = {};
for (const [name, entry] of Object.entries(PROBES)) {
  const result = await build({
    bundle: true,
    entryPoints: [entry],
    external: ["react", "react/jsx-runtime", "zod"],
    format: "esm",
    jsx: "automatic",
    logLevel: "error",
    platform: "browser",
    write: false,
  });
  const code = result.outputFiles[0].text;
  const digest = createHash("sha256").update(code).digest("hex");
  const file = path.join(out, `${digest}.mjs`);
  await fs.writeFile(file, code);
  compiled[name] = { digest, file };
}
process.stdout.write(JSON.stringify(compiled));
