import { describe, expect, it, vi } from "./vitest-shim";

import {
  addPageOp,
  buildInsertCustomComponentOp,
  buildInsertNodeOp,
  buildWebRichTextVariableCatalog,
  buildWebButtonProps,
  classifyEmbedUrl,
  composeSlotKey,
  createWebAccount,
  deriveInsertPlacement,
  deriveWebDocument,
  duplicateSubtree,
  fetchWebDocument,
  fetchWebPublishInfo,
  initialCustomComponentProps,
  isValidSlotKey,
  isWebButtonCommandProps,
  listDialogComponents,
  listCustomComponents,
  listWebAccounts,
  listWebTemplates,
  mint,
  moveSectionIndex,
  planCanvasNodeMove,
  planCanvasNodeResize,
  publishWebDocument,
  removePageOp,
  resumeWebBatch,
  setWebNoindex,
  rollbackWebPublish,
  routeIsValid,
  saveWebTemplate,
  setPageMetaOp,
  setSlotKeyOp,
  slotKeyParts,
  startWebTurn,
  startWebBatch,
  suggestPublishSlug,
  suggestSlugBase,
  unpublishWebSite,
  webBatchIsUnfinished,
  webNodeButtonAction,
  type WebBatchResult,
  type WebAccount,
  type CustomComponentArtifact,
  type WebDoc,
  type WebNode,
  type WebPageSummary
} from "../webDocuments";
import { richTextHrefError } from "../webRichText";

const SLUG_RE = /^[a-z0-9][a-z0-9-]{2,63}$/;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function buttonNode(overrides: Partial<WebNode>): WebNode {
  return { id: "cta", kind: "button", classes: "", label: "Get started", variant: "primary", ...overrides };
}

const CUSTOM_ARTIFACT: CustomComponentArtifact = {
  artifact_id: `ccart_${"a".repeat(64)}`,
  account_id: "acc_alpha",
  slug: "pricing-card",
  manifest: {
    schema_version: 2,
    meta: { name: "Pricing Card", description: "Typed pricing." },
    props_schema: {
      type: "object",
      additionalProperties: false,
      required: ["headline", "count", "featured", "tone"],
      properties: {
        headline: { type: "string" },
        count: { type: "number", default: 2 },
        featured: { type: "boolean" },
        tone: { type: "string", enum: ["calm", "bold"] },
        optionalCopy: { type: "string" }
      }
    },
    defaults: { headline: "Plans" },
    warnings: [],
    browser: { format: "esm", react: "host-singleton" }
  },
  provenance: { source_version: 2 }
};

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

