# Website page-role validation

The source-library planner now distinguishes product pages containing customer/review features from actual customer proof. A recognized product namespace defeats ambiguous descendant segments such as `customer` and `reviews`; explicit `case-studies` and `customer-stories` namespaces remain proof. A complete plural collection CTA such as “View more stories” within a proof path identifies an index instead of consuming an individual-story slot. This is a bounded English-language heuristic, not verified semantic understanding of every destination.

No brand names, customer names or route exceptions were added. Existing origin/credential exclusions, exact query identity, observed-link-only discovery, category quotas (2 products, 1 customer index, 2 stories), and the 20-page cap are preserved. A malformed observed URL is skipped individually rather than aborting otherwise valid discovery; explicit request validation remains unchanged.

## Evidence

- Seven of seventeen new role checks failed before the correction; all passed afterward. A separate malformed-link regression failed before the per-link guard.
- Final focused suite: **64 passed**, covering new cases and the existing semantic-navigation/capture contracts. Ruff and whitespace checks passed.
- Independent read-only review found no new actionable defect in the role patch and replayed all four frozen homepages.
- AWS's six-page plan now includes the actual customer index and two individual stories. Previously a product URL consumed the customer-index slot and a collection consumed a story slot.
- Clue remains one page because its observed links supply no product/customer/story destinations. Conduit remains six. Google remains four in the initial homepage plan, with stories selected after the customer index is captured.

The earlier 19-page source library used an explicitly selected evaluation plan. It is not evidence that automatic discovery selected those same URLs. This replay uses the current generic discovery function and frozen captured HTML; it downloads nothing and makes no live workspace changes.

Evidence: `.local-setup/website-capture/proof-role-parent.xml`; the four frozen homepage snapshots and `library-20260920` manifests remain unchanged. Broader limitations include first-match quotas, English labels, supporting-page redirect-origin drift, and destination relevance that still needs review.
