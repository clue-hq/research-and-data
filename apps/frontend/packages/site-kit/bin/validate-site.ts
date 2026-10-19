// The validator as a CLI, for the design API and the site agent's harness.
//
// Usage: node dist/validate-site.mjs < input.json   (in development: npx tsx bin/validate-site.ts)
// Reads {"files": {"pages": {route: page}, "shell": shell | null}, "brand": BrandData,
//        "agentSectionSchemas": {"<Name>": <the section's STORED props JSON Schema>},
//        "images": {"siteImages": [...], "accountLogos": [...]}} from stdin.
// Each agent section is checked against its stored JSON Schema, rebuilt with zod's fromJSONSchema.
// This CLI never imports a section's module: agent code runs only inside the design API's hardened
// render page (D2). Prints {"valid": bool, "errors": ["where: message", ...]} as JSON.
import { z } from "zod";
import type { BrandData } from "../src/brand";
import { validateSite, type AgentSectionSchemas, type SiteFiles, type SiteImages } from "../src/validate";

type Input = {
  files: SiteFiles;
  brand: BrandData;
  agentSectionSchemas?: Record<string, unknown>;
  images?: Partial<SiteImages>;
};

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as Input;

const agentSections: AgentSectionSchemas = {};
const schemaErrors: string[] = [];
for (const [name, jsonSchema] of Object.entries(input.agentSectionSchemas ?? {})) {
  try {
    agentSections[name] = { schema: z.fromJSONSchema(jsonSchema as Parameters<typeof z.fromJSONSchema>[0]), propsSchema: jsonSchema };
  } catch (error) {
    schemaErrors.push(`agent_sections.${name}: its stored props schema could not be read (${(error as Error).message})`);
  }
}

const result = validateSite(input.files, input.brand, agentSections, {
  siteImages: input.images?.siteImages ?? [],
  accountLogos: input.images?.accountLogos ?? [],
});
const errors = [...schemaErrors, ...result.errors];
console.log(JSON.stringify({ valid: errors.length === 0, errors }));
