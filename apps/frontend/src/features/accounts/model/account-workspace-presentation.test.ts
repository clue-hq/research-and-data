import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { AccountArtifactSchema, WorkspaceActivitySchema } from "./account-workspace";
import { accountArtifacts, activityPresentation, artifactDisplayType, artifactTypeLabels, artifactTypeOptions, filterAccountActivity, filterAccountArtifacts, formatAccountDate, insightHeaderSummary } from "./account-workspace-presentation";
import { openAiWorkspaceFixture } from "../data/account-workspace.fixture";
import { zafranWorkspaceFixture } from "../data/zafran/insights";
import { fixtureAccountWorkspaceRepository } from "../data/account-workspace.repository";

test("Insights shows counts without rewriting or deleting source date metadata", () => {
  const original = [...zafranWorkspaceFixture.insightSummary];
  assert.deepEqual(insightHeaderSummary(original), ["21 insights", "5 people"]);
  assert.ok(original.some((label) => label === "Researched 2 Sep 2026"));
  assert.deepEqual(zafranWorkspaceFixture.insightSummary, original);
  assert.equal(formatAccountDate("2026-09-02T00:15:00.000Z"), "2 Sept 2026");
});

test("artifact types include ads, landing pages and the existing document formats", () => {
  assert.deepEqual(artifactTypeOptions.map(({ value }) => value), ["all", "ad", "web", "document", "presentation", "email"]);
  for (const type of ["ad", "web", "document", "presentation", "email"]) {
    assert.ok(AccountArtifactSchema.safeParse({ ...openAiWorkspaceFixture.artifacts[0], type }).success);
  }
});

test("account artifacts never include an explicitly different account", async () => {
  const artifact = openAiWorkspaceFixture.artifacts[0]!;
  assert.deepEqual(accountArtifacts([artifact], "zafran-security"), []);
  assert.deepEqual(accountArtifacts([artifact], "openai"), [artifact]);
  assert.equal((await fixtureAccountWorkspaceRepository.get("zafran-security"))!.artifacts.length, 0);
  assert.equal(await fixtureAccountWorkspaceRepository.get("missing-account"), null);
});

test("legacy account-scoped payloads remain compatible", () => {
  const legacy = { ...openAiWorkspaceFixture.artifacts[0]!, accountId: undefined };
  assert.ok(AccountArtifactSchema.safeParse(legacy).success);
  assert.deepEqual(accountArtifacts([legacy], "openai"), [legacy]);
});

test("artifact type and search filters compose and reset without mutating records", () => {
  const artifacts = openAiWorkspaceFixture.artifacts;
  assert.equal(filterAccountArtifacts(artifacts, { type: "ad" }).length, 2);
  assert.deepEqual(filterAccountArtifacts(artifacts, { type: "web", search: " LANDING " }).map((a) => a.id), ["campaign-builder"]);
  assert.deepEqual(filterAccountArtifacts(artifacts, { type: "document" }), []);
  assert.deepEqual(filterAccountArtifacts(artifacts, { search: "nonexistent" }), []);
  assert.equal(filterAccountArtifacts(artifacts, { type: "all", search: "" }).length, 3);
  assert.equal(artifacts.length, 3);
});

test("sorting uses actual timestamps or names, not fabricated last-viewed dates", () => {
  const original = openAiWorkspaceFixture.artifacts;
  const records = original.map((a, index) => ({ ...a, updatedAt: `2026-09-0${index + 1}T12:00:00.000Z` }));
  assert.deepEqual(filterAccountArtifacts(records).map((a) => a.id), ["campaign-builder", "insight-report", "finance-review"]);
  assert.deepEqual(filterAccountArtifacts(original, { sort: "name" }).map((a) => a.title), ["10x revenue ad", "landing page builder", "print ad"]);
  assert.deepEqual(filterAccountArtifacts(original), original);
});

test("activity identifies recorded people and Clue without using the current owner as a fallback", () => {
  const person = WorkspaceActivitySchema.parse({ id: "person-event", kind: "artifact", text: "Created an ad", action: "created an ad", timeLabel: "1h ago", actor: { type: "person", id: "person-1", name: "Priya Shah" } });
  assert.deepEqual(activityPresentation(person), { actorType: "person", actorName: "Priya Shah", action: "created an ad" });
  assert.deepEqual(activityPresentation(openAiWorkspaceFixture.activity[0]!), { actorType: "clue", actorName: "Clue", action: "added 14 new contacts" });
  assert.deepEqual(activityPresentation({ id: "unknown", kind: "summary", text: "Account updated", timeLabel: "1h ago" }), { actorType: undefined, actorName: undefined, action: "Account updated" });
});

