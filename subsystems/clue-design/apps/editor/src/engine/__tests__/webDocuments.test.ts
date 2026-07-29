import { describe, expect, it, vi } from "vitest";

import {
  buildInsertNodeOp,
  buildWebButtonProps,
  classifyEmbedUrl,
  deriveInsertPlacement,
  duplicateSubtree,
  fetchWebPublishInfo,
  isWebButtonCommandProps,
  listDialogComponents,
  mint,
  moveSectionIndex,
  publishWebDocument,
  rollbackWebPublish,
  suggestPublishSlug,
  unpublishWebSite,
  webNodeButtonAction,
  type WebDoc,
  type WebNode,
  type WebPageSummary
} from "../webDocuments";

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
        doc_version: 7,
        status: "published",
        previous_available: true,
        updated_at: "2026-07-29T00:00:00Z"
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
      docVersion: 7,
      status: "published",
      previousAvailable: true,
      updatedAt: "2026-07-29T00:00:00Z"
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

describe("publishWebDocument", () => {
  it("posts the slug and maps the result", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        schema_version: 3,
        slug: "acme",
        url: "/p/acme",
        doc_version: 2,
        runtime_version: "v1",
        previous_available: false
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
      docVersion: 2,
      runtimeVersion: "v1",
      previousAvailable: false
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents/doc_abc123/web/publish");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ slug: "acme" });
  });

  it("omits the slug from the body when none is passed", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { slug: "acme", url: "/p/acme" }));
    await publishWebDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl }, "doc_abc123");
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({});
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
