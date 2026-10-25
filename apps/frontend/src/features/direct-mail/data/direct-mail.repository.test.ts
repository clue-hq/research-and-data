import assert from "node:assert/strict";
import test from "node:test";
import { createDirectMailFixture } from "./direct-mail.fixture";
import { createDirectMailRepository, unavailableDirectMailRepository } from "./direct-mail.repository";
import { validateAssetFile } from "./direct-mail.uploads";
import type { DirectMailStore } from "./direct-mail.storage";

function store(): DirectMailStore {
  let state = createDirectMailFixture();
  return { async read() { return structuredClone(state); }, async transact(change) {
    const next = change(structuredClone(state)); state = next.state; return next.result;
  } };
}
test("repository instances share durable drafts and reject stale writes", async () => {
  const storage = store();
  const a = createDirectMailRepository(storage), b = createDirectMailRepository(storage);
  await a.patch("mailer-avery", 1, { selectedGiftId: "coffee-set" });
  assert.equal((await b.read()).mailers[0].selectedGiftId, "coffee-set");
  await assert.rejects(b.patch("mailer-avery", 1, { note: "stale" }), /changed/);
});
test("proposal requests preserve existing choices until explicitly applied", async () => {
  const repo = createDirectMailRepository(store());
  await repo.patch("mailer-avery", 1, { selectedGiftId: "field-notebook", note: "Keep my words" });
  let state = await repo.requestProposal("mailer-avery", 2, "gifts", "Something different");
  assert.equal(state.mailers[0].selectedGiftId, "field-notebook");
  assert.equal(state.mailers[0].note, "Keep my words");
  state = await repo.resolveProposal("mailer-avery", 3, true);
  assert.equal(state.mailers[0].selectedGiftId, null);
  assert.equal(state.mailers[0].gifts.length, 3);
  assert.equal(state.mailers[0].note, "Keep my words");
});
test("campaign creation is deduplicated and keeps the chosen project scope", async () => {
  const repo = createDirectMailRepository(store());
  const input = { projectId: "10m-landing-page-campaign", campaign: "Customer workshops", recipientIds: ["contact-avery", "contact-jordan"], budgetCents: 12000, cardId: "card-studio", styleId: "style-warm" };
  const first = await repo.create(input), second = await repo.create(input);
  assert.equal(first.mailers.length, 10);
  assert.equal(second.mailers.length, 10);
  assert.equal(second.mailers.filter((m) => m.campaign === input.campaign).every((m) => m.budgetCents === 12000 && m.projectId === input.projectId), true);
});
test("invalid uploads fail before reading bytes, live mode never supplies fixture records", async () => {
  assert.throws(() => validateAssetFile({ name: "card.svg", size: 100, type: "image/svg+xml" }, "card"), /PNG or JPEG/);
  assert.throws(() => validateAssetFile({ name: "card.png", size: 10_000_000, type: "image/png" }, "card"), /3 MB/);
  assert.throws(() => validateAssetFile({ name: "style.exe", size: 10, type: "" }, "font"), /font/);
  await assert.rejects(unavailableDirectMailRepository.read(), /not connected/i);
});
