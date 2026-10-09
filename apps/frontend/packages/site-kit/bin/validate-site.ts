// The validator as a CLI, for the agent harness.
//
// Usage: tsx bin/validate-site.ts < input.json
// Reads {"files": {"pages": {route: page}, "shell": shell | null}, "brand": BrandData,
//        "agentSectionModules": {"<Name>": "<absolute path to a compiled .mjs or a .tsx module>"}}
// from stdin. Each agent section module is imported for its zod `schema` (zod schemas cannot
// travel as JSON). Prints {"valid": bool, "errors": ["where: message", ...]} as JSON.
import { pathToFileURL } from "node:url";
import type { AgentSectionModule } from "../src/agent-kit";
import type { BrandData } from "../src/brand";
import { validateSite, type SiteFiles } from "../src/validate";

type Input = { files: SiteFiles; brand: BrandData; agentSectionModules?: Record<string, string> };

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as Input;

const agentSections: Record<string, AgentSectionModule> = {};
for (const [name, file] of Object.entries(input.agentSectionModules ?? {})) {
  agentSections[name] = (await import(pathToFileURL(file).href)) as AgentSectionModule;
}

console.log(JSON.stringify(validateSite(input.files, input.brand, agentSections)));
