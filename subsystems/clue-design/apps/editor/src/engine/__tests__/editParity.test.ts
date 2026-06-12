import { describe, expect, it } from "vitest";

import parityFixture from "../../../../../fixtures/edit-parity/cases.json";
import {
  deleteEdit,
  modifyNodeEdit,
  modifyNodeStacksEdit,
  modifyPageNameEdit,
  type StructuredEdit
} from "../structuredEdits";

/**
 * W4 smoke contract: with the TS optimistic mirror retired, the same
 * engine (lumen-core) runs on both sides of the boundary, so byte parity
 * of operation application is tautological. What still needs pinning is
 * the WIRE FORMAT: the TS builders must emit exactly the JSON the Rust
 * `StructuredEditInstruction` deserializes.
 *
 * The full application-parity assertions live where the engines run:
 * - crates/lumen-api-helper/tests/edit_parity.rs (server helper)
 * - crates/lumen-api-helper/tests/wasm_helper_parity.rs (wasm vs helper)
 * - apps/editor/src/engine/__tests__/wasmEngine.test.ts (wasm engine)
 */

type ParityCase = {
  name: string;
  edit: StructuredEdit;
  expected_operations: unknown[];
};

const cases = (parityFixture as { cases: ParityCase[] }).cases;

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
    case "modify_node_add_dashed_stroke_entry":
      return modifyNodeStacksEdit("node_contact_name", {
        strokeEdits: [
          {
            kind: "add",
            entry: {
              id: "stroke_border",
              paint: { kind: "solid", color: { kind: "hex", value: "#111827" } },
              width: 1.0,
              dash: [6.0, 4.0],
              cap: "round",
              join: "round"
            }
          }
        ]
      });
    default:
      throw new Error(`no TS builder mapped for parity case ${name}`);
  }
}

describe("structured-edit wire-format smoke (vs pinned parity fixture)", () => {
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
});
