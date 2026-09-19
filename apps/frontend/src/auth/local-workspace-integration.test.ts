import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { build } from "esbuild";

// Keep session resolution, configuration, actions and route bindings real. Only
// Next/Clerk infrastructure and the external HTTP transport are replaced.
const root = process.cwd().endsWith("apps/frontend")
  ? process.cwd()
  : path.join(process.cwd(), "apps/frontend");
const stateKey = "__clueLocalWorkspaceIntegration";
interface RuntimeState {
  token: string | null;
  providerCalls: number;
  memberships: string[];
  principalWorkspace?: string;
  cookieValues: Map<string, string>;
  cookieWrites: string[];
  cookieDeletes: string[];
  fetches: Array<{ url: URL; init: RequestInit; headers: Headers }>;
}

async function bundleApplication() {
  const result = await build({
    stdin: {
      contents: `
        export * from "./src/features/session/data/session-dal";
        export * from "./src/features/session/data/session-actions";
        export * from "./src/auth/authenticated-backend";
        export * as platformRoute from "./src/app/api/clue/[...path]/route";
        export * as designRoute from "./src/app/api/clue/design/[...path]/route";
        export * as provisionRoute from "./src/app/api/onboarding/provision/route";
        export * as establishRoute from "./src/app/(auth)/session/establish/route";
      `,
      resolveDir: root,
      loader: "ts",
    },
    bundle: true,
    platform: "node",
    format: "cjs",
    packages: "external",
    write: false,
    tsconfig: path.join(root, "tsconfig.json"),
    plugins: [{
      name: "framework-infrastructure-only",
      setup(builder) {
        builder.onResolve({ filter: /^(server-only|next\/(headers|navigation|cache)|@clerk\/nextjs\/server)$/ }, ({ path: modulePath }) => ({ path: modulePath, namespace: "stub" }));
        builder.onLoad({ filter: /.*/, namespace: "stub" }, ({ path: modulePath }) => {
          const state = `globalThis.${stateKey}`;
          const modules: Record<string, string> = {
            "server-only": "export {};",
            "next/headers": `export async function cookies() { return {
              get(name) { const value = ${state}.cookieValues.get(name); return value === undefined ? undefined : {value}; },
              set(name, value) { ${state}.cookieWrites.push(name); ${state}.cookieValues.set(name, value); },
              delete(name) { ${state}.cookieDeletes.push(name); ${state}.cookieValues.delete(name); }
            }; }`,
            "next/navigation": "export function redirect(url) { throw Object.assign(new Error('redirect'), {redirect: url}); }",
            "next/cache": "export function revalidatePath() {}",
            "@clerk/nextjs/server": `export async function auth() { ${state}.providerCalls++; return {isAuthenticated: !!${state}.token, getToken: async () => ${state}.token}; }`,
          };
          return { contents: modules[modulePath], loader: "js" };
        });
      },
    }],
  });
  const exports = { exports: {} };
  new Function("require", "module", "exports", result.outputFiles[0].text)(
    createRequire(path.join(root, "package.json")), exports, exports.exports,
  );
  return exports.exports as typeof import("../features/session/data/session-dal") &
    typeof import("../features/session/data/session-actions") &
    typeof import("./authenticated-backend") & {
      platformRoute: typeof import("../app/api/clue/[...path]/route");
      designRoute: typeof import("../app/api/clue/design/[...path]/route");
      provisionRoute: typeof import("../app/api/onboarding/provision/route");
      establishRoute: typeof import("../app/(auth)/session/establish/route");
    };
}

const application = bundleApplication();
const environment: Record<string, string> = {
  NODE_ENV: "development",
  CLUE_AUTH_ENABLED: "true",
  CLUE_APP_ORIGIN: "http://localhost:3021",
  CLUE_API_BASE_URL: "http://platform.invalid",
  LUMEN_API_BASE_URL: "http://design.invalid",
  CLUE_AUTH_CLERK_AUTHORIZED_PARTIES: "http://localhost:3021",
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "test-publishable",
  CLERK_SECRET_KEY: "test-secret",
  CLUE_LOCAL_WORKSPACE_ID: "ws_aws",
  CLUE_LOCAL_WORKSPACE_NAME: "AWS",
};