describe("startWebTurn", () => {
  it("pins the async turn to the loaded document version", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { run_id: "run_web_1" }));
    const started = await startWebTurn(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_web",
      "Tighten the hero",
      12,
      "openai:test-model",
      ["hero-copy"]
    );
    expect(started).toEqual({ runId: "run_web_1" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_web/web/turns");
    expect(JSON.parse(String(init?.body))).toEqual({
      prompt: "Tighten the hero",
      base_version: 12,
      model: "openai:test-model",
      target_node_ids: ["hero-copy"]
    });
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

  it("remints a custom-component leaf while preserving its immutable pin and typed props", () => {
    const page = structuralPage();
    page.nodes!.cc = {
      id: "cc",
      kind: "custom_component",
      classes: "w-[420px] h-[200px]",
      slug: "book-a-call",
      artifact_id: `ccart_${"a".repeat(64)}`,
      props: { headline: "Book a call", showLogo: true, step: 2 }
    };
    page.nodes!.box.children = ["t1", "cc"];
    const copy = duplicateSubtree(page, "cc", seqGen("c1c1c1"));
    expect(copy).toEqual({
      root: "cc_c1c1c1",
      nodes: [
        {
          ...page.nodes!.cc,
          id: "cc_c1c1c1",
          children: undefined
        }
      ]
    });
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

describe("custom-component picker insertion", () => {
  it("derives deterministic supported defaults and neutral required values", () => {
    expect(initialCustomComponentProps(CUSTOM_ARTIFACT)).toEqual({
      headline: "Plans",
      count: 2,
      featured: false,
      tone: "calm"
    });
  });

  it("reuses generic placement and inserts one canonical immutable leaf", () => {
    const op = buildInsertCustomComponentOp({
      page: structuralPage(),
      selectedNodeId: "box",
      component: {
        slug: CUSTOM_ARTIFACT.slug,
        artifactId: CUSTOM_ARTIFACT.artifact_id,
        props: initialCustomComponentProps(CUSTOM_ARTIFACT)
      },
      gen: seqGen("c00001")
    });
    expect(op).toEqual({
      kind: "insert_node",
      page_id: "home",
      parent: "box",
      index: 1,
      root: "cc_c00001",
      nodes: [
        {
          id: "cc_c00001",
          kind: "custom_component",
          classes: "w-full min-h-[160px]",
          slug: "pricing-card",
          artifact_id: CUSTOM_ARTIFACT.artifact_id,
          props: {
            headline: "Plans",
            count: 2,
            featured: false,
            tone: "calm"
          }
        }
      ]
    });
  });

  it("loads only executable account-local catalog artifacts", async () => {
    const legacy = {
      ...CUSTOM_ARTIFACT,
      artifact_id: `ccart_${"b".repeat(64)}`,
      manifest: { schema_version: 1 }
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        components: [
          {
            account_id: "acc_alpha",
            slug: "pricing-card",
            source_version: 2,
            artifact_count: 2,
            latest_artifact: CUSTOM_ARTIFACT
          },
          {
            account_id: "acc_alpha",
            slug: "legacy",
            source_version: 1,
            artifact_count: 1,
            latest_artifact: legacy
          }
        ]
      })
    );
    const catalog = await listCustomComponents(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "acc_alpha"
    );
    expect(catalog).toEqual([
      {
        accountId: "acc_alpha",
        slug: "pricing-card",
        sourceVersion: 2,
        artifactCount: 2,
        latestArtifact: CUSTOM_ARTIFACT
      }
    ]);
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/web/accounts/acc_alpha/custom-components"
    );
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

describe("planCanvasNodeMove", () => {
  function movePage(): WebPageSummary {
    const page = structuralPage();
    page.nodes = {
      ...page.nodes,
      box: { ...page.nodes!.box, children: ["t1", "cta", "photo", "inner", "cc"] },
      cta: {
        id: "cta",
        kind: "button",
        classes: "",
        label: "Go",
        href: "https://example.com"
      },
      photo: {
        id: "photo",
        kind: "image",
        classes: "",
        asset_id: "asset_photo",
        alt: "Photo"
      },
      inner: { id: "inner", kind: "container", classes: "", children: [] },
      cc: {
        id: "cc",
        kind: "custom_component",
        classes: "",
        slug: "book-a-call",
        artifact_id: `ccart_${"a".repeat(64)}`,
        props: {}
      }
    };
    return page;
  }

  it("plans sibling reorder with the post-removal destination index", () => {
    expect(planCanvasNodeMove(movePage(), "photo", "box", 0)).toEqual({
      operation: {
        kind: "move_node",
        page_id: "home",
        id: "photo",
        new_parent: "box",
        index: 0
      },
      intent: "reorder_node"
    });
  });

  it("plans a text/button/image/container/custom-component reparent into a Section or Container", () => {
    const page = movePage();
    expect(planCanvasNodeMove(page, "t1", "secB", 0)?.intent).toBe("reparent_node");
    expect(planCanvasNodeMove(page, "cta", "secB", 0)?.operation).toEqual(
      expect.objectContaining({ kind: "move_node", id: "cta", new_parent: "secB" })
    );
    expect(planCanvasNodeMove(page, "photo", "secB", 0)).not.toBeNull();
    expect(planCanvasNodeMove(page, "inner", "secB", 0)).not.toBeNull();
    expect(planCanvasNodeMove(page, "cc", "secB", 0)).not.toBeNull();
  });

  it("keeps Sections at the root while preserving top-level reorder", () => {
    expect(planCanvasNodeMove(movePage(), "secB", "root", 0)).toEqual({
      operation: {
        kind: "move_node",
        page_id: "home",
        id: "secB",
        new_parent: "root",
        index: 0
      },
      intent: "reorder_node"
    });
    expect(planCanvasNodeMove(movePage(), "secB", "secA", 0)).toBeNull();
    expect(planCanvasNodeMove(movePage(), "cta", "root", 0)).toBeNull();
  });

  it("rejects roots, cycles, leaves as parents, invalid indexes and same-slot drops", () => {
    const page = movePage();
    expect(planCanvasNodeMove(page, "root", "secA", 0)).toBeNull();
    expect(planCanvasNodeMove(page, "box", "inner", 0)).toBeNull();
    expect(planCanvasNodeMove(page, "cta", "t1", 0)).toBeNull();
    expect(planCanvasNodeMove(page, "cta", "secB", 2)).toBeNull();
    expect(planCanvasNodeMove(page, "cta", "box", 1)).toBeNull();
    expect(planCanvasNodeMove(page, "missing", "box", 0)).toBeNull();
  });
});

describe("planCanvasNodeResize", () => {
  function resizePage(): WebPageSummary {
    return {
      id: "home",
      name: "Home",
      route: "/",
      root: "root",
      nodes: {
        root: { id: "root", kind: "root", classes: "", children: ["hero"] },
        hero: { id: "hero", kind: "section", classes: "", children: ["stack"] },
        stack: {
          id: "stack",
          kind: "container",
          classes: "flex size-10 md:w-full rounded-xl",
          children: ["copy", "cta", "photo", "cc"]
        },
        copy: { id: "copy", kind: "text", classes: "text-primary", content: "Hello" },
        cta: { id: "cta", kind: "button", classes: "w-fit", label: "Go" },
        photo: { id: "photo", kind: "image", classes: "h-auto", asset_id: "a", alt: "" },
        cc: {
          id: "cc",
          kind: "custom_component",
          classes: "",
          slug: "book-a-call",
          artifact_id: `ccart_${"a".repeat(64)}`,
          props: {}
        }
      }
    };
  }

  it("persists a corner resize as one class operation", () => {
    expect(planCanvasNodeResize(resizePage(), "stack", 320, 180)).toEqual({
      operation: {
        kind: "set_node_classes",
        page_id: "home",
        id: "stack",
        classes: "flex md:w-full rounded-xl w-[320px] h-[180px]"
      },
      intent: "resize_node"
    });
  });

  it("supports one-axis resize for containers, text, buttons, images, and custom components", () => {
    const page = resizePage();
    expect(planCanvasNodeResize(page, "stack", 240, null)).not.toBeNull();
    expect(planCanvasNodeResize(page, "copy", 240, null)).not.toBeNull();
    expect(planCanvasNodeResize(page, "cta", 240, null)).not.toBeNull();
    expect(planCanvasNodeResize(page, "photo", null, 160)).not.toBeNull();
    expect(planCanvasNodeResize(page, "cc", 480, 240)).not.toBeNull();
  });

  it("rejects sections, roots, missing nodes, invalid bounds, and no-op sizes", () => {
    const page = resizePage();
    expect(planCanvasNodeResize(page, "hero", 320, 180)).toBeNull();
    expect(planCanvasNodeResize(page, "root", 320, 180)).toBeNull();
    expect(planCanvasNodeResize(page, "missing", 320, 180)).toBeNull();
    expect(planCanvasNodeResize(page, "copy", 15, null)).toBeNull();
    expect(planCanvasNodeResize(page, "copy", Number.NaN, null)).toBeNull();
    expect(planCanvasNodeResize(page, "copy", null, null)).toBeNull();
    const once = planCanvasNodeResize(page, "copy", 240, null);
    if (!once || once.operation.kind !== "set_node_classes") {
      throw new Error("expected set_node_classes");
    }
    page.nodes!.copy.classes = once.operation.classes;
    expect(planCanvasNodeResize(page, "copy", 240, null)).toBeNull();
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

// ── publish ──────────────────────────────────────────────────────────────────

describe("suggestPublishSlug", () => {
  it("slugifies the title and appends the document id's last 4 chars", () => {
    const slug = suggestPublishSlug("My Cool Site", "doc_ab12");
    expect(slug).toBe("my-cool-site-ab12");
    expect(slug).toMatch(SLUG_RE);
  });

  it("collapses non-alnum runs to a single hyphen and trims the ends", () => {
    const slug = suggestPublishSlug("  My   Cool!!! Site??? ", "doc_9f3a");
    expect(slug).toBe("my-cool-site-9f3a");
    expect(slug).toMatch(SLUG_RE);
  });

  it("clamps the result to 64 characters", () => {
    const slug = suggestPublishSlug("word ".repeat(40), "doc_ab12");
    expect(slug.length).toBeLessThanOrEqual(64);
    expect(slug).toMatch(SLUG_RE);
    // No dangling hyphen after the clamp.
    expect(slug.endsWith("-")).toBe(false);
  });

  it("falls back to 'site' for a non-latin (or empty) title", () => {
    const nonLatin = suggestPublishSlug("日本語のサイト", "doc_ab12");
    expect(nonLatin).toBe("site-ab12");
    expect(nonLatin).toMatch(SLUG_RE);
    expect(suggestPublishSlug("", "doc_ab12")).toBe("site-ab12");
    expect(suggestPublishSlug("   ", "doc_ab12")).toBe("site-ab12");
  });
});

describe("fetchWebPublishInfo", () => {
  it("returns the unpublished state", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { published: false })
    );
    const info = await fetchWebPublishInfo(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123"
    );
    expect(info.published).toBe(false);
    expect(info.slug).toBeNull();
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/documents/doc_abc123/web/publish"
    );
  });

  it("maps the published state's snake_case fields", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        published: true,
        slug: "acme",
        url: "/p/acme",
        custom_url: null,
        public_origin: "https://acme.pages.test",
        custom_origin: null,
        doc_version: 7,
        status: "published",
        previous_available: true,
        updated_at: "2026-07-29T00:00:00Z",
        publish_id: "webpub_abc",
        manifest_digest: "manifest-abc",
        package_digest: "package-abc",
        html_digest: "html-abc"
      })
    );
    const info = await fetchWebPublishInfo(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123"
    );
    expect(info).toEqual({
      published: true,
      slug: "acme",
      url: "/p/acme",
      customUrl: null,
      publicOrigin: "https://acme.pages.test",
      customOrigin: null,
      docVersion: 7,
      status: "published",
      previousAvailable: true,
      updatedAt: "2026-07-29T00:00:00Z",
      publishId: "webpub_abc",
      manifestDigest: "manifest-abc",
      packageDigest: "package-abc",
      htmlDigest: "html-abc",
      pages: [],
      pageUrls: {},
      customPageUrls: {},
      currentVersion: null,
      noindex: false
    });
  });

  it("maps the document's current version and durable noindex (K6-2, K6-3)", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { published: true, slug: "acme", doc_version: 3, current_version: 4, noindex: true })
    );
    const info = await fetchWebPublishInfo(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "site"
    );
    expect(info.docVersion).toBe(3);
    expect(info.currentVersion).toBe(4);
    expect(info.noindex).toBe(true);
  });

  it("maps the custom hostname's url and page urls", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        published: true,
        slug: "acme",
        url: "https://acme.pages.test/acme",
        custom_url: "https://go.acme.com/acme",
        public_origin: "https://acme.pages.test",
        custom_origin: "https://go.acme.com",
        status: "active",
        page_urls: { "/": "https://acme.pages.test/acme" },
        custom_page_urls: {
          "/": "https://go.acme.com/acme",
          "/pricing": "https://go.acme.com/acme/pricing",
          "/broken": 7
        }
      })
    );
    const info = await fetchWebPublishInfo(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123"
    );
    expect(info.customUrl).toBe("https://go.acme.com/acme");
    expect(info.customOrigin).toBe("https://go.acme.com");
    // The non-string entry is dropped, exactly as for `page_urls`.
    expect(info.customPageUrls).toEqual({
      "/": "https://go.acme.com/acme",
      "/pricing": "https://go.acme.com/acme/pricing"
    });
  });

  it("maps the F5 route index and its absolute page urls", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        published: true,
        slug: "acme",
        url: "https://sites.example/w/ws_1/p/acme",
        status: "active",
        previous_available: false,
        pages: [
          { route: "/", page_id: "page_home", html_digest: "aaa" },
          { route: "/pricing", page_id: "page_pricing", html_digest: "bbb" },
          "not-a-page"
        ],
        page_urls: {
          "/": "https://sites.example/w/ws_1/p/acme",
          "/pricing": "https://sites.example/w/ws_1/p/acme/pricing",
          "/broken": 7
        }
      })
    );
    const info = await fetchWebPublishInfo(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123"
    );
    expect(info.pages).toEqual([
      { route: "/", pageId: "page_home", htmlDigest: "aaa" },
      { route: "/pricing", pageId: "page_pricing", htmlDigest: "bbb" }
    ]);
    expect(info.pageUrls).toEqual({
      "/": "https://sites.example/w/ws_1/p/acme",
      "/pricing": "https://sites.example/w/ws_1/p/acme/pricing"
    });
  });

  it("throws the server message on a non-2xx", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    await expect(
      fetchWebPublishInfo({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_abc123")
    ).rejects.toThrow("boom");
  });
});

