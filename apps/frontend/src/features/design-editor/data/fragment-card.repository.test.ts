/**
 * FE parity for the cloned-section inspector (clone-fidelity F3.2).
 *
 * The dev shell's card and this seam serve the same four affordances, and this file proves them
 * on the frontend's own terms — the fixture adapter enforcing the rules a component will be
 * written against, and the HTTP adapter carrying the backend's refusal SENTENCE rather than a
 * status code:
 *
 * 1. slot values, one control per kind (the manifest the card's controls are built from);
 * 2. a hidden-on-source section is shown as one, with its evidence, and cannot be activated
 *    until an isolation render exists (D-F8 + ruling P-7);
 * 3. the degraded → repaired lineage is readable from both ends (D-F6);
 * 4. a repair can be retired and the harvested original never can (rulings R17-2 / R17-3).
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  FIXTURE_FRAGMENT_CARDS,
  FragmentCardError,
  fixtureFragmentCardRepository,
  httpFragmentCardRepository,
} from "./fragment-card.repository";

const ORIGINAL = "frag_00000000products";
const REPAIR = "frag_00000000repair1";
const DORMANT = "frag_00000000pricing";

test("the card carries one control per slot kind", async () => {
  const repository = fixtureFragmentCardRepository();
  const card = await repository.get(ORIGINAL);
  const kinds = new Map(card.slots.map((slot) => [slot.key, slot.kind]));
  assert.equal(kinds.get("headline"), "text");
  assert.equal(kinds.get("art"), "image");
  // An href rides the node's text tag, so the MANIFEST is the only thing that remembers a slot
  // is a link target rather than copy.
  assert.equal(kinds.get("cta"), "href");
  assert.equal(kinds.get("visible"), "visibility");
});

test("section_index is where the band sat, not a position in the visible list", async () => {
  const repository = fixtureFragmentCardRepository();
  const visible = await repository.get(ORIGINAL);
  const hidden = await repository.get(DORMANT);
  // Both collections are numbered from one document-order counter (F3.0 M3), so the visible
  // indices have gaps on a page that hides something — 4 and 7, never 4 and 5.
  assert.equal(visible.sectionIndex, 4);
  assert.equal(hidden.sectionIndex, 7);
});

test("a hidden-on-source section says so, shows its evidence, and refuses activation with the reason", async () => {
  const repository = fixtureFragmentCardRepository();
  const card = await repository.get(DORMANT);
  assert.equal(card.status, "dormant");
  assert.equal(card.hiddenOnSource?.hidden, true);
  assert.ok(
    card.hiddenOnSource?.evidence.some((item) => item.includes("w-condition-invisible")),
  );
  assert.equal(card.activation.allowed, false);
  assert.equal(card.activation.reason, "no_preview");

  await assert.rejects(
    () => repository.activate(DORMANT),
    (error: unknown) =>
      error instanceof FragmentCardError && error.reason === "no_preview" && error.status === 409,
  );
});

test("an isolation render gives it a picture, and then a human may activate it", async () => {
  const repository = fixtureFragmentCardRepository();
  const pictured = await repository.generatePreview(DORMANT);
  assert.ok(pictured.previewPath);
  // P-7: an isolation render and a crop of the source site are not the same evidence, so the
  // card keeps them distinguishable.
  assert.equal(pictured.previewBasis, "isolation_render");
  assert.equal(pictured.activation.allowed, true);

  const woken = await repository.activate(DORMANT);
  assert.equal(woken.status, "approved");
  // It is no longer hidden, so it is no longer in the list of things to activate.
  assert.deepEqual(await repository.listDormant(), []);
});

test("a preview is attached once", async () => {
  const repository = fixtureFragmentCardRepository();
  await repository.generatePreview(DORMANT);
  await assert.rejects(
    () => repository.generatePreview(DORMANT),
    (error: unknown) => error instanceof FragmentCardError && error.reason === "preview_present",
  );
});

test("the lineage reads from both ends", async () => {
  const repository = fixtureFragmentCardRepository();
  const original = await repository.get(ORIGINAL);
  assert.equal(original.degraded, true);
  assert.equal(original.degradedReason, "dead_height");
  // The reason CODE is not what a human reads; the note is what the decision turns on.
  assert.ok(original.degradedNote?.includes("artificial scroll height"));
  assert.deepEqual(
    original.repairs.map((entry) => entry.fragmentId),
    [REPAIR],
  );

  const repair = await repository.get(REPAIR);
  assert.equal(repair.derivedFrom, ORIGINAL);
  assert.ok(repair.derivedReason?.includes("repair rung 3"));
  assert.equal(repair.repairsWhat?.label, "Products");
  assert.equal(repair.repairsWhat?.degraded, true);
});

test("a repair can be retired and the harvested original never can", async () => {
  const repository = fixtureFragmentCardRepository();
  const original = await repository.get(ORIGINAL);
  assert.equal(original.retirement.allowed, false);
  assert.equal(original.retirement.reason, "not_a_repair");
  await assert.rejects(
    () => repository.retire(ORIGINAL),
    (error: unknown) => error instanceof FragmentCardError && error.reason === "not_a_repair",
  );
  // …and it is still there, still the evidence.
  assert.equal((await repository.get(ORIGINAL)).status, "approved");

  const retired = await repository.retire(REPAIR);
  assert.equal(retired.status, "deprecated");
  assert.equal((await repository.get(ORIGINAL)).repairs[0]?.status, "deprecated");
});

test("the fixture seed is a valid card set", () => {
  assert.equal(FIXTURE_FRAGMENT_CARDS.length, 3);
});

// --- the HTTP adapter -------------------------------------------------------

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const WIRE_CARD = {
  fragment_id: DORMANT,
  label: "Proof — Pricing",
  section_role: "proof",
  status: "dormant",
  page_url: "https://insighthealth.example/",
  section_index: 7,
  preview: { path: null, basis: null },
  slots: [{ key: "headline", kind: "text", fallback: "Pricing" }],
  degraded: false,
  hidden_on_source: { hidden: true, evidence: ["class token 'hide'"] },
  activation: {
    activatable: false,
    reason: "no_preview",
    message: "Generate an isolation render and then decide.",
  },
  retirement: { retirable: false, reason: "not_a_repair", message: null },
};

test("the HTTP adapter parses the backend's card and calls the four routes", async () => {
  const seen: { url: string; method: string }[] = [];
  const repository = httpFragmentCardRepository({
    baseUrl: "/api/clue",
    fetchImpl: async (input, init) => {
      seen.push({ url: String(input), method: init?.method ?? "GET" });
      if (String(input).endsWith("/web/fragments/dormant")) {
        return respond({ sections: [WIRE_CARD] });
      }
      return respond(WIRE_CARD);
    },
  });

  const card = await repository.get(DORMANT);
  assert.equal(card.fragmentId, DORMANT);
  assert.equal(card.sectionIndex, 7);
  assert.equal(card.previewPath, null);
  assert.equal(card.activation.allowed, false);
  assert.equal(card.activation.reason, "no_preview");
  assert.deepEqual(card.hiddenOnSource, { hidden: true, evidence: ["class token 'hide'"] });

  assert.equal((await repository.listDormant()).length, 1);
  await repository.generatePreview(DORMANT);
  await repository.activate(DORMANT);
  await repository.retire(DORMANT);

  assert.deepEqual(seen, [
    { url: `/api/clue/web/fragments/${DORMANT}`, method: "GET" },
    { url: "/api/clue/web/fragments/dormant", method: "GET" },
    { url: `/api/clue/web/fragments/${DORMANT}/preview`, method: "POST" },
    { url: `/api/clue/web/fragments/${DORMANT}/activate`, method: "POST" },
    { url: `/api/clue/web/fragments/${DORMANT}/retire`, method: "POST" },
  ]);
});

test("a refusal reaches the caller as the sentence the backend wrote", async () => {
  const repository = httpFragmentCardRepository({
    fetchImpl: async () =>
      respond(
        {
          detail: {
            code: "fragment.activation_no_preview",
            reason: "no_preview",
            message:
              "fragment frag_x is hidden on its source site and carries no preview image",
            fragment_id: "frag_x",
          },
        },
        409,
      ),
  });
  await assert.rejects(
    () => repository.activate("frag_x"),
    (error: unknown) =>
      error instanceof FragmentCardError &&
      error.status === 409 &&
      error.reason === "no_preview" &&
      error.code === "fragment.activation_no_preview" &&
      error.message.includes("no preview image"),
  );
});
