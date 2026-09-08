import assert from "node:assert/strict";
import test from "node:test";
import { zafranAccountDetailFixture } from "./account";

function overviewSection(key: string) {
  const result = zafranAccountDetailFixture.overviewDisplay?.sections.find(
    (section) => section.key === key,
  );
  assert.ok(result, `Expected ${key} overview section`);
  return result;
}

test("overview evidence follows sentence punctuation", () => {
  const introduction = overviewSection("what-they-do").intro;
  assert.ok(introduction);
  assert.equal(
    introduction[0]?.segments?.[0]?.text.endsWith("controls."),
    true,
  );
  assert.equal(
    introduction[0]?.segments?.[1]?.text.startsWith(" The company's"),
    true,
  );

  const whyNow = overviewSection("why-now");
  assert.equal(whyNow.items.every((item) => item.inlineLead), true);
  assert.deepEqual(
    whyNow.items.map((item) => `${item.h2}${item.body[0]?.text ?? ""}`),
    [
      "The ABM seat has been open 77 days. The program exists on paper only.",
      'Director of Alliances posted 1 Sep 2026, a second GTM motion starting "from scratch".',
      "Nine months post Series C, two strategic investors added in 2026. Pipeline expectations for the year are set.",
    ],
  );
  assert.equal(whyNow.items[0]?.body[0]?.segments?.[0]?.text, ".");
  assert.equal(
    whyNow.items[1]?.body[0]?.segments?.[0]?.text.endsWith('".'),
    true,
  );
});
