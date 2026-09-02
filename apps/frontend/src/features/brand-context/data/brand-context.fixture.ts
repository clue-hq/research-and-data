import type { BrandContextWorkspace } from "../model/brand-context";

const knowledgeBody = `# Company Overview

Acme Inc. is a collaborative work management company that helps modern teams plan, track, and deliver their most important work.

- Founded: 2016
- Headquarters: San Francisco, California
- Industry: Software
- Employees: 450+
- Customers: 8,000+
- Website: acme.com

## Acme Flow

Acme Flow brings projects, goals, documents, and team conversations into one shared workspace. It gives every team a clear view of what is happening, who owns the next step, and how work connects to company priorities.

### Common use cases

- Marketing campaign planning
- Product launch coordination
- Sales enablement
- Client delivery
- Executive reporting`;

export const brandContextFixture: BrandContextWorkspace = {
  assets: [
    {
      category: "logo",
      createdAt: "2026-08-10T23:00:00.000Z",
      createdLabel: "A hour ago",
      description:
        "Logo of the company Clue, in black color, to be used on white backgrounds.",
      dimensions: "256×256px",
      id: "logo",
      name: "logo",
      origin: "kit",
      sizeBytes: 2202009,
      sizeLabel: "2.1 mb",
      type: "Image",
      visual: { imagePath: "/logos/clue-sidebar.svg", kind: "image" },
    },
    {
      category: "background",
      createdAt: "2026-08-10T22:58:00.000Z",
      createdLabel: "A hour ago",
      description: "Soft blue campaign background for light surfaces.",
      dimensions: "1600×900px",
      id: "bg",
      name: "bg",
      origin: "kit",
      sizeBytes: 2097152,
      sizeLabel: "2 mb",
      type: "Image",
      visual: { colors: ["#d9edff", "#f8fbff", "#b9dcff"], kind: "gradient" },
    },
    {
      category: "background",
      createdAt: "2026-08-10T22:56:00.000Z",
      createdLabel: "A hour ago",
      description: "Warm neutral background for editorial content.",
      dimensions: "1600×900px",
      id: "bg2",
      name: "bg2",
      origin: "kit",
      sizeBytes: 2097152,
      sizeLabel: "2 mb",
      type: "Image",
      visual: { colors: ["#ece9df", "#faf9f5", "#c8c2ad"], kind: "gradient" },
    },
    {
      category: "ai-generated",
      createdAt: "2026-08-10T22:54:00.000Z",
      createdLabel: "A hour ago",
      description: "Brand green background for campaign artwork.",
      dimensions: "1600×900px",
      id: "bg3",
      name: "bg3",
      origin: "kit",
      sizeBytes: 2097152,
      sizeLabel: "2 mb",
      type: "Image",
      visual: { colors: ["#b9c7ae", "#f2f5ed", "#66705f"], kind: "gradient" },
    },
    {
      category: "mockup",
      createdAt: "2026-08-10T22:52:00.000Z",
      createdLabel: "A hour ago",
      description: "Approved Clue campaign mockup.",
      dimensions: "1600×900px",
      id: "mockup",
      name: "mockup",
      origin: "kit",
      sizeBytes: 2097152,
      sizeLabel: "2 mb",
      type: "Image",
      visual: { imagePath: "/projects/home/abm-campaign.png", kind: "image" },
    },
  ],
  colorGroups: [
    {
      id: "background",
      label: "Background",
      swatches: [
        { id: "background-primary", label: "Primary", lightValue: "#FFFFFF", darkValue: "#0F1114" },
        { id: "background-secondary", label: "Secondary", lightValue: "#F8F9FB", darkValue: "#17191D" },
        { id: "background-tertiary", label: "Tertiary", lightValue: "#EEF0F3", darkValue: "#1F2328" },
        { id: "background-inverted", label: "Inverted", lightValue: "#1C2028", darkValue: "#ECEEF2" },
      ],
    },
    {
      id: "content",
      label: "Content",
      swatches: [
        { id: "content-primary", label: "Primary", lightValue: "#1C2028", darkValue: "#ECEEF2" },
        { id: "content-secondary", label: "Secondary", lightValue: "#5E636C", darkValue: "#ACB4BE" },
        { id: "content-knockout", label: "Knockout", lightValue: "#FFFFFF", darkValue: "#0F1114" },
      ],
    },
    {
      id: "accent",
      label: "Accent",
      swatches: [
        { id: "accent-primary", label: "Primary", lightValue: "#A6AD9D", darkValue: "#646B5C" },
        { id: "accent-secondary", label: "Secondary", lightValue: "#D95D00", darkValue: "#F2D8B6" },
      ],
    },
  ],
  id: "clue-brand-context",
  knowledgeFolders: [
    {
      documents: [
        {
          body: knowledgeBody,
          folderId: "company",
          id: "company-knowledge",
          name: "Overview.md",
          path: "company/Overview.md",
          updatedLabel: "Edited just now",
        },
      ],
      id: "company",
      label: "Company",
    },
    { documents: [], id: "product", label: "Product" },
    { documents: [], id: "audience", label: "Audience" },
    { documents: [], id: "proof", label: "Proof" },
    { documents: [], id: "memories", label: "Memories" },
  ],
  name: "Clue",
  textStyles: [
    { fontFamily: "Satoshi Variable", fontSize: 24, fontWeight: 700, id: "title", lineHeight: 36, name: "Title", recommendedUse: "Primary page headings" },
    { fontFamily: "Satoshi Variable", fontSize: 16, fontWeight: 500, id: "heading", lineHeight: 20, name: "Heading", recommendedUse: "Section and card headings" },
    { fontFamily: "Satoshi Variable", fontSize: 14, fontWeight: 400, id: "body", lineHeight: 20, name: "Body", recommendedUse: "Long-form product copy" },
    { fontFamily: "DM Mono", fontSize: 13, fontWeight: 400, id: "code", lineHeight: 20, name: "Code", recommendedUse: "Structured data and code" },
  ],
  typefaces: [
    { family: "Satoshi Variable", id: "satoshi-variable", source: "library" },
    { family: "Season Serif", id: "season-serif", source: "library" },
    { family: "DM Mono", id: "dm-mono", source: "library" },
  ],
};