describe("setWebNoindex", () => {
  it("puts the explicit choice on the document's noindex route and returns what was stored", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { schema_version: 1, document_id: "doc_abc123", web_noindex: false })
    );
    const stored = await setWebNoindex({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_abc123", false);
    expect(stored).toBe(false);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_abc123/web-noindex");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ noindex: false });
  });

  it("throws the server message on a refusal", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(409, { detail: { code: "document.kind_unsupported", message: "not a website" } })
    );
    await expect(
      setWebNoindex({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_abc123", true)
    ).rejects.toThrow("not a website");
  });
});

describe("publishWebDocument", () => {
  it("posts the slug and maps the result", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        schema_version: 3,
        slug: "acme",
        url: "/p/acme",
        custom_url: null,
        public_origin: "https://acme.pages.test",
        custom_origin: null,
        doc_version: 2,
        runtime_version: 2,
        previous_available: false,
        publish_id: "webpub_abc",
        manifest_digest: "manifest-abc",
        package_digest: "package-abc",
        html_digest: "html-abc"
      })
    );
    const result = await publishWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "acme"
    );
    expect(result).toEqual({
      schemaVersion: 3,
      slug: "acme",
      url: "/p/acme",
      customUrl: null,
      publicOrigin: "https://acme.pages.test",
      customOrigin: null,
      docVersion: 2,
      runtimeVersion: "2",
      previousAvailable: false,
      publishId: "webpub_abc",
      manifestDigest: "manifest-abc",
      packageDigest: "package-abc",
      htmlDigest: "html-abc",
      routes: [],
      // A response carrying neither `routes` nor `page_urls` (a server older
      // than F5) maps to empty for both — the caller falls back to joining.
      pageUrls: {},
      customPageUrls: {}
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_abc123/web/publish");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ slug: "acme" });
  });

  it("reads the absolute address the server gives every route", async () => {
    // F5 task 14: once a workspace handle and a host suffix exist, the site is
    // served from an origin the client cannot derive — so the publish response
    // carries the addresses and this parses them rather than rebuilding them.
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        slug: "launch",
        url: "https://acme.pages.cluehq.ai/launch",
        routes: ["/", "/pricing"],
        page_urls: {
          "/": "https://acme.pages.cluehq.ai/launch",
          "/pricing": "https://acme.pages.cluehq.ai/launch/pricing",
          "/bad": 7
        }
      })
    );
    const result = await publishWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "launch"
    );
    // The non-string entry is dropped, not coerced into a URL nobody can open.
    expect(result.pageUrls).toEqual({
      "/": "https://acme.pages.cluehq.ai/launch",
      "/pricing": "https://acme.pages.cluehq.ai/launch/pricing"
    });
    expect(result.customPageUrls).toEqual({});
  });

  it("reads the custom hostname's addresses off the publish response", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        slug: "launch",
        url: "https://acme.pages.cluehq.ai/launch",
        custom_url: "https://go.acme.com/launch",
        custom_origin: "https://go.acme.com",
        routes: ["/", "/pricing"],
        page_urls: {
          "/": "https://acme.pages.cluehq.ai/launch",
          "/pricing": "https://acme.pages.cluehq.ai/launch/pricing"
        },
        custom_page_urls: {
          "/": "https://go.acme.com/launch",
          "/pricing": "https://go.acme.com/launch/pricing"
        }
      })
    );
    const result = await publishWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "launch"
    );
    expect(result.customUrl).toBe("https://go.acme.com/launch");
    expect(result.customOrigin).toBe("https://go.acme.com");
    expect(result.customPageUrls).toEqual({
      "/": "https://go.acme.com/launch",
      "/pricing": "https://go.acme.com/launch/pricing"
    });
  });

  it("omits the slug from the body when none is passed", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { slug: "acme", url: "/p/acme" }));
    await publishWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_abc123");
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({});
  });

  it("sends noindex only when the caller asks for it, and maps the routes", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { slug: "acme", url: "/p/acme", routes: ["/", "/pricing", 3] })
    );
    const result = await publishWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "acme",
      { noindex: true }
    );
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({
      slug: "acme",
      noindex: true
    });
    expect(result.routes).toEqual(["/", "/pricing"]);

    const withoutOption = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { slug: "acme", url: "/p/acme" }));
    await publishWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl: withoutOption },
      "doc_abc123",
      "acme"
    );
    expect(JSON.parse(String(withoutOption.mock.calls[0][1]?.body))).toEqual({ slug: "acme" });
  });

  it("surfaces the 422 bad-slug message", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(422, { detail: "Slug must be lowercase." }));
    await expect(
      publishWebDocument(
        { apiBaseUrl: "http://localhost:8002", fetchImpl },
        "doc_abc123",
        "BAD SLUG"
      )
    ).rejects.toThrow("Slug must be lowercase.");
  });

  it("surfaces the 409 slug-taken message", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(409, { detail: { message: "Slug already in use." } }));
    await expect(
      publishWebDocument(
        { apiBaseUrl: "http://localhost:8002", fetchImpl },
        "doc_abc123",
        "acme"
      )
    ).rejects.toThrow("Slug already in use.");
  });
});

