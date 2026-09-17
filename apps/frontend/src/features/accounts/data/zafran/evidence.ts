import type { ResearchEvidence } from "../../model/research-display";

function favicon(domain: string) {
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=32`;
}

function source(
  claimId: string,
  sourceDomain: string,
  sourceUrl: string,
  verifiedAt: string,
  options: Partial<ResearchEvidence> = {},
): ResearchEvidence {
  return {
    claimId,
    sourceUrl,
    sourceDomain,
    faviconUrl: favicon(sourceDomain),
    title: null,
    quote: null,
    publishedAt: null,
    verifiedAt,
    verificationKind: "verified",
    mediaTimestamp: null,
    provider: null,
    outreachSafe: true,
    ...options,
  };
}

function privateRecord(
  claimId: string,
  verifiedAt: string,
  options: Partial<ResearchEvidence> = {},
): ResearchEvidence {
  return {
    claimId,
    sourceUrl: null,
    sourceDomain: null,
    faviconUrl: null,
    title: "Verified private record",
    quote: null,
    publishedAt: null,
    verifiedAt,
    verificationKind: "verified",
    mediaTimestamp: null,
    provider: null,
    outreachSafe: true,
    ...options,
  };
}

export const zafranResearchEvidence: ResearchEvidence[] = [
  source(
    "ashby-abm-role",
    "jobs.ashbyhq.com",
    "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf",
    "2026-09-02",
    {
      title: "Senior Manager, ABM & Integrated Campaigns",
      quote:
        "Own ABM from the ground up: 1:1 programs, 1:few cluster plays, and scaled 1:many motions.",
      publishedAt: "2026-06-17",
    },
  ),
  source(
    "ashby-alliances-role",
    "jobs.ashbyhq.com",
    "https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17",
    "2026-09-02",
    {
      title: "Director of Alliances",
      quote: "Build that engine from scratch, anchored in global systems integrators.",
      publishedAt: "2026-09-01",
    },
  ),
  source(
    "ashby-job-board",
    "jobs.ashbyhq.com",
    "https://jobs.ashbyhq.com/zafran-security",
    "2026-09-02",
    {
      title: "Zafran Security open roles",
      quote: "27 open roles across sales, R&D, marketing, customer success and operations.",
    },
  ),
  source(
    "ashby-bdr-role",
    "jobs.ashbyhq.com",
    "https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13",
    "2026-09-02",
    {
      title: "Business Development Representative",
      quote:
        "Use Salesforce, LinkedIn Sales Navigator, ZoomInfo and Outreach with regular NYC office presence.",
      publishedAt: "2026-08-19",
    },
  ),
  source(
    "crunchbase-funding",
    "crunchbase.com",
    "https://www.crunchbase.com/organization/zafran",
    "2026-08-22",
    {
      title: "Zafran Security funding history",
      quote: "$130.5M raised across four rounds.",
    },
  ),
  source(
    "zafran-series-c",
    "zafran.io",
    "https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai",
    "2026-09-02",
    {
      title: "Zafran triples ARR in $60M round",
      quote:
        "More than tripled ARR and uses existing security tools to prove 99% of critical vulnerabilities are not exploitable.",
      publishedAt: "2025-12-02",
    },
  ),
  source(
    "zafran-amex-investment",
    "zafran.io",
    "https://www.zafran.io/resources/zafran-announces-strategic-investment-from-amex-ventures",
    "2026-09-02",
    {
      title: "Strategic investment from Amex Ventures",
      publishedAt: "2026-02-24",
    },
  ),
  source(
    "zafran-cisco-investment",
    "zafran.io",
    "https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments",
    "2026-09-02",
    {
      title: "Strategic investment from Cisco Investments",
      publishedAt: "2026-07-22",
    },
  ),
  source(
    "zafran-homepage",
    "zafran.io",
    "https://www.zafran.io/",
    "2026-09-02",
    {
      title: "Zafran Security",
      quote: "Customer proof includes CISOs at Kraft Heinz, Chipotle, Netskope and Ashland.",
    },
  ),
  source(
    "zafran-openai-customer",
    "zafran.io",
    "https://www.zafran.io/resources/openai-selects-zafran-for-trusted-access-for-cyber",
    "2026-09-02",
    {
      title: "OpenAI selects Zafran for Trusted Access for Cyber",
      quote: "OpenAI selects Zafran for Trusted Access for Cyber.",
    },
  ),
  source(
    "zafran-platform",
    "zafran.io",
    "https://www.zafran.io/platform",
    "2026-09-02",
    {
      title: "Zafran platform",
      quote:
        "Prioritizes exploitable vulnerabilities and drives remediation through existing workflows.",
    },
  ),
  source(
    "zafran-about",
    "zafran.io",
    "https://www.zafran.io/about",
    "2026-09-02",
    {
      title: "About Zafran Security",
      quote: "Founded by Sanaz Yashar, Ben Seri and Snir Havdala.",
    },
  ),
  source(
    "ctech-growth",
    "calcalistech.com",
    "https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl",
    "2026-09-02",
    {
      title: "Cisco investing in Zafran Security",
      quote: "The development in AI is very fast, and we need more people.",
    },
  ),
  source(
    "zafran-product-marketing-role",
    "zafran.io",
    "https://www.zafran.io/open-positions/d67a7de0b50a4b7facfcb168db99148f",
    "2026-09-02",
    {
      title: "Director of Product Marketing",
      quote: "Positioning that resonates with CISOs, security practitioners, and business leaders.",
    },
  ),
  source(
    "zafran-ctem-workflow",
    "zafran.io",
    "https://www.zafran.io/ctem-academy/best-vulnerability-management-tools-of-2026",
    "2026-09-02",
    {
      title: "Best vulnerability management tools of 2026",
      quote: "Routes remediation through Jira and ServiceNow.",
    },
  ),
  source(
    "zafran-overnight-proof",
    "zafran.io",
    "https://www.zafran.io/open-positions/8c2f9f9808bf41349208e2a3d376f40e",
    "2026-09-02",
    {
      title: "Zafran Security open position",
      quote: "De-risks 90% of critical vulnerabilities overnight.",
    },
  ),
  source(
    "zafran-remops-proof",
    "zafran.io",
    "https://www.zafran.io/resources/beyond-the-hype-remediation-operations-that-delivers-results-yi2h5",
    "2026-09-02",
    {
      title: "Remediation operations that deliver results",
      quote: "87% cut in time per vulnerability.",
    },
  ),
  source(
    "linkedin-vari-hiring",
    "linkedin.com",
    "https://www.linkedin.com/posts/varinderkaur_our-marketing-team-at-zafran-security-is-activity-7462208819037691907-EQ8X",
    "2026-09-01",
    {
      title: "Vari Kaur is hiring an ABM leader",
      quote:
        "Work shoulder-to-shoulder with Sales to go after the accounts that matter most.",
      publishedAt: "2026-05-18",
    },
  ),
  source(
    "linkedin-vari-profile",
    "linkedin.com",
    "https://www.linkedin.com/in/varinderkaur",
    "2026-08-22",
    {
      title: "Vari Kaur",
      quote: "Head of Growth Marketing with 6sense and Demandbase certifications.",
      verificationKind: "record",
    },
  ),
  source(
    "linkedin-nick-profile",
    "linkedin.com",
    "https://www.linkedin.com/in/nicholastfisher",
    "2026-08-22",
    {
      title: "Nick Fisher",
      quote: "VP of Marketing at Zafran Security since April 2024.",
      verificationKind: "record",
    },
  ),
  source(
    "linkedin-nick-criteria",
    "linkedin.com",
    "https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf",
    "2026-09-01",
    {
      title: "Why I joined Zafran Security",
      quote:
        "The decision to join a startup comes down to three basic criteria: market, product and people.",
    },
  ),
  source(
    "spotify-sanaz-interview",
    "podcasters.spotify.com",
    "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai",
    "2026-09-02",
    {
      title: "AI Summit with Sanaz Yashar",
      quote: "The biggest pain is we don't have enough operators.",
      publishedAt: "2025-08-10",
      mediaTimestamp: "05:14",
    },
  ),
  source(
    "linkedin-tom-profile",
    "linkedin.com",
    "https://www.linkedin.com/in/tomanthonyjr",
    "2026-08-22",
    {
      title: "Tom Anthony",
      quote: "SVP Global Sales at Zafran Security; previously Okta and Upbound.",
      verificationKind: "record",
    },
  ),
  source(
    "linkedin-ben-profile",
    "linkedin.com",
    "https://www.linkedin.com/in/ben-seri",
    "2026-08-22",
    {
      title: "Ben Seri",
      quote: "Co-Founder and CTO at Zafran Security; previously VP of Research at Armis.",
      verificationKind: "record",
    },
  ),
  source(
    "linkedin-zafran-company",
    "linkedin.com",
    "https://www.linkedin.com/company/zafran-security",
    "2026-08-22",
    {
      title: "Zafran Security on LinkedIn",
      quote: "New York headquarters with founders and R&D in Tel Aviv.",
      verificationKind: "record",
    },
  ),
  source(
    "globes-cisco-rumour",
    "globes.co.il",
    "https://en.globes.co.il/en/article-cisco-investing-in-not-acquiring-zafran-security-1001550210",
    "2026-09-02",
    {
      title: "Cisco investing in, not acquiring, Zafran Security",
      outreachSafe: false,
    },
  ),
  source(
    "ctech-cisco-rumour",
    "calcalistech.com",
    "https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl",
    "2026-09-02",
    {
      title: "Cisco and Zafran Security report",
      outreachSafe: false,
    },
  ),
  source(
    "linkedin-nick-hobby",
    "linkedin.com",
    "https://www.linkedin.com/posts/nicholastfisher_if-weve-worked-together-you-may-have-discovered-activity-6932337822636937217-ptV7",
    "2026-09-01",
    {
      title: "Nick Fisher on Cocktail Chemistry",
      quote: "Cocktail Chemistry is a long-running side project and published book.",
    },
  ),
  source(
    "youtube-cocktail",
    "youtube.com",
    "https://www.youtube.com/watch?v=8_YWBtq4eic",
    "2026-09-02",
    {
      title: "Supporting Cocktail Chemistry",
      quote:
        "I invest a lot in top-quality liquors and equipment, whether it's a smoking gun or immersion circulator.",
      mediaTimestamp: "00:05–00:30",
    },
  ),
  source(
    "simon-book",
    "simonandschuster.com",
    "https://www.simonandschuster.com/authors/Nick-Fisher/177280135",
    "2026-09-02",
    {
      title: "Nick Fisher, author",
      quote: "Author of Cocktail Chemistry: The Art and Science of Drinks from Iconic TV Shows and Movies.",
    },
  ),
  source(
    "zafran-x",
    "x.com",
    "https://x.com/Zafran_io",
    "2026-08-22",
    { title: "Zafran Security on X", verificationKind: "record" },
  ),
  privateRecord("zafran-revenue-estimate", "2026-08-22", {
    title: "Estimated revenue and IT-spend record",
    quote: "Revenue band $10–25M; estimated IT spend $7.6M.",
    verificationKind: "record",
  }),
  privateRecord("zafran-headcount-record", "2026-08-22", {
    title: "Company headcount record",
    quote: "167 employees.",
    verificationKind: "record",
  }),
  privateRecord("email-vari", "2026-08-31", {
    title: "Email verification",
    quote: "vari@zafran.io verified.",
  }),
  privateRecord("email-nick", "2026-08-31", {
    title: "Email verification",
    quote: "nick@zafran.io verified.",
  }),
  privateRecord("email-sanaz", "2026-09-02", {
    title: "Email verification",
    quote: "sanaz@zafran.io verified.",
  }),
  privateRecord("email-tom", "2026-09-02", {
    title: "Email verification",
    quote: "tom@zafran.io verified.",
  }),
];

export const zafranEvidenceById = new Map(
  zafranResearchEvidence.map((evidence) => [evidence.claimId, evidence]),
);