async function withRuntime(
  action: (app: Awaited<typeof application>, state: RuntimeState) => Promise<void>,
  overrides: Record<string, string> = {},
) {
  const previousEnvironment = Object.fromEntries(Object.keys(environment).map((key) => [key, process.env[key]]));
  const previousFetch = globalThis.fetch;
  const globals = globalThis as unknown as Record<string, unknown>;
  const previousState = globals[stateKey];
  const state: RuntimeState = {
    token: "test-session", providerCalls: 0, memberships: ["ws_aws", "ws_conduit"],
    cookieValues: new Map([
      ["clue_workspace_id", "ws_conduit"],
      ["clue_workspace_id_3021", "ws_conduit"],
      ["clue_workspace_id_3022", "ws_conduit"],
    ]),
    cookieWrites: [], cookieDeletes: [], fetches: [],
  };
  Object.assign(process.env, environment, overrides);
  globals[stateKey] = state;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const headers = new Headers(init.headers);
    state.fetches.push({ url, init, headers });
    if (url.pathname === "/auth/v1/session") return Response.json({
      user_id: "usr_test", has_inactive_memberships: true,
      memberships: state.memberships.map((workspace_id) => ({
        workspace_id, membership_id: `wsm_${workspace_id}`, workspace_name: `Workspace ${workspace_id}`,
        role_key: "owner", permissions: [],
      })),
    });
    // The merged establish route accepts pending invitations first; an installation
    // without invitation delivery refuses with the typed 503, which the route treats
    // as "no invitation to accept" and continues to the ordinary session path.
    if (url.pathname === "/auth/v1/invitations/accept") return Response.json(
      { error: { code: "INVITATIONS_UNCONFIGURED", message: "Invitation acceptance is not configured." } },
      { status: 503 },
    );
    if (url.pathname === "/auth/v1/principal") return Response.json({
      user_id: "usr_test", membership_id: "wsm_selected", role_key: "owner", permissions: [],
      workspace_id: state.principalWorkspace ?? headers.get("X-Clue-Workspace-Id"),
    });
    if (["/frontend/v1/projects", "/brand-kits"].includes(url.pathname)) {
      return Response.json({ workspace: headers.get("X-Workspace-Id") ?? headers.get("X-Clue-Workspace-Id") });
    }
    throw new Error(`Unexpected external request: ${url}`);
  };
  try {
    await action(await application, state);
  } finally {
    globalThis.fetch = previousFetch;
    if (previousState === undefined) delete globals[stateKey]; else globals[stateKey] = previousState;
    for (const [key, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
}

test("real session resolution uses the pin, checks membership and rejects a mismatched principal", async () => {
  await withRuntime(async (app, state) => {
    for (const cookie of [null, "ws_conduit", "ws_stale"]) {
      assert.equal((await app.loadProtectedSession("test-session", cookie)).principal.workspace_id, "ws_aws");
    }
    assert(state.fetches.filter((call) => call.url.pathname.endsWith("/principal")).every((call) => call.headers.get("X-Clue-Workspace-Id") === "ws_aws"));
    state.principalWorkspace = "ws_conduit";
    await assert.rejects(app.loadProtectedSession("test-session", "ws_aws"), { code: "WORKSPACE_FORBIDDEN" });
    state.memberships = ["ws_conduit"];
    state.fetches = [];
    await assert.rejects(app.loadProtectedSession("test-session", "ws_conduit"), { code: "WORKSPACE_FORBIDDEN" });
    assert.deepEqual(state.fetches.map((call) => call.url.pathname), ["/auth/v1/session"]);
  });
});

test("protected SSR and authenticated BFF context agree despite a foreign cookie", async () => {
  await withRuntime(async (app) => {
    assert.equal((await app.getProtectedSession())?.principal.workspace_id, "ws_aws");
    const context = await app.authenticatedBackendContext();
    assert.equal(context.workspaceId, "ws_aws");
    assert.equal(context.requestedWorkspaceId, "ws_conduit");
  });
});

for (const route of ["platformRoute", "designRoute"] as const) {
  test(`${route} overwrites forged headers and repairs only its own port cookie`, async () => {
    await withRuntime(async (app, state) => {
      const segments = route === "platformRoute" ? ["frontend", "v1", "projects"] : ["brand-kits"];
      const response = await app[route].GET(new Request("http://localhost:3021/api/clue/test", {
        headers: { Authorization: "Bearer forged", "X-Workspace-Id": "ws_conduit", "X-Clue-Workspace-Id": "ws_conduit", cookie: "forged=1" },
      }), { params: Promise.resolve({ path: segments }) });
      assert.equal(response.status, 200);
      assert.equal((await response.json()).workspace, "ws_aws");
      const forwarded = state.fetches.at(-1)!;
      assert.equal(forwarded.init.cache, "no-store");
      assert.equal(forwarded.headers.get("cookie"), null);
      assert.equal(forwarded.headers.get("authorization"), route === "platformRoute" ? "Bearer test-session" : null);
      assert.deepEqual(state.cookieWrites, ["clue_workspace_id_3021"]);
      assert.equal(state.cookieValues.get("clue_workspace_id_3021"), "ws_aws");
      assert.equal(state.cookieValues.get("clue_workspace_id_3022"), "ws_conduit");
      assert.equal(state.cookieValues.get("clue_workspace_id"), "ws_conduit");
    });
  });

  test(`${route} refuses missing authentication and missing pinned membership before data forwarding`, async () => {
    await withRuntime(async (app, state) => {
      state.token = null;
      const request = new Request("http://localhost:3021/api/clue/test");
      const context = { params: Promise.resolve({ path: ["brand-kits"] }) };
      assert.equal((await app[route].GET(request, context)).status, 401);
      assert.equal(state.fetches.length, 0);
      state.token = "test-session";
      state.memberships = ["ws_conduit"];
      assert.equal((await app[route].GET(request, context)).status, 403);
      assert.deepEqual(state.fetches.map((call) => call.url.pathname), ["/auth/v1/session"]);
      assert.equal(state.cookieWrites.length, 0);
    });
  });
}

test("workspace Server Actions reject another authorized workspace and clear only the instance cookie", async () => {
  await withRuntime(async (app, state) => {
    const form = new FormData();
    form.set("workspaceId", "ws_conduit");
    await assert.rejects(app.selectWorkspace(form), { code: "WORKSPACE_FORBIDDEN" });
    assert.equal(state.providerCalls, 0);
    assert.equal(state.fetches.length, 0);
    assert.equal(state.cookieWrites.length, 0);
    form.set("workspaceId", "ws_aws");
    await app.selectWorkspace(form);
    assert.deepEqual(state.cookieWrites, ["clue_workspace_id_3021"]);
    await app.clearWorkspaceSelection();
    assert.deepEqual(state.cookieDeletes, ["clue_workspace_id_3021"]);
    assert.equal(state.cookieValues.get("clue_workspace_id_3022"), "ws_conduit");
    assert.equal(state.cookieValues.get("clue_workspace_id"), "ws_conduit");
  });
});

test("session establishment writes the pinned port cookie after real membership validation", async () => {
  await withRuntime(async (app, state) => {
    // The merged route reads the invite token off the request URL before establishing.
    await assert.rejects(
      app.establishRoute.GET(new Request("http://localhost:3021/session/establish")),
      { redirect: "/" },
    );
    assert.deepEqual(state.cookieWrites, ["clue_workspace_id_3021"]);
    assert.equal(state.cookieValues.get("clue_workspace_id_3021"), "ws_aws");
  });
});

test("both provisioning entrypoints refuse before provider or backend work", async () => {
  await withRuntime(async (app, state) => {
    state.token = null;
    const request = () => new Request("http://localhost:3021/api/onboarding/provision", {
      method: "POST", headers: { origin: "http://localhost:3021" }, body: "{}",
    });
    for (const response of [
      await app.provisionRoute.POST(request()),
      await app.platformRoute.POST(request(), { params: Promise.resolve({ path: ["auth", "v1", "provision"] }) }),
    ]) {
      assert.equal(response.status, 403);
      assert.equal((await response.json()).error.code, "LOCAL_WORKSPACE_PINNED");
    }
    assert.equal(state.providerCalls, 0);
    assert.equal(state.fetches.length, 0);
  });
});

test("ordinary unpinned sessions retain explicit cookie selection", async () => {
  await withRuntime(async (app, state) => {
    assert.equal((await app.getProtectedSession())?.principal.workspace_id, "ws_conduit");
    await app.clearWorkspaceSelection();
    assert.deepEqual(state.cookieDeletes, ["clue_workspace_id"]);
    assert.equal(state.cookieValues.get("clue_workspace_id_3021"), "ws_conduit");
  }, { CLUE_LOCAL_WORKSPACE_ID: "", CLUE_LOCAL_WORKSPACE_NAME: "" });
});
