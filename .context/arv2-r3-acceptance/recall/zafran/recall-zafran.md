# answer-key recall — zafran

account **zafran** · keys 66 · exact 22 · partial 11 · field_only 23 · missing 10 · **recall 50%**

| section | hits | keys | recall |
| --- | ---: | ---: | ---: |
| `core` | 24 | 29 | 83% |
| `account` | 8 | 26 | 31% |
| `account.resonance` | 1 | 11 | 9% |

## misses

- **core.annual_revenue** (zaf-015) — missing
  - key: `{"amount_max": 25000000, "amount_min": 10000000, "as_of": "2026-08-22", "currency": "USD", "estimate_kind": "provider_estimate"}`
- **account.total_funding** (zaf-017) — field_only
  - key: `{"amount": 130500000, "currency": "USD", "investors": 9, "rounds": 4}`
  - run: `{"amount_usd": 130000000, "estimate_kind": "reported"}`
- **account.recent_funding** (zaf-018) — field_only
  - key: `[{"announced_at": "2025-12-02", "investors": ["Vintage Investment Partners", "Cyberstarts", "Amex Ventures", "PSP Growth", "Knollwood Investment Advisory", "Sequoia Capital", "Menlo Ventures"], "raised_amount": 60000000…`
  - run: `{"amount_usd": null, "date": "2026-02-24", "investor": "Amex Ventures", "round": "strategic investment"}`
- **account.employee_roster_sample** (zaf-023) — field_only
  - key: `[{"department": ["sales"], "full_name": "Brian Sams", "linkedin": "https://www.linkedin.com/in/brian-sams", "seniority": "mid_level", "source_call": "POST /v1/people {domain:zafran.io,size:12}", "start": "2026-08-01", "…`
  - run: `[{"name": "Sanaz Yashar", "title": "Co-Founder & CEO"}, {"name": "Ben Seri", "title": "Co-Founder & CTO"}, {"name": "Rotem Peled-Dvir", "title": "SVP Finance"}, {"name": "Tom Anthony", "title": "SVP Sales"}, {"name": "N…`
- **account.open_requisitions** (zaf-087) — field_only
  - key: `[{"compensation_published": false, "days_open": 81, "department": "Sales", "employment_type": "FullTime", "is_remote": true, "job_url": "https://jobs.ashbyhq.com/zafran-security/22702028-c1c6-4147-b099-0bc62d81b978", "l…`
  - run: `[{"dept": "Marketing", "published": "2026-08-19", "still_listed": true, "title": "Business Development Representative", "url": "https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13"}]`
- **account.abm_program_maturity** (zaf-090) — field_only
  - key: `{"days_open": 77, "published_at": "2026-06-17", "reports_to": "Head of Growth Marketing (Vari Kaur)", "req": "Senior Manager, ABM & Integrated Campaigns", "state": "being built from scratch", "url": "https://jobs.ashbyh…`
  - run: `{"paragraphs": ["Own ABM from the ground up: 1:1 programs for your most strategic targets, 1:few cluster plays for high-potential segments, and scaled 1:many motions where volume matters."]}`
- **account.named_customers** (zaf-093) — field_only
  - key: `[{"name": "Ricardo Lafosse", "quote": " platform page See the Full Platform ## Ranked #1 for Continuous Threat Exposure Management (CTEM) ״Zafran is tackling vulnerabilities from a hacker's perspective. They add a true …`
  - run: `["Lumen Technologies"]`
- **account.media_layer_index** (zaf-094) — field_only
  - key: `[{"cost_usd": 0.024451, "duration": "00:42:49", "latency_s": 44.11, "person": "Sanaz Yashar", "title": "Boardroom Club — AI Summit: Sanaz Yashar", "transcript_chars": 44409, "url": "https://podcasters.spotify.com/pod/sh…`
  - run: `[{"duration_s": 212, "kind": "youtube", "person": "Sanaz Yashar", "speaker_verified": false, "url": "https://www.youtube.com/watch?v=CVVlYiauTE4"}]`
