import { describe, expect, it } from "vitest";

import {
  buildInsertNodeOp,
  buildWebButtonProps,
  classifyEmbedUrl,
  deriveInsertPlacement,
  duplicateSubtree,
  isWebButtonCommandProps,
  listDialogComponents,
  mint,
  moveSectionIndex,
  webNodeButtonAction,
  type WebDoc,
  type WebNode,
  type WebPageSummary
} from "../webDocuments";

function buttonNode(overrides: Partial<WebNode>): WebNode {
  return { id: "cta", kind: "button", classes: "", label: "Get started", variant: "primary", ...overrides };
}

describe("webNodeButtonAction", () => {
  it("reads the link form when no command is present", () => {
    expect(webNodeButtonAction(buttonNode({ href: "https://x.test" }))).toBe("link");
  });

  it("reads show_modal / close from the command form", () => {
    expect(webNodeButtonAction(buttonNode({ command: "show_modal", command_target: "d1" }))).toBe(
      "show_modal"
    );
    expect(webNodeButtonAction(buttonNode({ command: "close", command_target: "d1" }))).toBe(
      "close"
    );
  });

  it("falls back to link for an unknown command", () => {
    expect(webNodeButtonAction(buttonNode({ command: "bogus" }))).toBe("link");
  });
});

describe("buildWebButtonProps", () => {
  const common = {
    label: "Get started",
    variant: "secondary",
    href: "https://x.test",
    new_tab: true,
    command_target: "dialog-1"
  };

  it("builds the link form and preserves label + variant", () => {
    const props = buildWebButtonProps({ action: "link", ...common });
    expect(props).toEqual({
      kind: "button",
      label: "Get started",
      variant: "secondary",
      href: "https://x.test",
      new_tab: true
    });
    expect(isWebButtonCommandProps(props)).toBe(false);
  });

  it("builds the command form and preserves label + variant", () => {
    const open = buildWebButtonProps({ action: "show_modal", ...common });
    expect(open).toEqual({
      kind: "button",
      label: "Get started",
      variant: "secondary",
      command: "show_modal",
      command_target: "dialog-1"
    });
    expect(isWebButtonCommandProps(open)).toBe(true);

    const close = buildWebButtonProps({ action: "close", ...common });
    expect(close).toMatchObject({ command: "close", command_target: "dialog-1" });
  });

  it("round-trips link → command → link preserving label + variant", () => {
    const start = buttonNode({ href: "https://x.test", new_tab: false });
    const toCommand = buildWebButtonProps({
      action: "show_modal",
      label: start.label ?? "",
      variant: start.variant ?? "primary",
      href: start.href ?? "",
      new_tab: start.new_tab ?? false,
      command_target: "d9"
    });
    expect(toCommand).toMatchObject({ label: "Get started", variant: "primary" });

    const backToLink = buildWebButtonProps({
      action: "link",
      label: toCommand.label,
      variant: toCommand.variant,
      href: "https://x.test",
      new_tab: false,
      command_target: isWebButtonCommandProps(toCommand) ? toCommand.command_target : ""
    });
    expect(backToLink).toEqual({
      kind: "button",
      label: "Get started",
      variant: "primary",
      href: "https://x.test",
      new_tab: false
    });
  });
});

describe("listDialogComponents", () => {
  const doc: WebDoc = {
    pages: [
      {
        id: "home",
        name: "Home",
        route: "/",
        nodes: {
          hero: { id: "hero", kind: "section", classes: "" },
          d1: { id: "d1", kind: "component", classes: "", component: "dialog", name: "Signup" },
          acc: { id: "acc", kind: "component", classes: "", component: "accordion" },
          d2: { id: "d2", kind: "component", classes: "", component: "dialog" }
        }
      },
      {
        id: "about",
        name: "About",
        route: "/about",
        nodes: {
          d3: { id: "d3", kind: "component", classes: "", component: "dialog", name: "Contact" }
        }
      }
    ]
  };

  it("lists every dialog across pages, carrying the name when set", () => {
    const dialogs = listDialogComponents(doc);
    expect(dialogs).toEqual([
      { id: "d1", name: "Signup" },
      { id: "d2" },
      { id: "d3", name: "Contact" }
    ]);
  });

  it("returns an empty list for a null doc or one without dialogs", () => {
    expect(listDialogComponents(null)).toEqual([]);
    expect(
      listDialogComponents({
        pages: [{ id: "p", name: "P", route: "/", nodes: { t: { id: "t", kind: "text", classes: "" } } }]
      })
    ).toEqual([]);
  });
});

