// The catalog as a CLI, for the site agent's harness.
//
// Usage: node dist/build-catalog.mjs < input.json   (in development: npx tsx bin/build-catalog.ts)
// Reads {"brand": BrandData, "seller": "<the seller's name>"} from stdin and prints
// {"files": {"<relative path>": "<markdown>"}}: catalog/index.md, catalog/clones/<id>.md,
// catalog/sections.md and brand/brand.md. The caller writes them where the agent reads them.
import type { BrandData } from "../src/brand";
import { buildCatalog } from "../src/catalog";

type Input = { brand: BrandData; seller: string };

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as Input;
console.log(JSON.stringify({ files: buildCatalog(input.brand, input.seller) }));