- **account.media_transcript_quality_warning** (zaf-118) — missing
  - key: `{"media": "42:49 podcast", "model": "gemini-3.5-flash-lite", "remedy": "gemini-3.5-transcribe re-ran the same file and produced the full 6,926-word episode with no looping, but returns parts[].audioTranscription.text wi…`
- **core.company_about** (zaf-122) — field_only
  - key: `Describes itself as "the first AI-native end-to-end Threat Exposure Management platform" and promotes "Agentic Exposure Management" covering asset inventory, vulnerability detection, risk assessment, and autonomous reme…`
  - run: `Zafran | AI-Native Threat Exposure Management Platform Zafran's agentic platform proves what attackers can exploit in your environment, then mobilizes your existing defenses to stop them. Zafran is for security teams bu…`
- **account.recent_funding** (zaf-125) — field_only
  - key: `Series C $60M led by Menlo Ventures (Dec 2, 2025); subsequent strategic investments/extensions from Amex Ventures and Cisco Investments announced in 2026`
  - run: `{"amount_usd": null, "date": "2026-02-24", "investor": "Amex Ventures", "round": "strategic investment"}`
- **account.total_funding** (zaf-126) — field_only
  - key: `{"amount_usd": "more than $130M (company reported); third-party coverage estimated >$140M after Cisco investment but exact amount NOT FOUND", "semantics": "reported and third-party estimate mixed"}`
  - run: `{"amount_usd": 130000000, "estimate_kind": "reported"}`
- **core.company_about** (zaf-127) — field_only
  - key: `Claims outcome: de-risks 90% of critical vulnerabilities overnight and uses existing security tools to remediate the 10% most likely to be exploited`
  - run: `Zafran | AI-Native Threat Exposure Management Platform Zafran's agentic platform proves what attackers can exploit in your environment, then mobilizes your existing defenses to stop them. Zafran is for security teams bu…`
- **account.strategic_moves** (zaf-128) — field_only
  - key: `Launched Agentic Exposure Management (autonomous AI agents across vulnerability lifecycle); positioning product as an overlay that leverages existing scanners/agents/controls; packaging core + add-ons (Zafran Discover, …`
  - run: `Agentic Exposure Management launch with Series C; capital for product innovation and global expansion`
- **account.operational_pain** (zaf-129) — field_only
  - key: `Company cites rapid AI development driving hiring needs across engineering, sales, customer success, and core infrastructure; scaling to meet demand`
  - run: `ABM program being built from scratch by a single senior hire who must execute hands-on without a large team or large budget; 1:1 / 1:few / 1:many still to be stood up.`
- **core.hq_location** (zaf-134) — field_only
  - key: `New York, New York (company press release dateline); company has Israeli founders / presence referenced across coverage`
  - run: `{"city": "New York", "country": "United States", "country_code": "US", "raw": "New York, New York", "region": "New York"}`
- **account.recent_funding** (zaf-135) — field_only
  - key: `Strategic investment announced from Cisco Investments (2026-07-22), company confirmed investment (not an acquisition)`
  - run: `{"amount_usd": null, "date": "2026-02-24", "investor": "Amex Ventures", "round": "strategic investment"}`
- **account.resonance.public_frustrations** (zaf-136) — missing
  - key: `Company positions product as addressing customer frustration with noisy scanners and manual triage; claims to "replace legacy scanner with Zafran continuous detection, no new agents" and to "normalize and de-duplicate f…`
- **account.resonance.culture** (zaf-137) — field_only
  - key: `Company frames itself as R&D and enterprise security talent driven; hires for engineering, sales, CS, and core infra after Series C`
  - run: `R&D and enterprise security talent framing; careers page employee quotes from Field Marketing, Solutions, Engineering, DevOps, RSM, BDR`
- **account.resonance.public_frustrations** (zaf-138) — missing
  - key: `Third-party press raised questions about competitive differentiation and ARR growth pace; anonymous exec quoted saying product struggled to demonstrate meaningful competitive advantage`
- **account.recent_funding** (zaf-139) — field_only
  - key: `Amex Ventures strategic investment announced Feb 24, 2026; CTech reported amount estimated at several million as an extension`
  - run: `{"amount_usd": null, "date": "2026-02-24", "investor": "Amex Ventures", "round": "strategic investment"}`