// ── structural editing ───────────────────────────────────────────────────────

/** A page: root → [secA, secB]; secA is a Section holding a Container `box`
 * whose single child is the leaf Text `t1`. */
function structuralPage(): WebPageSummary {
  return {
    id: "home",
    name: "Home",
    route: "/",
    root: "root",
    nodes: {
      root: { id: "root", kind: "container", classes: "", children: ["secA", "secB"] },
      secA: { id: "secA", kind: "section", classes: "", tag: "section", children: ["box"] },
      box: { id: "box", kind: "container", classes: "flex", children: ["t1"] },
      t1: { id: "t1", kind: "text", classes: "", variant: "body", content: "one" },
      secB: { id: "secB", kind: "section", classes: "", tag: "section", children: [] }
    }
  };
}

/** A deterministic hex generator — successive fixed 6-char suffixes. */
function seqGen(...values: string[]): () => string {
  let index = 0;
  return () => values[index++ % values.length];
}

describe("mint", () => {
  it("mints prefix_6hex and records the id in the collision set", () => {
    const existing = new Set<string>();
    const id = mint("txt", existing, seqGen("abc123"));
    expect(id).toBe("txt_abc123");
    expect(existing.has("txt_abc123")).toBe(true);
  });

  it("re-rolls until the candidate is unique", () => {
    const existing = new Set<string>(["txt_aaaaaa"]);
    const id = mint("txt", existing, seqGen("aaaaaa", "aaaaaa", "bbbbbb"));
    expect(id).toBe("txt_bbbbbb");
  });

  it("keeps successively minted ids distinct via the shared set", () => {
    const existing = new Set<string>();
    const a = mint("box", existing, seqGen("111111"));
    // `b`'s first roll collides with `a` (now in the set), forcing a re-roll.
    const b = mint("box", existing, seqGen("111111", "222222"));
    expect(a).toBe("box_111111");
    expect(b).toBe("box_222222");
  });
});

describe("duplicateSubtree", () => {
  it("deep-copies + reminints every id and remaps children arrays", () => {
    const page = structuralPage();
    const copy = duplicateSubtree(page, "secA", seqGen("s1s1s1", "b1b1b1", "t1t1t1"));
    expect(copy).not.toBeNull();
    const nodes = copy!.nodes;
    const ids = nodes.map((node) => node.id);
    // No original id survives.
    for (const original of ["secA", "box", "t1"]) {
      expect(ids).not.toContain(original);
    }
    // The root is the reminted section, and its child points at the reminted box.
    const root = nodes.find((node) => node.id === copy!.root)!;
    expect(root.kind).toBe("section");
    const childBox = nodes.find((node) => node.id === root.children?.[0])!;
    expect(childBox.kind).toBe("container");
    const grandchild = nodes.find((node) => node.id === childBox.children?.[0])!;
    expect(grandchild.kind).toBe("text");
    expect(grandchild.content).toBe("one");
    // Every child reference resolves inside the cloned subtree.
    const cloneIds = new Set(ids);
    for (const node of nodes) {
      for (const child of node.children ?? []) {
        expect(cloneIds.has(child)).toBe(true);
      }
    }
  });

  it("returns null when the node isn't in the page", () => {
    expect(duplicateSubtree(structuralPage(), "nope")).toBeNull();
  });
});

describe("deriveInsertPlacement", () => {
  const page = structuralPage();

  it("no selection → end of the page root's children", () => {
    expect(deriveInsertPlacement(page, null)).toEqual({ parent: "root", index: 2 });
  });

  it("a Section selected → its next sibling under the root", () => {
    expect(deriveInsertPlacement(page, "secA")).toEqual({ parent: "root", index: 1 });
  });

  it("a Container (branch) selected → appended into it", () => {
    expect(deriveInsertPlacement(page, "box")).toEqual({ parent: "box", index: 1 });
  });

  it("a leaf selected → after it inside its parent", () => {
    expect(deriveInsertPlacement(page, "t1")).toEqual({ parent: "box", index: 1 });
  });

  it("a SECTION insertable escapes to root level: after the enclosing section", () => {
    // t1 lives inside box inside secA (root index 0) — a Section insert from
    // that selection must land at root index 1, never inside the container.
    expect(deriveInsertPlacement(page, "t1", true)).toEqual({ parent: "root", index: 1 });
    // No selection → root end; a selected section behaves like next-sibling.
    expect(deriveInsertPlacement(page, null, true)).toEqual({ parent: "root", index: 2 });
    expect(deriveInsertPlacement(page, "secA", true)).toEqual({ parent: "root", index: 1 });
  });
});

