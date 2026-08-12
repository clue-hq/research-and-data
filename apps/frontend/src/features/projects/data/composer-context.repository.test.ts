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
      ],
      projectId: "project-1",
      threadId: "thread-1",
    });

    assert.equal(calls[0]?.input, "/api/clue/api/v1/projects/project-1/composer-context/prepare");
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      thread_id: "thread-1",
      context_refs: [
        { object_type: "account", object_id: "account-1", version: null },
      ],
    });
    assert.deepEqual(prepared.entities, [
      {
        id: "account-1",
        imagePath: "/logos/clue.svg",
        label: "Acme",
        secondaryLabel: "acme.example",
        type: "account",
        version: 9,
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
