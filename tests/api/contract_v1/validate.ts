/**
 * The Zod oracle for contract v1 (ARV2 D3, task 1; re-pointed at the monorepo models in D4 task 3).
 *
 * The five schema files it imports ARE the frontend's own accounts models
 * (`apps/frontend/src/features/accounts/model/`). They were vendored under `./zod/` while the
 * frontend still lived in the dummy repo; the D4 re-lift landed them in `apps/frontend`, so the
 * oracle now reads the shipped models directly and there is exactly one copy of contract v1's
 * presentation truth. Each D0/D3 amendment is still marked in place with a
 * `// D0 ruling Rn/Sn` or `// D3 ruling` comment.
 *
 * Two CLI modes, both driven from `tests/api/contract_v1/test_contract_v1.py`:
 *
 *   tsx validate.ts --shapes
 *       Prints stable JSON — `{schemaName: {required: [...], optional: [...]}}` for the five
 *       payload schemas, keys and arrays sorted — which is committed as `zod-fields.json`.
 *       A key is `optional` when it accepts `undefined`: `.optional()`, `.nullish()`, or a
 *       `.default(...)`. A bare `.nullable()` is REQUIRED-but-nullable and stays in `required`.
 *
 *   tsx validate.ts --enums
 *       Prints stable JSON — `{"<Schema>.<path>": [values...]}` — for every field, at any depth,
 *       whose allowed values are a fixed list (a `z.enum`, a `z.literal` or a union of them). A
 *       nested object field's path is `parent.child`; an array's element is `parent[]`. The test
 *       checks that every value the backend may send at that path is one this list accepts (review
 *       finding K1-1: `"site"` was added to the backend's artifact types and not here, and the whole
 *       accounts read failed; `--shapes` compares field names only, and only at the top level).
 *
 *   tsx validate.ts <payload.json> <SchemaName>
 *       Parses the file with the named schema. Exit 0 on success; exit 1 with the Zod error
 *       on stderr otherwise.
 *
 * `zod` is resolved from `apps/frontend/node_modules` — see `README.md` for the exact incantation.
 */
import { readFileSync } from "node:fs";

import { AccountSchema } from "../../../apps/frontend/src/features/accounts/model/account";
import { AccountDetailSchema } from "../../../apps/frontend/src/features/accounts/model/account-detail";
import { AccountWorkspaceSchema } from "../../../apps/frontend/src/features/accounts/model/account-workspace";
import {
  AccountContactDetailSchema,
  AccountContactSummarySchema,
} from "../../../apps/frontend/src/features/accounts/model/account-contact";

const SCHEMAS: Record<string, { shape: Record<string, unknown> }> = {
  AccountSchema,
  AccountDetailSchema,
  AccountWorkspaceSchema,
  AccountContactSummarySchema,
  AccountContactDetailSchema,
};

/** True when the field accepts `undefined`: optional, nullish, or defaulted. */
function acceptsUndefined(field: unknown): boolean {
  const def = (field as { _zod?: { def?: { type?: string; innerType?: unknown } } })
    ?._zod?.def;
  if (!def || typeof def.type !== "string") {
    return false;
  }
  if (def.type === "optional" || def.type === "default" || def.type === "prefault") {
    return true;
  }
  // `.optional().nullable()` — a nullable wrapper only counts as optional when its inner
  // type is itself optional or defaulted.
  if (def.type === "nullable") {
    return acceptsUndefined(def.innerType);
  }
  return false;
}

function shapes(): string {
  const out: Record<string, { optional: string[]; required: string[] }> = {};
  for (const name of Object.keys(SCHEMAS).sort()) {
    const required: string[] = [];
    const optional: string[] = [];
    const shape = SCHEMAS[name].shape;
    for (const key of Object.keys(shape).sort()) {
      (acceptsUndefined(shape[key]) ? optional : required).push(key);
    }
    out[name] = { optional, required };
  }
  return `${JSON.stringify(out, null, 2)}\n`;
}

