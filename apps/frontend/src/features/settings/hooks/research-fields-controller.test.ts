import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import type { ResearchField, ResearchFields } from "../model/research-fields";
import { createResearchFieldsController } from "./research-fields-controller";

const field: ResearchField = {
  key: "account.crm", label: "CRM", description: "Find the CRM with evidence.",
  origin: "workspace", created_by: "Ada", created_at: "2026-09-16T00:00:00Z",
};
const platform: ResearchField = { ...field, key: "core.name", label: "Name", origin: "platform", created_by: null, created_at: null };
const initial: ResearchFields = { entity: "accounts", rows: [platform, field] };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup(overrides: Partial<Parameters<typeof createResearchFieldsController>[2]> = {}, canManage = true) {
  const notices: [string, boolean | undefined][] = [];
  const actions = {
    createSettingsResearchField: async () => ({ ...field, key: "account.new_field" }),
    patchSettingsResearchField: async (_key: string, patch: Partial<ResearchField>) => ({ ...field, ...patch }),
    retireSettingsResearchField: async () => ({ ok: true as const }),
    ...overrides,
  };
  const controller = createResearchFieldsController(initial, canManage, actions, (message, error) => notices.push([message, error]));
  return { controller, notices };
}

test("create trims the input, blocks double submit, and appends after platform/workspace rows", async () => {
  const response = deferred<ResearchField>();
  let calls = 0;
  const { controller, notices } = setup({ createSettingsResearchField: async (body) => {
    calls++;
    assert.deepEqual(body, { entity: "accounts", label: "New field", description: "Find evidence." });
    return response.promise;
  } });
  const pending = controller.create(" New field ", " Find evidence. ");
  assert.equal(controller.getSnapshot().creating, true);
  assert.equal(await controller.create("duplicate", "duplicate"), false);
  assert.equal(calls, 1);
  response.resolve({ ...field, key: "account.new_field" });
  assert.equal(await pending, true);
  assert.equal(controller.getSnapshot().creating, false);
  assert.deepEqual(controller.getSnapshot().rows.map(row => row.key), ["core.name", "account.crm", "account.new_field"]);
  assert.deepEqual(notices, [["Field created", undefined]]);
});

test("collision errors stay next to Name and failed creates do not add rows", async () => {
  const { controller } = setup({ createSettingsResearchField: async () => {
    throw new ClueApiError("This name is reserved. Add a qualifier.", { code: "KEY_TAKEN", status: 409, requestId: "r" });
  } });
  assert.equal(await controller.create("CRM", "Find evidence"), false);
  assert.deepEqual(controller.getSnapshot().createError, { field: "label", message: "This name is reserved. Add a qualifier." });
  assert.deepEqual(controller.getSnapshot().rows, initial.rows);
  controller.clearCreateError();
  assert.equal(controller.getSnapshot().createError, null);
});

test("blank or oversized instructions never reach the transport", async () => {
  let calls = 0;
  const { controller } = setup({ createSettingsResearchField: async () => { calls++; return field; } });
  await controller.create("Name", "   ");
  assert.equal(controller.getSnapshot().createError?.field, "description");
  await controller.create("x".repeat(201), "Find evidence");
  assert.equal(controller.getSnapshot().createError?.field, "label");
  await assert.rejects(controller.update(field.key, "description", " "), /Description is required/);
  assert.equal(calls, 0);
});

test("reversed disjoint save responses cannot overwrite the other attribute", async () => {
  const name = deferred<ResearchField>(), description = deferred<ResearchField>();
  const { controller } = setup({ patchSettingsResearchField: (_key, patch) => patch.label ? name.promise : description.promise });
  const first = controller.update(field.key, "label", "New name");
  const second = controller.update(field.key, "description", "New instruction");
  assert.equal(controller.isPending(field.key), true);
  description.resolve({ ...field, description: "New instruction" });
  await second;
  name.resolve({ ...field, label: "New name" });
  await first;
  assert.deepEqual(controller.getSnapshot().rows[1], { ...field, label: "New name", description: "New instruction" });
  assert.equal(controller.isPending(field.key), false);
});

test("failed edits retain the saved row and clear pending state", async () => {
  const { controller } = setup({ patchSettingsResearchField: async () => { throw new Error("Access removed"); } });
  await assert.rejects(controller.update(field.key, "label", "New name"), /Access removed/);
  assert.deepEqual(controller.getSnapshot().rows, initial.rows);
  assert.equal(controller.isPending(field.key), false);
});

test("retirement waits for success, refuses pending saves, and keeps failed rows", async () => {
  const save = deferred<ResearchField>(), retire = deferred<{ ok: true }>();
  let retireCalls = 0;
  const { controller, notices } = setup({ patchSettingsResearchField: () => save.promise, retireSettingsResearchField: () => { retireCalls++; return retire.promise; } });
  const writing = controller.update(field.key, "label", "New name");
  assert.equal(await controller.retire(field.key), false);
  assert.equal(retireCalls, 0);
  save.resolve({ ...field, label: "New name" }); await writing;
  const retiring = controller.retire(field.key);
  assert.equal(controller.getSnapshot().rows.length, 2);
  assert.equal(await controller.retire(field.key), false);
  retire.reject(new Error("Retirement refused"));
  assert.equal(await retiring, false);
  assert.equal(controller.getSnapshot().rows.length, 2);
  assert.deepEqual(notices, [["Retirement refused", true]]);
  const success = setup();
  assert.equal(await success.controller.retire(field.key), true);
  assert.deepEqual(success.controller.getSnapshot().rows, [platform]);
});

test("read-only members and platform rows never submit writes", async () => {
  const { controller } = setup({}, false);
  assert.equal(await controller.create("Test", "Test"), false);
  await assert.rejects(controller.update(field.key, "label", "Test"), /read-only/);
  assert.equal(await controller.retire(field.key), false);
  const manager = setup().controller;
  await assert.rejects(manager.update(platform.key, "description", "Test"), /read-only/);
  assert.equal(await manager.retire(platform.key), false);
});

test("leaving a workspace ignores late successes and failures without notifying the next scope", async () => {
  const create = deferred<ResearchField>(), patch = deferred<ResearchField>(), retire = deferred<{ ok: true }>();
  const { controller, notices } = setup({ createSettingsResearchField: () => create.promise, patchSettingsResearchField: () => patch.promise, retireSettingsResearchField: () => retire.promise });
  const creating = controller.create("New", "Instruction");
  const updating = controller.update(field.key, "label", "New name");
  const snapshot = controller.getSnapshot();
  controller.deactivate();
  controller.activate(); // A new lifetime must still reject the old lifetime's results.
  create.resolve({ ...field, key: "account.new" });
  patch.resolve({ ...field, label: "New name" });
  assert.equal(await creating, false); await updating;
  assert.equal(controller.getSnapshot(), snapshot);
  assert.deepEqual(notices, []);
  const removal = setup({ retireSettingsResearchField: () => retire.promise });
  const removing = removal.controller.retire(field.key);
  removal.controller.deactivate();
  retire.reject(new Error("Old scope failure"));
  assert.equal(await removing, false);
  assert.deepEqual(removal.notices, []);
});