- **account.resonance.buying_culture** (zaf-140) — field_only
  - key: `Company targets CISOs, security practitioners, and business leaders and uses ABM-driven GTM; land motion emphasizes leveraging customers' existing tools and routing remediation through Jira/ServiceNow`
  - run: `{"culture_label": "hybrid NYC GTM", "summary": "NYC office ~3 days a week for the BDR seat; BDR reports into Marketing department"}`
- **account.hiring_velocity_eng** (zaf-141) — missing
  - key: `Multiple open roles listed in 2026: Senior Manager ABM & Integrated Campaigns, Sr Technical Marketing Manager, Director of Product Marketing, AVP Sales East, Technical Account Manager (public job postings)`
- **account.resonance.attrition_signal** (zaf-142) — field_only
  - key: `Co-founder / CPO Snir Havdala reported by CTech to have departed to NVIDIA; company stated departure was planned and product leadership assumed by Itay Nachum (VP Product)`
  - run: `{"direction": "stable", "signal_type": "attrition", "summary": "Co-founder/CPO Snir Havdala left; company says planned; Itay Nachum VP Product assumed product org"}`
- **account.resonance.eng_blog_tone** (zaf-143) — missing
  - key: `Company messaging emphasizes agentic AI, autonomous agents, and practical remediation outcomes (de-duplication, exploitability testing, mitigation via existing controls)`
- **account.recent_funding** (zaf-144) — field_only
  - key: `Series C messaging: capital to accelerate product innovation and global expansion`
  - run: `{"amount_usd": null, "date": "2026-02-24", "investor": "Amex Ventures", "round": "strategic investment"}`
- **account.resonance.public_frustrations** (zaf-145) — missing
  - key: `Claims platform reduces remediation time from weeks to hours and presents RemOps metric of "87%" time reduction per vulnerability (modeled savings $169K to $2.7M)`
- **core.primary_tech_stack** (zaf-147) — field_only
  - key: `Agentic AI / generative AI agents, Exposure Graph, integrations with scanners/endpoint/cloud security tools, ticketing integrations (Jira, ServiceNow)`
  - run: `["dnssec", "google cloud", "amazon s3", "envoy", "floc opt-out", "cloudflare automatic challenge", "cloudflare challenge", "hubspot hosted", "amazon oregon region", "zendesk mail"]`
- **account.resonance.public_frustrations** (zaf-148) — missing
  - key: `Company claims 99% of critical vulnerabilities are not exploitable and 1% require rapid remediation, repeated across corporate messaging`
- **account.resonance.public_frustrations** (zaf-149) — missing
  - key: `Company claims to "de-duplicate" findings and provide a single source of truth across cloud, on-prem, and AppSec`
- **account.resonance.public_frustrations** (zaf-150) — missing
  - key: `Company states it is trusted by Fortune 500 and high-growth companies and lists CISO quotes from Kraft Heinz, Chipotle, Netskope, Ashland, and a Fortune 25 Healthcare Enterprise`
- **account.claimed_customer_logos** (zaf-172) — field_only
  - key: `["Kraft Heinz (Ricardo Lafosse, CISO)", "Chipotle (Dave Estlick, CISO)", "Netskope (James Robinson, CISO)", "Ashland (Robert Schuetter, CISO)", "Unnamed Fortune 25 Healthcare Enterprise (CISO quote)", "OpenAI (press: \"…`
  - run: `["Kraft Heinz", "Chipotle", "Netskope", "Ashland", "Lumen"]`
- **account.product_packaging** (zaf-173) — field_only
  - key: `{"addons": ["Zafran Discover", "Zafran Autonomous Workflows"], "core": "Zafran platform (Agentic Exposure Management)"}`
  - run: `{"core": "AI-Native Threat Exposure Management / Agentic Exposure Management", "named_modules": ["Unify Findings", "Assess Risk", "Mitigate", "RemOps / Remediate", "Proactive Exposure Hunting", "Exposure Graph", "Agenti…`
