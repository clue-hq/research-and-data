import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const applicationContractPath = new URL(
  "../../../../packages/design-system/source/production/application.json",
  import.meta.url,
);
const accountComponentsPath = new URL(
  "./account-components.module.css",
  import.meta.url,
);
const accountDetailsPath = new URL(
  "./account-detail-primitives.tsx",
  import.meta.url,
);
const accountDetailModelPath = new URL(
  "../model/account-detail.ts",
  import.meta.url,
);
const contactProfilePath = new URL(
  "./contact-profile-content.tsx",
  import.meta.url,
);

type ApplicationContract = {
  source: { fileKey: string; role: string };
  tokens: Array<{ name: string; value: number | string }>;
};

const contract = JSON.parse(
  readFileSync(applicationContractPath, "utf8"),
) as ApplicationContract;
const accountCss = readFileSync(accountComponentsPath, "utf8");
const accountDetails = readFileSync(accountDetailsPath, "utf8");
const accountDetailModel = readFileSync(accountDetailModelPath, "utf8");
const contactProfile = readFileSync(contactProfilePath, "utf8");

function token(name: string) {
  return contract.tokens.find((item) => item.name === name)?.value;
}

test("account workspace geometry is sourced from the production Clue file", () => {
  assert.equal(contract.source.fileKey, "NcLl2r0dzVDN28xAQCwvM1");
  assert.equal(contract.source.role, "production-shell-geometry");
  assert.equal(token("dimension/header/action-bar-height"), 58);
  assert.equal(token("dimension/table/header-height"), 48);
  assert.equal(token("dimension/table/row-comfortable"), 56);
  assert.equal(token("dimension/table/row-spacious"), 64);
});

test("record pages preserve original rails and previews around a 720px reading measure", () => {
  // The article includes 32px padding on each side of the reading column.
  assert.match(accountCss, /max-width:\s*784px/);
  assert.match(accountCss, /width:\s*clamp\(360px,\s*38\.06%,\s*548px\)/);
  assert.match(accountCss, /width:\s*min\(727px,\s*100vw\)/);
  assert.match(accountCss, /height:\s*calc\(100dvh\s*-\s*56px\)/);
  assert.match(accountCss, /padding:\s*22px 16px 18px/);
  assert.doesNotMatch(accountCss, /\.recordSurface \.badge|\.previewDrawer \.badge/);
  assert.doesNotMatch(accountCss, /\.detailRail \.coreHeading/);
  assert.match(accountDetails, /flex w-40 shrink-0 items-center gap-2/);
  assert.match(accountDetails, /<DetailsRow icon=\{UserRound\} label="Owner">/);
  assert.match(contactProfile, /flex w-40 shrink-0 items-center gap-2/);
});

