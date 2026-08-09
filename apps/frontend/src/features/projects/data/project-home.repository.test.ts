import assert from "node:assert/strict";
import test from "node:test";
import { ClueChatApiError } from "./chat-api";
import { createHttpProjectHomeRepository } from "./project-home.repository";

const TRANSPORT = { mode: "http", prefix: "/api/clue" } as const;

test("Home HTTP repository maps the real workspace capabilities", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    assert.equal(String(input), "/api/clue/api/v1/home");
    return Response.json({
      data: {
        brands: [{ id: "brd_1", name: "Clue Demo Brand" }],
        default_brand_id: "brd_1",
        context_entities: [],
        agent_profiles: [],
        default_agent_profile_id: null,
        composer_capabilities: {
          context_refs: false,
          attachments: false,
          agent_profile_selection: false,
        },
        suggestions: ["Find target accounts"],
      },
    });
  };
  try {
    const home = await createHttpProjectHomeRepository(TRANSPORT).get();
    assert.deepEqual(home.brands, [{ id: "brd_1", name: "Clue Demo Brand" }]);
    assert.equal(home.defaultBrandId, "brd_1");
    assert.deepEqual(home.composerCapabilities, {
      contextRefs: false,
      attachments: false,
      agentProfileSelection: false,
    });
    assert.deepEqual(home.models, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Home create sends one atomic request and trusts only the returned href", async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = "";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return Response.json(
      {
        data: {
          project: {
            id: "prj_real",
            title: "Untitled project",
            brand_id: "brd_1",
            href: "/projects/prj_real",
            created_at: "2026-08-10T12:00:00Z",
          },
          thread: {
            id: "thr_real",
            title: "Start Northstar research",
            href: "/projects/prj_real?thread=thr_real",
            status: "running",
            pinned: false,
            project_id: "prj_real",
            created_at: "2026-08-10T12:00:00Z",
            updated_at: "2026-08-10T12:00:00Z",
          },
          turn: {
            turn_id: "turn_real",
            thread_id: "thr_real",
            requested_at: "2026-08-10T12:00:00Z",
            replayed: false,
          },
          href: "/projects/prj_real?thread=thr_real",
        },
      },
      { status: 201 },
    );
  };
  try {
    const created = await createHttpProjectHomeRepository(TRANSPORT).create({
      brandId: "brd_1",
      message: "Start Northstar research",
      idempotencyKey: "home-project:test",
    });
    assert.equal(requestUrl, "/api/clue/api/v1/projects");
    assert.equal(requestInit?.method, "POST");
    assert.equal(
      new Headers(requestInit?.headers).get("Idempotency-Key"),
      "home-project:test",
    );
    assert.deepEqual(JSON.parse(String(requestInit?.body)), {
      brand_id: "brd_1",
      message: "Start Northstar research",
      context_refs: [],
      attachment_refs: [],
      agent_profile_id: null,
    });
    assert.equal(created.href, "/projects/prj_real?thread=thr_real");
    assert.equal(created.project.title, "Untitled project");
    assert.equal(created.thread.title, "Start Northstar research");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Home refusals stay typed and never become fixture success", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json(
    {
      error: {
        code: "IDEMPOTENCY_CONFLICT",
        message: "this key belongs to another request",
        requestId: "req-r4",
      },
    },
    { status: 409 },
  );
  try {
    await assert.rejects(
      () => createHttpProjectHomeRepository(TRANSPORT).create({
        brandId: "brd_1",
        message: "Start Northstar research",
        idempotencyKey: "home-project:conflict",
      }),
      (failure: unknown) => {
        assert.ok(failure instanceof ClueChatApiError);
        assert.equal(failure.code, "IDEMPOTENCY_CONFLICT");
        assert.equal(failure.status, 409);
        assert.equal(failure.requestId, "req-r4");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