describe("unpublishWebSite", () => {
  it("DELETEs the slug and maps the result", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { slug: "acme", status: "unpublished" }));
    const result = await unpublishWebSite(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "acme"
    );
    expect(result).toEqual({ slug: "acme", status: "unpublished" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/web/publishes/acme");
    expect(init?.method).toBe("DELETE");
  });

  it("throws the server message on a non-2xx", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(404, { detail: "Not found." }));
    await expect(
      unpublishWebSite({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "acme")
    ).rejects.toThrow("Not found.");
  });
});

describe("rollbackWebPublish", () => {
  it("POSTs the rollback and maps the result", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { slug: "acme", doc_version: 4, status: "published" })
    );
    const result = await rollbackWebPublish(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "acme"
    );
    expect(result).toEqual({ slug: "acme", docVersion: 4, status: "published" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/web/publishes/acme/rollback");
    expect(init?.method).toBe("POST");
  });

  it("surfaces the 409 no-previous message", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(409, { detail: "No previous version to roll back to." }));
    await expect(
      rollbackWebPublish({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "acme")
    ).rejects.toThrow("No previous version to roll back to.");
  });
});

// ── personalization (P5) ───────────────────────────────────────────────────────

describe("slot key helpers", () => {
  it("isValidSlotKey accepts the [a-z0-9_.-] charset up to 64 chars", () => {
    expect(isValidSlotKey("account.name")).toBe(true);
    expect(isValidSlotKey("plan_tier-2")).toBe(true);
    expect(isValidSlotKey("a".repeat(64))).toBe(true);
    expect(isValidSlotKey("a".repeat(65))).toBe(false);
    expect(isValidSlotKey("Account.Name")).toBe(false); // uppercase
    expect(isValidSlotKey("has space")).toBe(false);
    expect(isValidSlotKey("when:account.plan")).toBe(false); // colon not in charset
    expect(isValidSlotKey("")).toBe(false);
  });

  it("slotKeyParts splits the when: gate from a bare key", () => {
    expect(slotKeyParts("account.name")).toEqual({ key: "account.name", whenBound: false });
    expect(slotKeyParts("when:account.plan")).toEqual({ key: "account.plan", whenBound: true });
    expect(slotKeyParts(null)).toEqual({ key: "", whenBound: false });
    expect(slotKeyParts(undefined)).toEqual({ key: "", whenBound: false });
  });

  it("composeSlotKey round-trips through slotKeyParts (and clears on blank)", () => {
    expect(composeSlotKey("account.name", false)).toBe("account.name");
    expect(composeSlotKey("account.plan", true)).toBe("when:account.plan");
    expect(composeSlotKey("  ", true)).toBeNull();
    expect(composeSlotKey("", false)).toBeNull();
    const stored = composeSlotKey("account.logo", true);
    expect(slotKeyParts(stored)).toEqual({ key: "account.logo", whenBound: true });
  });

  it("setSlotKeyOp builds the invertible op (null clears)", () => {
    expect(setSlotKeyOp("home", "hero", "account.name")).toEqual({
      kind: "set_slot_key",
      page_id: "home",
      id: "hero",
      slot_key: "account.name"
    });
    expect(setSlotKeyOp("home", "hero", null)).toEqual({
      kind: "set_slot_key",
      page_id: "home",
      id: "hero",
      slot_key: null
    });
  });
});