test("researched previews and full pages share the same sourced content renderer", () => {
  const preview = readFileSync(new URL("./account-preview-drawer.tsx", import.meta.url), "utf8");
  const overview = readFileSync(new URL("./account-research-overview.tsx", import.meta.url), "utf8");
  assert.match(preview, /account\.overviewDisplay \? \(/);
  assert.match(preview, /<AccountResearchBody account=\{account\}/);
  assert.match(overview, /<AccountResearchBody account=\{account\}/);
  assert.match(overview, /sections=\{sectionsBeforeCommittee\}/);
  assert.match(overview, /sections=\{sectionsAfterCommittee\}/);
  assert.match(overview, /evidence=\{account\.researchEvidence\}/);
  assert.match(preview, /account\.summaryParagraphs\.length > 0/);
  assert.match(preview, /account\.businessParagraphs\.length > 0/);
});

test("contact full pages keep properties above research without a new details rail", () => {
  const contactPage = readFileSync(new URL("./contact-full-screen.tsx", import.meta.url), "utf8");
  assert.match(contactPage, /<ContactProfileContent contact=\{contact\} \/>/);
  assert.doesNotMatch(contactPage, /RecordDetailsRail|showDetails=\{false\}/);
  assert.match(contactProfile, />\s*Core\s*</);
});

test("contact profiles retain workspace navigation and all account sections", () => {
  const contactPage = readFileSync(new URL("./contact-full-screen.tsx", import.meta.url), "utf8");
  const contactRoute = readFileSync(new URL("../../../app/(protected)/accounts/[accountId]/contacts/[contactId]/page.tsx", import.meta.url), "utf8");
  const workspace = readFileSync(new URL("./account-workspace-shell.tsx", import.meta.url), "utf8");
  const layout = readFileSync(new URL("./accounts-layout-shell.tsx", import.meta.url), "utf8");

  assert.match(contactPage, /<AccountWorkspaceShell\s+account=\{account\}\s+activeTab="contacts"/);
  assert.match(contactPage, /showDetailsToggle=\{false\}/);
  assert.match(contactPage, /copyLinkLabel="Copy contact link"/);
  assert.doesNotMatch(contactPage, /<header|<ApplicationShell/);
  assert.match(contactRoute, /getAccountDetails\(accountId\)/);
  assert.match(contactRoute, /if \(!account \|\| !contact\) notFound\(\)/);
  assert.match(contactRoute, /<ContactFullScreen account=\{account\} contact=\{contact\}/);
  assert.match(layout, /<ApplicationShell activeHref="\/accounts">/);
  assert.match(workspace, /aria-label="Account sections"/);
  assert.match(workspace, /aria-current=\{active \? "page" : undefined\}/);
  for (const label of ["Overview", "Contacts", "Insights", "Artifacts", "Activity"]) {
    assert.ok(workspace.includes(`label: "${label}"`));
  }
});

test("overview contact rail shows three people and See all without extra count metadata", () => {
  const screen = readFileSync(new URL("./account-detail-screen.tsx", import.meta.url), "utf8");
  const panel = screen.slice(screen.indexOf("function ContactsPanel("), screen.indexOf("function ActivityPanel("));
  assert.match(panel, />Contacts<\/h2>/);
  assert.match(panel, /account\.contacts\.slice\(0, 3\)\.map/);
  assert.match(panel, /See all/);
  assert.doesNotMatch(panel, /contacts\.length|emailVerified|with verified email/);
});

test("fit evidence uses intact source text in an aligned, responsive table", () => {
  const renderer = readFileSync(new URL("./research-content.tsx", import.meta.url), "utf8");
  const researchCss = readFileSync(new URL("./account-research.module.css", import.meta.url), "utf8");
  assert.match(renderer, /<th scope="row">\{item\.h2\}<\/th>/);
  assert.match(renderer, /item\.body\.map\(\(sentence, index\)/);
  assert.match(renderer, /<FitBadge fit=\{overallFit\}/);
  assert.match(researchCss, /@container \(max-width: 520px\)/);
});

test("account controls consume canonical component and motion tokens", () => {
  assert.match(
    accountCss,
    /var\(--clue-ds-product-component-button-sm-height\)/,
  );
  assert.match(
    accountCss,
    /var\(--clue-ds-product-component-button-md-radius\)/,
  );
  assert.match(
    accountCss,
    /var\(--clue-ds-product-motion-duration-fast\)/,
  );
});

test("account details separate core and configurable fields behind progressive disclosure", () => {
  assert.match(accountDetails, />\s*Core\s*</);
  assert.match(accountDetails, />\s*Custom\s*</);
  assert.match(accountDetails, /aria-expanded=\{expanded\}/);
  assert.match(accountDetails, /"See all"/);
  assert.ok(
    accountDetails.indexOf('label="Contacts"') <
      accountDetails.indexOf("primaryCustomFields.length > 0"),
    "Contacts should render before the Custom section",
  );
  assert.ok(
    accountDetails.indexOf("primaryCustomFields.length > 0") <
      accountDetails.indexOf("aria-expanded={expanded}"),
    "Custom should render before the disclosure control",
  );
  assert.match(accountDetails, /from "lucide-react"/);
  assert.match(accountDetails, /BriefcaseBusiness/);
  assert.match(accountDetails, /industryBadgeTones/);
  assert.match(accountDetails, /badgeToneOrange/);
  assert.match(accountDetails, /label="Headcount"/);
  assert.match(accountDetails, /icon=\{AtSign\}/);
  assert.match(accountDetails, /href=\{`\/accounts\/\$\{accountId\}\/contacts`\}/);
  assert.match(accountDetails, /label="Date Created"/);
  assert.match(accountDetails, /label="Last Modified"/);
  assert.match(accountDetails, /label="Fit Score"/);
  assert.match(accountDetails, /FitScoreIndicator score=\{account\.fitScore\}/);
  assert.match(accountDetails, /formatAccountDate\(account\.createdAt\)/);
  assert.match(accountDetails, /formatAccountDate\(account\.lastModifiedAt\)/);
  assert.match(accountDetails, /aria-label="Custom variable"/);
  assert.match(accountDetails, /<Zap/);
  assert.doesNotMatch(accountDetails, /label="Size"/);
  assert.doesNotMatch(accountDetails, /Referral fit/);
  assert.doesNotMatch(accountDetails, /Direct access fit/);
  assert.match(accountDetailModel, /AccountOwnerSchema/);
  assert.match(accountDetailModel, /customFields:/);
});

test("contact profile reuses the refreshed account detail icon and badge language", () => {
  assert.match(contactProfile, /from "lucide-react"/);
  assert.match(contactProfile, /strokeWidth=\{1\.5\}/);
  assert.match(contactProfile, /icon=\{BriefcaseBusiness\}/);
  assert.match(contactProfile, /icon=\{RadioTower\}/);
  assert.match(contactProfile, /icon=\{AtSign\}/);
  assert.match(contactProfile, /personaToneClasses\[contact\.personaTone\]/);
  assert.match(contactProfile, /components\.badgePositive/);
  assert.match(contactProfile, /underline-offset-2/);
  assert.doesNotMatch(contactProfile, /AccountFlowIcon/);
  assert.doesNotMatch(contactProfile, /\/logos\/(linkedin|x)\.svg/);
});
