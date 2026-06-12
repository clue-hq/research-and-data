import { describe, expect, it } from "vitest";

import parityFixture from "../../../../../fixtures/edit-parity/cases.json";
import minimalScene from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Scene } from "../contracts";
import {
  deleteEdit,
  modifyNodeEdit,
  modifyNodeStacksEdit,
  modifyPageNameEdit,
  optimisticOperations,
  type StructuredEdit
} from "../structuredEdits";

/**
 * Cross-language parity: these are the same pinned cases the Rust side
 * asserts in crates/lumen-api-helper/tests/edit_parity.rs. The TS wrapper
 * must emit the identical wire format, and the optimistic operations must
 * equal the canonical operations the Rust builders produce.
 */

type ParityCase = {
  name: string;
  edit: StructuredEdit;
  expected_operations: unknown[];
};

const cases = (parityFixture as { cases: ParityCase[] }).cases;
const scene = minimalScene as unknown as Scene;

function builderFor(name: string): StructuredEdit {
  switch (name) {
    case "modify_node_text_and_font_size":
      return modifyNodeEdit("node_contact_name", {
        text: { content: "Parity headline", font_size: 18.0 }
      });
    case "modify_page_name":
      return modifyPageNameEdit("page_a4", "Renamed page");
    case "safe_delete_node":
      return deleteEdit({ kind: "node", id: "node_contact_name" });
    case "modify_node_add_drop_shadow_entry":
      return modifyNodeStacksEdit("node_contact_name", {
        effectEdits: [
          {
            kind: "add",
            entry: {
              id: "shadow_soft",
              kind: {
                kind: "drop_shadow",
                color: { kind: "hex", value: "#000000" },
                opacity: 0.18,
                x: 0.0,
                y: 8.0,
                blur: 24.0,
                spread: 0.0
              }
            }
          }
        ]
      });
    default:
      throw new Error(`no TS builder mapped for parity case ${name}`);
  }
}

describe("edit parity with the Rust builders", () => {
  it("covers every pinned parity case", () => {
    expect(cases.length).toBeGreaterThan(0);
    for (const parityCase of cases) {
      expect(() => builderFor(parityCase.name)).not.toThrow();
    }
  });

  it.each(cases.map((parityCase) => [parityCase.name, parityCase] as const))(
    "emits the pinned wire format for %s",
    (_name, parityCase) => {
      expect(builderFor(parityCase.name)).toEqual(parityCase.edit);
    }
  );

  it.each(cases.map((parityCase) => [parityCase.name, parityCase] as const))(
    "optimistic operations match the canonical Rust operations for %s",
    (_name, parityCase) => {
      const operations = optimisticOperations(scene, parityCase.edit);
      expect(operations).toEqual(parityCase.expected_operations);
    }
  );
});
