"use client";

// D2 spike (Task 4): import each agent section at runtime and add it to the config makeConfig
// builds, with fields derived from the section's own zod schema, then render <Puck>.
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zod from "zod";
import { useEffect, useState } from "react";
import { Puck, type Config, type Data, type Field, type Fields, type Viewports } from "@puckeditor/core";
import type { BrandData } from "@/lib/brands";
import { makeKit, type Kit } from "@/puck/agent-kit";
import { AssetPicker } from "@/puck/asset-picker";
import { CloneEditor } from "@/puck/clone-editor";
import { makeConfig, type ConfigOptions } from "@/puck/config";

const VIEWPORTS: Viewports = [
  { width: 375, height: "auto", label: "Phone" },
  { width: 768, height: "auto", label: "Tablet" },
  { width: 1440, height: "auto", label: "Desktop" },
];

type SectionModule = { schema: zod.ZodObject; render: (props: unknown, kit: Kit) => React.ReactNode };
type JsonSchema = {
  type?: string;
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
};

declare global {
  var __clueSectionHost: Record<string, unknown> | undefined;
  /** Load facts for the spike's measurements (read by the Playwright probe). */
  var __runtimeSections: { importMs: number; perModuleMs: Record<string, number>; names: string[]; skipped: string[] } | undefined;
  var __runtimeData: Data | undefined;
}

const NOT_INLINE = /href|image|src|logo|url/i;
const LONG_TEXT = /body|intro|statement|description|quote/i;

/** Puck fields from a section's props schema (zod's JSON Schema). Text edits in place. */
export function fieldsFrom(schema: JsonSchema, brand: BrandData, skipped: string[], at = ""): Fields {
  const fields: Record<string, Field> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (key === "id") continue;
    const where = at ? `${at}.${key}` : key;
    if (prop.enum) fields[key] = { type: "select", options: prop.enum.map((v) => ({ label: String(v), value: v as string })) };
    else if (prop.type === "string" && /image|logo/i.test(key))
      fields[key] = {
        type: "custom",
        label: key,
        render: ({ value, onChange }) => <AssetPicker assets={brand.assets} value={value ?? ""} onChange={onChange} />,
      };
    else if (prop.type === "string")
      fields[key] = { type: LONG_TEXT.test(key) ? "textarea" : "text", contentEditable: !NOT_INLINE.test(key) };
    else if (prop.type === "boolean")
      fields[key] = { type: "radio", options: [{ label: "Yes", value: true }, { label: "No", value: false }] };
    else if (prop.type === "number" || prop.type === "integer") fields[key] = { type: "number" };
    else if (prop.type === "array" && prop.items?.type === "object")
      fields[key] = {
        type: "array",
        arrayFields: fieldsFrom(prop.items, brand, skipped, `${where}[]`),
        getItemSummary: (item: Record<string, unknown>) =>
          String(Object.values(item ?? {}).find((v) => typeof v === "string" && v && !v.startsWith("/")) ?? key),
      };
    else if (prop.type === "object") fields[key] = { type: "object", objectFields: fieldsFrom(prop, brand, skipped, where) };
    else skipped.push(where);
  }
  return fields as Fields;
}

export function RuntimeEditor({
  workspace,
  sections,
  data,
  brand,
  options,
}: {
  workspace: string;
  sections: Record<string, string>;
  data: Data;
  brand: BrandData;
  options: ConfigOptions;
}) {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    globalThis.__clueSectionHost = { react: React, "react/jsx-runtime": jsxRuntime, zod };
    const started = performance.now();
    const perModuleMs: Record<string, number> = {};
    Promise.all(
      Object.entries(sections).map(async ([name, digest]) => {
        const t = performance.now();
        const url = `/compiled/${workspace}/${digest}.mjs`;
        const module = (await import(/* webpackIgnore: true */ /* turbopackIgnore: true */ url)) as SectionModule;
        perModuleMs[name] = Math.round(performance.now() - t);
        return [name, digest, module] as const;
      }),
    )
      .then((loaded) => {
        const href = (value: string) =>
          value && value.startsWith("/") && !value.startsWith("//")
            ? `${options.basePath}${value === "/" ? "" : value}`
            : value;
        const kit = makeKit(href);
        const base = makeConfig(brand, { ...options, editor: { CloneEditor, AssetPicker } }) as Config & {
          components: Record<string, unknown>;
          categories: Record<string, unknown>;
        };
        const skipped: string[] = [];
        for (const [name, digest, module] of loaded) {
          const propsSchema = zod.z.toJSONSchema(module.schema) as JsonSchema;
          base.components[name] = {
            label: `${name} (agent, runtime)`,
            fields: fieldsFrom(propsSchema, brand, skipped, name),
            render: (props: unknown) => (
              <div data-agent-section={name} data-runtime-digest={digest}>
                {module.render(props, kit)}
              </div>
            ),
          };
        }
        base.categories.agent = { title: "Agent sections (runtime)", components: loaded.map(([name]) => name) };
        globalThis.__runtimeSections = {
          importMs: Math.round(performance.now() - started),
          perModuleMs,
          names: loaded.map(([name]) => name),
          skipped,
        };
        setConfig(base);
      })
      .catch((reason: unknown) => setError(String(reason instanceof Error ? reason.stack ?? reason.message : reason)));
  }, [workspace, sections, brand, options]);

  if (error) return <pre data-runtime-error="true">{error}</pre>;
  if (!config) return <p data-runtime-loading="true">Loading this site’s sections…</p>;
  return (
    <Puck
      config={config}
      data={data}
      viewports={VIEWPORTS}
      ui={{ viewports: { current: { width: 1440, height: "auto" }, controlsVisible: true, options: VIEWPORTS } }}
      onChange={(next) => {
        globalThis.__runtimeData = next;
      }}
    />
  );
}