describe("suggestSlugBase", () => {
  it("slugifies the title without the doc-id suffix", () => {
    expect(suggestSlugBase("My Cool Site")).toBe("my-cool-site");
    expect(suggestSlugBase("  Acme!!! Health  ")).toBe("acme-health");
  });
  it("falls back to 'site' for an empty/non-latin title", () => {
    expect(suggestSlugBase("")).toBe("site");
    expect(suggestSlugBase("日本語")).toBe("site");
  });
});

describe("webBatchIsUnfinished", () => {
  const base: WebBatchResult = {
    batchId: "batch_1",
    status: "complete",
    counts: { total: 5, derived: 5, published: 5, failed: 0 },
    manifest: [],
    cursor: 5
  };
  it("is unfinished when the cursor is below the total", () => {
    expect(webBatchIsUnfinished({ ...base, cursor: 3 })).toBe(true);
  });
  it("is finished when the cursor reached the total", () => {
    expect(webBatchIsUnfinished({ ...base, cursor: 5 })).toBe(false);
  });
  it("falls back to a non-terminal status when the cursor is absent", () => {
    expect(webBatchIsUnfinished({ ...base, cursor: null, status: "running" })).toBe(true);
    expect(webBatchIsUnfinished({ ...base, cursor: null, status: "complete" })).toBe(false);
  });
});