describe("buildInsertNodeOp", () => {
  it("wraps a non-Section insertable in a Section+Container when it lands at the root", () => {
    const op = buildInsertNodeOp({
      page: structuralPage(),
      selectedNodeId: null,
      kind: "text",
      gen: seqGen("t00001", "b00001", "s00001")
    });
    expect(op.kind).toBe("insert_node");
    if (op.kind !== "insert_node") {
      throw new Error("expected insert_node");
    }
    expect(op.parent).toBe("root");
    expect(op.index).toBe(2);
    const rootNode = op.nodes.find((node) => node.id === op.root)!;
    expect(rootNode.kind).toBe("section");
    // The wrapped subtree carries a container and the text leaf.
    expect(op.nodes.some((node) => node.kind === "container")).toBe(true);
    expect(op.nodes.some((node) => node.kind === "text" && node.content === "New text")).toBe(true);
  });

  it("does NOT wrap when the insertable lands inside a container", () => {
    const op = buildInsertNodeOp({
      page: structuralPage(),
      selectedNodeId: "box",
      kind: "text",
      gen: seqGen("t00001")
    });
    if (op.kind !== "insert_node") {
      throw new Error("expected insert_node");
    }
    expect(op.parent).toBe("box");
    expect(op.index).toBe(1);
    expect(op.nodes).toHaveLength(1);
    expect(op.nodes[0].kind).toBe("text");
    expect(op.root).toBe(op.nodes[0].id);
  });

  it("inserts a Section as a root sibling without wrapping", () => {
    const op = buildInsertNodeOp({
      page: structuralPage(),
      selectedNodeId: null,
      kind: "section",
      gen: seqGen("t00001", "b00001", "s00001")
    });
    if (op.kind !== "insert_node") {
      throw new Error("expected insert_node");
    }
    expect(op.parent).toBe("root");
    const rootNode = op.nodes.find((node) => node.id === op.root)!;
    expect(rootNode.kind).toBe("section");
    // Exactly one section (no wrap scaffold added a second).
    expect(op.nodes.filter((node) => node.kind === "section")).toHaveLength(1);
  });
});

describe("moveSectionIndex", () => {
  it("drops below the source → boundary shifts down one (after)", () => {
    expect(moveSectionIndex(0, 2)).toBe(1);
  });

  it("drops above the source → boundary unchanged (before)", () => {
    expect(moveSectionIndex(2, 0)).toBe(0);
  });

  it("a same-slot drop resolves to the source index (caller no-ops)", () => {
    expect(moveSectionIndex(1, 1)).toBe(1);
    expect(moveSectionIndex(1, 2)).toBe(1);
  });
});

describe("classifyEmbedUrl", () => {
  it("classifies a calendly.com link (and subdomains) as the calendly provider", () => {
    expect(classifyEmbedUrl("https://calendly.com/team/intro")).toEqual({
      kind: "embed",
      provider: "calendly",
      url: "https://calendly.com/team/intro",
      html: ""
    });
    expect(classifyEmbedUrl("https://acme.calendly.com/demo")?.provider).toBe("calendly");
    // Trims surrounding whitespace before classifying.
    expect(classifyEmbedUrl("  https://calendly.com/x  ")?.provider).toBe("calendly");
  });

  it("classifies any other https URL as custom", () => {
    expect(classifyEmbedUrl("https://widget.example/embed")).toEqual({
      kind: "embed",
      provider: "custom",
      url: "https://widget.example/embed",
      html: ""
    });
  });

  it("rejects a non-https URL (returns null so the card does not commit)", () => {
    expect(classifyEmbedUrl("http://widget.example/embed")).toBeNull();
    expect(classifyEmbedUrl("calendly.com/x")).toBeNull();
    expect(classifyEmbedUrl("")).toBeNull();
  });
});
