import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import { firstPageId, flattenPageNodeIds, slotByNode } from "../sceneQueries";

describe("scene queries", () => {
  it("finds the first page from the contract fixture", () => {
    expect(firstPageId(minimalScene)).toBe("page_a4");
  });

  it("flattens page node ids in render order", () => {
    expect(flattenPageNodeIds(minimalScene, "page_a4")).toEqual(["node_contact_name"]);
  });

  it("finds a slot bound to a selected node", () => {
    expect(slotByNode(minimalScene, "node_contact_name")?.key).toBe("contact.full_name");
  });
});