describe("fetchWebDocument template passthrough", () => {
  it("maps is_template / template_document_id / account_id for web docs", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        id: "doc_1",
        doc_kind: "web",
        title: "Acme — Priv",
        scene: { pages: [] },
        current_version: 4,
        is_template: 1,
        template_document_id: "doc_tmpl",
        account_id: "acc_9"
      })
    );
    const loaded = await fetchWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_1");
    expect(loaded.isTemplate).toBe(true);
    expect(loaded.templateDocumentId).toBe("doc_tmpl");
    expect(loaded.accountId).toBe("acc_9");
  });

  it("defaults the passthrough fields on a plain web doc", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { id: "doc_2", doc_kind: "web", title: "Plain" }));
    const loaded = await fetchWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_2");
    expect(loaded.isTemplate).toBe(false);
    expect(loaded.templateDocumentId).toBeNull();
    expect(loaded.accountId).toBeNull();
  });
});

describe("listWebAccounts", () => {
  it("maps the name-sorted rows (snake_case → camelCase)", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        accounts: [
          {
            account_id: "acc_1",
            name: "Acme",
            domain: "acme.com",
            logo_asset_id: "asset_a",
            data: { plan: "Enterprise" },
            notes: "big fish",
            created_at: "t0",
            updated_at: "t1"
          }
        ]
      })
    );
    const accounts = await listWebAccounts({ apiBaseUrl: "http://localhost:8002", fetchImpl });
    expect(accounts).toEqual([
      {
        accountId: "acc_1",
        name: "Acme",
        domain: "acme.com",
        logoAssetId: "asset_a",
        data: { plan: "Enterprise" },
        notes: "big fish",
        createdAt: "t0",
        updatedAt: "t1"
      }
    ]);
    expect(String(fetchImpl.mock.calls[0][0])).toBe("http://localhost:8002/web/accounts");
  });
});

describe("rich-text account variable catalog", () => {
  const account = (
    accountId: string,
    overrides: Partial<WebAccount> = {}
  ): WebAccount => ({
    accountId,
    name: "Acme",
    domain: null,
    logoAssetId: null,
    data: {},
    notes: null,
    createdAt: null,
    updatedAt: null,
    ...overrides
  });

  it("uses only a derived page's account text model and excludes asset values", () => {
    const catalog = buildWebRichTextVariableCatalog(
      [
        account("acc_1", {
          name: "Acme",
          domain: "acme.test",
          logoAssetId: "asset_logo",
          data: { plan: "Enterprise" }
        }),
        account("acc_2", { name: "Beta", data: { region: "West" } })
      ],
      "acc_1"
    );
    expect(catalog).toEqual([
      { key: "account.domain", label: "Domain", example: "acme.test" },
      { key: "account.name", label: "Name", example: "Acme" },
      { key: "account.plan", label: "Plan", example: "Enterprise" }
    ]);
  });

  it("returns the template union, filters invalid keys, and is honestly empty without accounts", () => {
    expect(
      buildWebRichTextVariableCatalog(
        [
          account("acc_1", { data: { plan: "Pro", "Bad Key": "No" } }),
          account("acc_2", { data: { region: "West" } })
        ],
        null
      ).map((entry) => entry.key)
    ).toEqual(["account.name", "account.plan", "account.region"]);
    expect(buildWebRichTextVariableCatalog([], null)).toEqual([]);
    expect(buildWebRichTextVariableCatalog([account("acc_1")], "missing")).toEqual([]);
  });
});