type ZodDef = {
  type?: string;
  shape?: Record<string, unknown>;
  element?: unknown;
  innerType?: unknown;
  entries?: Record<string, string | number>;
  values?: unknown[];
  options?: unknown[];
  in?: unknown;
  getter?: () => unknown;
};

function defOf(schema: unknown): ZodDef | undefined {
  return (schema as { _zod?: { def?: ZodDef } })?._zod?.def;
}

/** The fixed values a schema accepts, or null when it accepts more than a fixed list. */
function fixedValues(schema: unknown): unknown[] | null {
  const def = defOf(schema);
  if (!def) return null;
  switch (def.type) {
    case "enum":
      return Object.values(def.entries ?? {});
    case "literal":
      return [...(def.values ?? [])];
    case "optional":
    case "nullable":
    case "default":
    case "prefault":
    case "readonly":
      return fixedValues(def.innerType);
    case "union": {
      const all: unknown[] = [];
      for (const option of def.options ?? []) {
        const values = fixedValues(option);
        if (values === null) return null;
        all.push(...values);
      }
      return all;
    }
    default:
      return null;
  }
}

function walkEnums(schema: unknown, path: string, out: Record<string, unknown[]>, seen: Set<unknown>): void {
  const def = defOf(schema);
  if (!def || seen.has(schema)) return;
  const values = fixedValues(schema);
  if (values !== null) {
    out[path] = [...new Set(values)].sort((a, b) => String(a).localeCompare(String(b)));
    return;
  }
  seen.add(schema);
  switch (def.type) {
    case "object":
      for (const key of Object.keys(def.shape ?? {}).sort()) walkEnums(def.shape![key], `${path}.${key}`, out, seen);
      break;
    case "array":
      walkEnums(def.element, `${path}[]`, out, seen);
      break;
    case "optional":
    case "nullable":
    case "default":
    case "prefault":
    case "readonly":
      walkEnums(def.innerType, path, out, seen);
      break;
    case "union":
      for (const option of def.options ?? []) walkEnums(option, path, out, seen);
      break;
    case "pipe":
      walkEnums(def.in, path, out, seen);
      break;
    case "lazy":
      if (def.getter) walkEnums(def.getter(), path, out, seen);
      break;
  }
  seen.delete(schema);
}

function enums(): string {
  const out: Record<string, unknown[]> = {};
  for (const name of Object.keys(SCHEMAS).sort()) walkEnums(SCHEMAS[name], name, out, new Set());
  const sorted = Object.fromEntries(Object.keys(out).sort().map((key) => [key, out[key]]));
  return `${JSON.stringify(sorted, null, 2)}\n`;
}

function main(argv: string[]): number {
  if (argv.length === 1 && argv[0] === "--shapes") {
    process.stdout.write(shapes());
    return 0;
  }
  if (argv.length === 1 && argv[0] === "--enums") {
    process.stdout.write(enums());
    return 0;
  }
  if (argv.length !== 2) {
    process.stderr.write(
      "usage: validate.ts --shapes | validate.ts --enums | validate.ts <payload.json> <SchemaName>\n",
    );
    return 2;
  }
  const [payloadPath, schemaName] = argv;
  const schema = SCHEMAS[schemaName] as
    | { safeParse: (value: unknown) => { success: boolean; error?: unknown } }
    | undefined;
  if (schema === undefined) {
    process.stderr.write(
      `unknown schema ${schemaName}; known: ${Object.keys(SCHEMAS).sort().join(", ")}\n`,
    );
    return 2;
  }
  const parsed = schema.safeParse(JSON.parse(readFileSync(payloadPath, "utf8")));
  if (parsed.success) {
    return 0;
  }
  process.stderr.write(
    `${schemaName} rejected ${payloadPath}:\n${JSON.stringify(parsed.error, null, 2)}\n`,
  );
  return 1;
}

process.exit(main(process.argv.slice(2)));