test("activity retains optional user profile data even when the feed uses a person icon", () => {
  const event = { id: "person-event", kind: "artifact", text: "Created an ad", timeLabel: "1h ago", actor: { type: "person", id: "person-1", name: "Priya Shah", avatarUrl: "https://images.example.com/priya.png" } };
  const parsed = WorkspaceActivitySchema.parse(event);
  assert.equal(parsed.actor?.type === "person" && parsed.actor.avatarUrl, event.actor.avatarUrl);
  assert.ok(WorkspaceActivitySchema.safeParse({ ...event, actor: { ...event.actor, avatarUrl: undefined } }).success);
  assert.ok(WorkspaceActivitySchema.safeParse({ ...event, actor: { ...event.actor, avatarUrl: "/avatars/workspace-user.png" } }).success);
});

test("activity uses equally small Clue and single-person icons beside the recorded actor", () => {
  const screen = readFileSync(new URL("../components/account-activity-feed.tsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../components/account-library.module.css", import.meta.url), "utf8");
  assert.match(screen, /actorType === "clue"/);
  assert.match(screen, /src="\/icons\/projects\/clue-assistant\.svg"/);
  assert.match(screen, /const ACTIVITY_ICON_SIZE = 14/);
  assert.match(screen, /<Image alt="Clue"[^>]*height=\{ACTIVITY_ICON_SIZE\}[^>]*width=\{ACTIVITY_ICON_SIZE\}/);
  assert.match(screen, /<UserRound aria-hidden="true" size=\{ACTIVITY_ICON_SIZE\}/);
  assert.match(css, /\.actorMark \{ height: 14px; object-fit: contain; width: 14px; \}/);
  assert.doesNotMatch(screen, /ContactAvatar/);
  assert.doesNotMatch(screen, /src=\{account\.owner/);
});

test("activity filters actor types and sorts timestamped events newest first", () => {
  const base = { id: "a", kind: "updated" as const, text: "Updated account", timeLabel: "Today" };
  const events = [
    { ...base, occurredAt: "2026-09-02T10:00:00.000Z", actor: { type: "clue" as const } },
    { ...base, id: "b", occurredAt: "2026-09-03T10:00:00.000Z", actor: { type: "person" as const, id: "owner", name: "Priya Shah" } },
  ];
  assert.deepEqual(filterAccountActivity(events, "all").map((a) => a.id), ["b", "a"]);
  assert.deepEqual(filterAccountActivity(events, "clue").map((a) => a.id), ["a"]);
  assert.deepEqual(filterAccountActivity(events, "person").map((a) => a.id), ["b"]);
  assert.equal(filterAccountActivity(zafranWorkspaceFixture.activity, "person").length, 1);
  const partialDates = [events[0]!, { ...base, id: "undated" }, events[1]!];
  assert.deepEqual(filterAccountActivity(partialDates, "all"), partialDates);
});

test("research activity keeps the supplied events and dates beneath the actor presentation", () => {
  const researchActivity = zafranWorkspaceFixture.activity.filter((a) => !a.isSample);
  assert.deepEqual(researchActivity.map((a) => [a.text, a.timeLabel]), [
    ["Committee confirmed", "2 Sep 2026"], ["Account researched", "2 Sep 2026"], ["Person research", "1 Sep 2026"],
  ]);
  assert.ok(researchActivity.every((a) => activityPresentation(a).actorName === "Clue"));
});

test("one explicitly marked owner example demonstrates the person icon without inventing an event time", async () => {
  const workspace = await fixtureAccountWorkspaceRepository.get("zafran-security");
  const examples = workspace!.activity.filter((item) => item.isSample);
  assert.equal(examples.length, 1);
  assert.equal(examples[0]!.actor?.type, "person");
  assert.equal(activityPresentation(examples[0]!).actorName, "Aakash Shrivastava");
  assert.equal(examples[0]!.timeLabel, "Sample");
  assert.equal(examples[0]!.occurredAt, undefined);
  const screen = readFileSync(new URL("../components/account-activity-feed.tsx", import.meta.url), "utf8");
  assert.match(screen, /item\.isSample \? <span>Sample<\/span>/);
});

test("the account library uses themed filters, accessible previews and a plain activity list", () => {
  const screen = readFileSync(new URL("../components/account-library-screens.tsx", import.meta.url), "utf8");
  const shell = readFileSync(new URL("../components/account-workspace-shell.tsx", import.meta.url), "utf8");
  const insights = readFileSync(new URL("../components/account-workspace-screens.tsx", import.meta.url), "utf8");
  assert.match(screen, /AccountFilterSelect ariaLabel="Filter artifacts by type"/);
  assert.match(screen, /AccountFilterSelect ariaLabel="Sort artifacts"/);
  assert.match(screen, /<Dialog\.Root/);
  assert.match(screen, /<Dialog\.Close/);
  assert.match(screen, /No matching artifacts/);
  assert.match(screen, /No artifacts yet/);
  assert.match(screen, /<AccountActivityFeed items=\{items\}/);
  assert.doesNotMatch(screen, /openai-detail\.svg|Last viewed|account\.owner/);
  // Ruling R8: the stamp defaults to the account's, and a contact page passes its own.
  assert.match(shell, /lastModifiedAt = account\.lastModifiedAt/);
  assert.match(shell, /dateTime=\{lastModifiedAt\}/);
  assert.match(insights, /insightHeaderSummary\(workspace\.insightSummary\)/);
  assert.match(insights, /summary=\{workspace\.insightSummary\}/);
});

test("activity filtering is a tick-free segmented selector and the rail shares the feed", () => {
  const screen = readFileSync(new URL("../components/account-library-screens.tsx", import.meta.url), "utf8");
  const activity = screen.slice(screen.indexOf("export function AccountActivityScreen("));
  const detail = readFileSync(new URL("../components/account-detail-screen.tsx", import.meta.url), "utf8");
  const feed = readFileSync(new URL("../components/account-activity-feed.tsx", import.meta.url), "utf8");
  assert.match(activity, /aria-label="Filter activity by actor"[^>]*role="group"/);
  assert.match(activity, /aria-pressed=\{actor === option\.value\}/);
  assert.match(activity, /onClick=\{\(\) => setActor\(option\.value\)\}/);
  assert.doesNotMatch(activity, /AccountFilterSelect|Select\.ItemIndicator|check\.svg/);
  assert.match(detail, /<AccountActivityFeed compact items=\{account\.activity\} label="Recent account activity"/);
  assert.doesNotMatch(detail, /function ActivityIcon\(/);
  assert.match(feed, /activityPresentation\(item\)/);
  assert.match(feed, /compact \? styles\.railFeed/);
});

// Review finding K1-1: the backend labels a site built for an account `"site"`, and the frontend's
// list did not have it, so one site artifact made the whole Insights / Artifacts / Activity read fail.
// A site is a landing page to the marketer: it shows exactly as one (label, icon, the "Landing pages"
// filter); no new filter or label was designed, so none is invented.
test("a site artifact parses and shows as a landing page: label, icon type, filter and sort", () => {
  const base = openAiWorkspaceFixture.artifacts[0]!;
  const site = { ...base, id: "site-1", title: "Garner microsite", type: "site" as const };
  const web = { ...base, id: "web-1", title: "Old landing page", type: "web" as const };
  const ad = { ...base, id: "ad-1", title: "Banner", type: "ad" as const };
  assert.ok(AccountArtifactSchema.safeParse(site).success, "the read no longer fails on a site");
  assert.equal(artifactTypeLabels.site, "Landing page");
  assert.equal(artifactDisplayType("site"), "web");
  assert.equal(artifactDisplayType("ad"), "ad");
  assert.deepEqual(filterAccountArtifacts([site, web, ad], { type: "web" }).map((a) => a.id).sort(), ["site-1", "web-1"]);
  assert.deepEqual(filterAccountArtifacts([site, web, ad], { search: "landing page" }).map((a) => a.id).sort(), ["site-1", "web-1"]);
  assert.deepEqual(artifactTypeOptions.map(({ value }) => value), ["all", "ad", "web", "document", "presentation", "email"], "no new filter");
  const sorted = filterAccountArtifacts([web, ad, site], { sort: "type" }).map((a) => a.id);
  assert.deepEqual(sorted, ["ad-1", "site-1", "web-1"], "sites sort with landing pages");
});
