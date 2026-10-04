import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { zafranAccountDetailFixture } from "./account";
import { nickFisherFixture } from "./contacts";
import { zafranWorkspaceFixture } from "./insights";

const committedSpec = readFileSync(
  path.join(
    process.cwd(),
    "src/features/accounts/data/zafran/FRONTEND-SPEC-ZAFRAN.md",
  ),
  "utf8",
);

function section(
  page: NonNullable<typeof zafranWorkspaceFixture.insightsDisplay>,
  key: string,
) {
  const result = page.sections.find((entry) => entry.key === key);
  assert.ok(result, `Expected ${key} section`);
  return result;
}

test("the committed Zafran source remains the exact supplied Markdown", () => {
  assert.equal(
    createHash("sha256").update(committedSpec).digest("hex"),
    "8c0e9c84d0d69a2105a1bc7d40590ec8cbe39f063b9422324336d2042db67967",
  );
});

test("Insights exposes every source item without shortened replacement copy", () => {
  const insights = zafranWorkspaceFixture.insightsDisplay!;
  assert.deepEqual(
    insights.sections.map((entry) => entry.items.length),
    // The trailing 0 is Miscellaneous: an honest empty section, added 2026-09-27 (296922df1).
    [4, 3, 3, 3, 5, 3, 0],
  );
  assert.equal(section(insights, "miscellaneous").empty, true);

  const firstSignal = section(insights, "buying-signals").items[0]!;
  assert.equal(
    firstSignal.h2,
    "They have been trying to hire an ABM owner for 77 days and have not.",
  );
  assert.match(
    firstSignal.body[0]!.text,
    /own ABM from the ground up: 1:1 programs for your most strategic targets, 1:few cluster plays for high-potential segments, and scaled 1:many motions where volume matters/,
  );
  assert.equal(
    firstSignal.body[1]!.text,
    "What it means for us: the work this seat was created for is the work we do, and nobody is doing it.",
  );

  const funding = section(insights, "money-and-momentum").items[0]!;
  assert.match(
    funding.body[0]!.text,
    /The full ladder: \$5\.5M seed and a \$25M venture round \(March 2024\), \$40M Series B \(September 2024\), \$60M Series C \(December 2025\)/,
  );
});

test("Account Overview exposes the complete supplied narrative and sections", () => {
  const overview = zafranAccountDetailFixture.overviewDisplay!;
  assert.deepEqual(
    overview.sections.map((entry) => entry.items.length),
    [0, 7, 3, 5, 3],
  );

  const intro = section(overview, "what-they-do").intro!;
  assert.match(
    intro[0]!.text,
    /works out which vulnerabilities an attacker could actually exploit, and drives the fix through tools already in place: Jira, ServiceNow and the existing security controls/,
  );
  assert.match(
    intro[1]!.text,
    /It has 167 employees, has raised \$130\.5M across four rounds/,
  );
  assert.ok(
    intro[1]!.segments?.some((segment) =>
      segment.claimIds.includes("zafran-headcount-record"),
    ),
  );
});

test("Nick Fisher's page keeps all supplied research and copy-lines", () => {
  const contact = nickFisherFixture.contactDisplay!;
  assert.deepEqual(
    contact.sections.map((entry) => entry.items.length),
    // The trailing 0 is Miscellaneous: an honest empty section, added 2026-09-27 (296922df1).
    [4, 3, 5, 4, 4, 0],
  );
  assert.equal(section(contact, "miscellaneous").empty, true);

  const whyThisPerson = section(contact, "why-this-person");
  assert.equal(
    whyThisPerson.items[2]!.h2,
    "He does his own customer research, and it shows in the messaging. That is a strength, and it tells you how to sell to him.",
  );
  assert.match(
    whyThisPerson.items[2]!.body[0]!.text,
    /The limit is scale: he can do that for Zafran's message once, not for every target account\./,
  );
  assert.equal(
    whyThisPerson.items[2]!.sendLine?.text,
    '"You went through dozens of Gong calls to find the 96% line. That is what we do for each of your target accounts, with the source on every line." On the landing page, show one per-account insight with its citation visible, so he can check it the way he checks Gong.',
  );

  const cocktail = section(contact, "openers").items[1]!;
  assert.match(
    cocktail.body[0]!.text,
    /I invest a lot in top quality liquors… as well as equipment that I use, whether it's a smoking gun or immersion circulator/,
  );
  assert.equal(
    cocktail.sendLine?.channel,
    "In your email",
  );
});
