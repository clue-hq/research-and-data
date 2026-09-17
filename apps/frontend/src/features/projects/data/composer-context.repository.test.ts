import assert from "node:assert/strict";
import test from "node:test";
import { createHttpComposerContextRepository } from "./composer-context.repository";

test("composer preparation uses the same-origin BFF and returns exact canonical versions", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return Response.json({
      data: {
        project_id: "project-1",
        thread_id: "thread-1",
        context_entities: [
          {
            object_type: "account",
            object_id: "account-1",
            label: "Acme",
            secondary_label: "acme.example",
            image_url: null,
            version: 9,
          },
          {
            object_type: "account",
            object_id: "account-2",
            label: "Globex",
            secondary_label: "globex.example",
            image_url: "https://cdn.brandfetch.io/domain/globex.example/w/128/h/128?c=cid",
            version: 3,
          },
          {
            object_type: "contact",
            object_id: "contact-1",
            label: "Pat Lee",
            secondary_label: "CEO",
            image_url: "https://elsewhere.example/pat.png",
            version: 2,
          },
        ],
      },
    });
  };
  try {
    const prepared = await createHttpComposerContextRepository({
      mode: "http",
      prefix: "/api/clue",
    }).prepare({
      contextRefs: [
        { objectId: "account-1", objectType: "account", version: null },
        { objectId: "account-2", objectType: "account", version: null },
        { objectId: "contact-1", objectType: "contact", version: null },
      ],
      projectId: "project-1",
      threadId: "thread-1",
    });

    assert.equal(calls[0]?.input, "/api/clue/api/v1/projects/project-1/composer-context/prepare");
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      thread_id: "thread-1",
      context_refs: [
        { object_type: "account", object_id: "account-1", version: null },
        { object_type: "account", object_id: "account-2", version: null },
        { object_type: "contact", object_id: "contact-1", version: null },
      ],
    });
    // No image is no image (the renderer draws the building glyph or the initials); a
    // Brandfetch Logo API URL passes through; any other host is dropped, never embedded.
    assert.deepEqual(prepared.entities, [
      {
        id: "account-1",
        imagePath: undefined,
        label: "Acme",
        secondaryLabel: "acme.example",
        type: "account",
        version: 9,
      },
      {
        id: "account-2",
        imagePath: "https://cdn.brandfetch.io/domain/globex.example/w/128/h/128?c=cid",
        label: "Globex",
        secondaryLabel: "globex.example",
        type: "account",
        version: 3,
      },
      {
        id: "contact-1",
        imagePath: undefined,
        label: "Pat Lee",
        secondaryLabel: "CEO",
        type: "contact",
        version: 2,
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
