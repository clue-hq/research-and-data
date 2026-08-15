/**
 * The FI-4 slice-3 D-6 checklist table: which explicit onboarding fields roll up into which
 * setting-up row.
 *
 * This is DATA, deliberately — the reduction over it (`model/setup-items.ts`) takes the table
 * as a parameter and knows nothing about these particular four rows. The field partition is the
 * ratified one and covers all eleven `CLIENT_ONBOARDING_FIELDS` exactly once; company navigation
 * such as `client.product_catalog` is intentionally not a checklist row. The labels and
 * detail lines are integration-authored copy pending founder review.
 */
export interface SetupGroup {
  /** Stable across every poll tick — the frozen SetupRow keys on it. Never renumber. */
  id: string;
  label: string;
  detail: string;
  fieldKeys: readonly string[];
}

export const SETUP_GROUPS: readonly SetupGroup[] = [
  {
    id: "product-value",
    label: "Understanding your product & value",
    detail: "Product, value proposition, and differentiators",
    fieldKeys: ["client.product", "client.value_prop", "client.differentiator"],
  },
  {
    id: "pricing-proof",
    label: "Pricing & proof",
    detail: "Pricing posture and proof points",
    fieldKeys: ["client.pricing_posture", "client.proof_point"],
  },
  {
    id: "customers-market",
    label: "Customers & market",
    detail: "Customers, ICP evidence, and market reputation",
    fieldKeys: [
      "client.customer",
      "client.icp_evidence",
      "client.market_reputation",
      "client.delivered_value",
    ],
  },
  {
    id: "competitors-buyers",
    label: "Competitors & likely buyers",
    detail: "Competitor landscape and likely-buyer profiles",
    fieldKeys: ["client.competitor", "client.buyer_profile"],
  },
] as const;
