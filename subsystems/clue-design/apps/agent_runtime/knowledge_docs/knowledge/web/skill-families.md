# Website skill families

Seven families cover 24 responsibilities through existing callable tools. A
family is a group of skills, not a separately running agent. Entry files are
short; read their detailed references for the operation at hand. This works
from a workspace's captured brand sources, not a hardcoded customer pack.

| Family | Responsibilities | Skills |
|---|---|---|
| Source readiness (4) | observed-page acquisition; coverage/freshness/version; provenance/dependencies; gap/refetch handoff | `web-source-readiness` |
| Source-faithful composition (4) | brand grammar; pin/rebind/variant/repair choice; responsive/root/asset preservation; chrome/CTA consistency | `create-website`, `repair-cloned-sections`, `campaign-page-workflow` |
| Media composition (4) | actual role/rendition/provenance; product crop/radius/alpha; background/derivative choice; proof/logo identity | `web-media-composition` |
| Motion fidelity (3) | inventory; supported reconstruction/fallback; state/playback verification | `web-motion-fidelity` |
| Personalization (3) | page/audience intent; identity/evidence/use gates; grounded copy and destination | `web-account-personalization`, `campaign-landing-page`, `conversion-copywriting` |
| Scoped editing (3) | artifact/target/current state; minimal mutation; preservation and targeted verification | `edit-website` |
| Fidelity review (3) | source/final-state comparison; responsive/interaction/conversion/provenance; honest verdict/gaps | `review-website` |

For new pages: readiness → relevant composition/media/motion/personalization →
review. For a targeted edit: editing → only the families affected → scoped
review. `design-guidance` supports brand deployment; `plan-design` owns the
existing plan. Neither overrides the measured source or user edits.

The workflow has real capability boundaries. Website agents use their current
workspace's registry and declared tools. `fetch_page` supplies facts and links,
not a rendered capture. Acquisition/refresh belongs to brand ingestion. Never
seed a customer-specific replacement catalog to make a run appear complete.
An unavailable source/read/refresh tool is a named gap, not a fictional call.
The director/solo performs render and behavioral review. The author reports
what it changed; a reviewer uses delivered observations and read tools.

A source faithful page may reuse captured HTML/CSS inside React WebDoc output;
that does not recover the original site's React source or WebGL program.
Generated media and authored custom TSX are derived work. Readiness, successful
compilation, approved assets and a clean static screenshot are separate from
visual and functional acceptance. Report each against observed evidence.