describe("richTextHrefError", () => {
  it("mirrors the server's safe href scheme grammar", () => {
    for (const href of [
      "https://example.com",
      "http://example.com",
      "mailto:hello@example.com",
      "tel:+15555550100",
      "#pricing",
      "/pricing"
    ]) {
      expect(richTextHrefError(href)).toBeNull();
    }
    expect(richTextHrefError("javascript:alert(1)")).toContain("Use http(s)");
    expect(richTextHrefError("   ")).toBe("Enter a link URL.");
  });
});

describe("createWebAccount", () => {
  it("POSTs camelCase → snake_case, omitting unset fields", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { account_id: "acc_5", name: "Beta" }));
    const created = await createWebAccount(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      { name: "Beta", domain: "beta.com", logoAssetId: "asset_b", data: { tier: "pro" } }
    );
    expect(created.accountId).toBe("acc_5");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/web/accounts");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      name: "Beta",
      domain: "beta.com",
      logo_asset_id: "asset_b",
      data: { tier: "pro" }
    });
  });

  it("surfaces the 422 unresolvable-logo message", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(422, { detail: "logo_asset_id not found." }));
    await expect(
      createWebAccount({ apiBaseUrl: "http://localhost:8002", fetchImpl }, { name: "X" })
    ).rejects.toThrow("logo_asset_id not found.");
  });
});

describe("saveWebTemplate", () => {
  it("POSTs the (optional) title and maps the new id", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { document_id: "doc_t", title: "Base — template" }));
    const saved = await saveWebTemplate(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_src",
      "Base"
    );
    expect(saved).toEqual({ documentId: "doc_t", title: "Base — template" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_src/web/template");
    expect(JSON.parse(String(init?.body))).toEqual({ title: "Base" });
  });
});

describe("listWebTemplates", () => {
  it("maps the template summaries + brand kit ref", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        templates: [
          {
            document_id: "doc_t",
            title: "ABM base",
            version: 3,
            updated_at: "t2",
            brand_kit_ref: { id: "kit_1", version: 2 }
          }
        ]
      })
    );
    const templates = await listWebTemplates({ apiBaseUrl: "http://localhost:8002", fetchImpl });
    expect(templates).toEqual([
      {
        documentId: "doc_t",
        title: "ABM base",
        version: 3,
        updatedAt: "t2",
        brandKitRef: { id: "kit_1", version: 2 }
      }
    ]);
  });
});

describe("deriveWebDocument", () => {
  it("POSTs account_id + title and maps coverage", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        document_id: "doc_new",
        title: "Base — Acme",
        coverage: {
          bound: ["account.name"],
          unbound_slots: [{ key: "account.logo", node_ids: ["img1"] }],
          unbound_vars: [],
          unused_values: ["account.domain"],
          removed_node_ids: ["sec3"]
        },
        diagnostics: []
      })
    );
    const derived = await deriveWebDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_t",
      { accountId: "acc_1", title: "Base — Acme" }
    );
    expect(derived.documentId).toBe("doc_new");
    expect(derived.coverage).toEqual({
      bound: ["account.name"],
      unboundSlots: [{ key: "account.logo", nodeIds: ["img1"] }],
      unboundVars: [],
      unusedValues: ["account.domain"],
      removedNodeIds: ["sec3"]
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_t/web/derive");
    expect(JSON.parse(String(init?.body))).toEqual({ account_id: "acc_1", title: "Base — Acme" });
  });

  it("omits account_id when none is passed (template-only derive)", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { document_id: "doc_new", title: "t" }));
    await deriveWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_t", {});
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({});
  });

  it("surfaces the 422 web_derive.rejected message", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(422, { detail: { message: "Derive rejected." } }));
    await expect(
      deriveWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_t", {
        accountId: "acc_1"
      })
    ).rejects.toThrow("Derive rejected.");
  });
});

describe("startWebBatch", () => {
  it("POSTs account_ids + publish + slug_base and maps the manifest", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        batch_id: "batch_1",
        status: "complete",
        counts: { total: 2, derived: 2, published: 1, failed: 1 },
        cursor: 2,
        manifest: [
          {
            account_id: "acc_1",
            account_name: "Acme",
            document_id: "doc_a",
            slug: "base-acme",
            url: "/p/base-acme",
            status: "published",
            unbound: ["account.logo"]
          },
          {
            account_id: "acc_2",
            account_name: "Beta",
            status: "failed",
            error: "no logo asset"
          }
        ]
      })
    );
    const result = await startWebBatch(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_t",
      { accountIds: ["acc_1", "acc_2"], publish: true, slugBase: "base" }
    );
    expect(result.batchId).toBe("batch_1");
    expect(result.counts).toEqual({ total: 2, derived: 2, published: 1, failed: 1 });
    expect(result.manifest[0]).toEqual({
      accountId: "acc_1",
      accountName: "Acme",
      documentId: "doc_a",
      slug: "base-acme",
      url: "/p/base-acme",
      status: "published",
      unbound: ["account.logo"],
      error: null
    });
    expect(result.manifest[1]).toMatchObject({ status: "failed", error: "no logo asset", unbound: [] });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_t/web/batch");
    expect(JSON.parse(String(init?.body))).toEqual({
      account_ids: ["acc_1", "acc_2"],
      publish: true,
      slug_base: "base"
    });
  });

  it("coerces an unknown per-account status to 'derived'", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        batch_id: "b",
        status: "complete",
        counts: {},
        manifest: [{ account_id: "a", account_name: "A", status: "weird" }]
      })
    );
    const result = await startWebBatch(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_t",
      { accountIds: ["a"], publish: false }
    );
    expect(result.manifest[0].status).toBe("derived");
    // publish=false still sends the flag; slug_base omitted when absent.
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({
      account_ids: ["a"],
      publish: false
    });
  });
});

describe("resumeWebBatch", () => {
  it("POSTs to the resume endpoint and maps the snapshot", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        batch_id: "b",
        status: "complete",
        counts: { total: 3, derived: 3, published: 0, failed: 0 },
        cursor: 3,
        manifest: []
      })
    );
    const result = await resumeWebBatch({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "b");
    expect(result.cursor).toBe(3);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/web/batches/b/resume");
    expect(init?.method).toBe("POST");
  });
});

describe("page operation builders", () => {
  it("setPageMetaOp emits only the keys it was given", () => {
    expect(setPageMetaOp("home", { route: "/x" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      route: "/x"
    });
    // The wire payload must carry no `name` key at all — a `name: undefined`
    // property would still be an own key, and Rust's Option<String> field is
    // skip_serializing_if = "Option::is_none".
    const op = setPageMetaOp("home", { route: "/x" });
    expect(Object.keys(op).includes("name")).toBe(false);
    expect(JSON.stringify(op)).toBe('{"kind":"set_page_meta","page_id":"home","route":"/x"}');
  });

  it("setPageMetaOp carries a name-only edit, and both together", () => {
    expect(setPageMetaOp("home", { name: "Home" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      name: "Home"
    });
    expect(Object.keys(setPageMetaOp("home", { name: "Home" })).includes("route")).toBe(false);
    expect(setPageMetaOp("home", { name: "Home", route: "/" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      name: "Home",
      route: "/"
    });
    // No meta at all is still a well-formed (no-op) payload with no null keys.
    expect(setPageMetaOp("home", {})).toEqual({ kind: "set_page_meta", page_id: "home" });
  });

  it("addPageOp builds an empty page whose root container is in its nodes", () => {
    const op = addPageOp({ id: "pricing", name: "Pricing", route: "/pricing" });
    expect(op.kind).toBe("add_page");
    if (op.kind !== "add_page") {
      throw new Error("expected an add_page op");
    }
    expect(op.page.id).toBe("pricing");
    expect(op.page.name).toBe("Pricing");
    expect(op.page.route).toBe("/pricing");
    expect(op.page.root).toBe("root_pricing");
    expect(op.page.nodes.root_pricing).toEqual({
      id: "root_pricing",
      kind: "container",
      classes: "",
      children: []
    });
    // `index` omitted means "append" to the engine; the key must be absent.
    expect(Object.keys(op).includes("index")).toBe(false);
  });

  it("addPageOp carries an explicit index when one is given", () => {
    const op = addPageOp({ id: "about", name: "About", route: "/about" }, 0);
    if (op.kind !== "add_page") {
      throw new Error("expected an add_page op");
    }
    expect(op.index).toBe(0);
  });

  it("removePageOp names the page", () => {
    expect(removePageOp("pricing")).toEqual({ kind: "remove_page", page_id: "pricing" });
  });
});

describe("routeIsValid", () => {
  it("accepts the engine's good routes", () => {
    for (const good of ["/", "/pricing", "/pricing/enterprise-2026"]) {
      expect(routeIsValid(good)).toBe(true);
    }
  });

  it("refuses the engine's bad routes", () => {
    const bad = [
      "",
      "pricing",
      "/Pricing",
      "/pricing/",
      "//a",
      "/a b",
      "/a_b",
      "/manifest.json",
      "/p-assets/x",
      "/asset-store/x",
      "/x/manifest.json",
      `/${"a".repeat(128)}`
    ];
    for (const route of bad) {
      expect(routeIsValid(route)).toBe(false);
    }
  });
});
