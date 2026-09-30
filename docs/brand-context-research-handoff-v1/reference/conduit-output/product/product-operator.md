# Operator & internal AI availability

Operator is a named **workspace assistant** in Conduit documentation. It is not listed as a standalone product on marketing navigation, which names [AI Agents](#knowledge/product-agents), [Inbox](#knowledge/product-inbox), [Guest Portals](#knowledge/product-portals), [Workflows](#knowledge/product-workflows), and **Operations** as coming soon. Treat Operator as an internal configuration surface unless a later source changes that packaging.

## What is established

Docs define Operator as Conduit’s workspace assistant: it helps create agents, write Skills, inspect data, understand escalations, and manage configuration in the current workspace. Open it from the main sidebar or as a sidebar on V3 build pages. The start guide puts it in test-and-deploy: inspect, edit, and reason about agent configuration. The agents overview lists it under Build Surfaces with Knowledge, Skills, Tools, and Sandbox. [Source](https://docs.conduit.ai/agent-hub/operator.md)

Public product pages do **not** sell Operator as its own SKU. Footer and product menus list Conduit Agents, Inbox, Portals, and Workflows. Operations is labeled “Coming soon” for AI-coordinated housekeeping, maintenance, and inspections—a different name and job from Operator. [Source](https://www.conduit.ai/product/agents)

Pricing copy includes “Operator, workflows, escalation” on the Messaging package (starting **$18 / unit / mo**, **40 credits / unit / mo**). That is a bundle feature line, not an Operator-only price. [Source](https://www.conduit.ai/pricing.md)

Two other “operator” uses must stay separate. V3 can create **internal agents** that run on workspace data and do not own a customer inbox; Conduit publishes a gallery of those patterns. The REST API also uses “operator replies” for human/staff messages (`is_sent_by_autopilot` is true only when the AI agent sent the message). Neither is the Operator assistant. [Source](https://docs.conduit.ai/agent-hub/internal-agent-use-cases.md)

## Role in the product system

Operator sits in the V3 Agent Hub loop: help the team configure the workspace; do not replace a published guest agent. Docs contrast four surfaces:

| Surface | Who it serves | Guest inbox? | Documented job |
| --- | --- | --- | --- |
| Operator | Workspace team | No | Inspect, edit, reason about configuration |
| Customer agent | Contacts | Yes | Reply through an inbox |
| Internal agent | Team or systems | No | Internal work; may trigger customer actions only via configured workflows, tools, or channels |
| Voice agent | Callers | Voice config | Phone handling |

[Source](https://docs.conduit.ai/agent-hub/operator.md)

A published agent’s behavior still comes from that agent’s Persona, Skills, Tools, Behavior, and Settings. Operator tool access is configured separately from agent tools. Operator Settings cover model behavior and reasoning level when supported, Operator-specific Skills, and which connection, custom, MCP, and built-in tools Operator may use. [Source](https://docs.conduit.ai/agent-hub/operator.md)

MCP can manage Operator Skills (`operatorSettings.skills`) with `list_operator_skills`, `create_operator_skill`, `patch_operator_skill`, and `delete_operator_skill`. Those tools are MCP-only (no matching REST route), require `workspace_id`, and writes need a read/write token plus Manage Agents. That is configuration of the assistant, not a second product. See [Developer platform](#knowledge/product-developers). [Source](https://docs.conduit.ai/mcp/overview)

Devices docs state device tools are available to chat agents, voice agents, workflows, **and Operator**; once the Devices add-on is enabled, Operator can use those tools. Changelog **3.12** (28 Aug 2026) says tasks, including custom fields, can be updated “straight from the AI operator,” Operator timestamps use the workspace timezone, and a workflow-canvas fix unblocked the AI operator. [Source](https://docs.conduit.ai/devices/overview.md)

## Use cases and users

Documented users are workspace teammates, not guests. Concrete tasks in Operator docs:

- Create a chat agent from a plain-language description
- Draft or revise Skills (including turning a rough policy into a Skill on the Skills page)
- Inspect Knowledge gaps or conflicts; draft a Knowledge article while reviewing a source
- Reason about escalations; review an agent’s escalation Skills before changing them
- Generate reports or exports **when the workspace has the required access**
- Point the user to the right configuration page; ask what an agent needs before publish; draft a custom-tool description

[Source](https://docs.conduit.ai/agent-hub/operator.md)

With Devices enabled, Operator can use the same device tool catalog as agents and MCP (list devices, telemetry, access codes, lock/thermostat writes subject to policy). Changelog additionally records task field updates from the AI operator. Docs tell teams to review staged changes before publishing agents, enabling tools, deleting sources, or changing automation. [Source](https://docs.conduit.ai/devices/overview.md)

The internal-agent gallery (cleaning-status messages, trash reminders, lockout codes, and similar) is **not** a list of Operator features. Those are examples of internal agents teams have built or scoped; most need property rules, PMS fields, and escalation contacts. Do not infer Operator performs those jobs unattended.

## Availability and dependencies

| Item | What sources show | Gap |
| --- | --- | --- |
| Commercial listing | Messaging package feature: Operator, workflows, escalation | No Operator-only SKU or fee |
| UI | Main sidebar; sidebar on V3 build pages; full-page threads | No public screenshot of defaults |
| MCP Operator Skills | v3 plan MCP; Manage Agents for writes | No REST equivalent |
| Devices | Operator can use device tools after Devices add-on | Writes follow device policy; remote unlock off by default |
| Operations product | Marketing: coming soon (housekeeping, maintenance, inspections) | Not Operator |

[Source](https://www.conduit.ai/pricing.md)

Messaging starting rates and credits are package-level; see [Pricing](#knowledge/pricing). The credit guide says Operator turns are metered by model and billable tokens, while internal-agent runs have a dynamic work-based cost. It gives roughly 7,000–71,000 billable tokens per credit depending on model, with possible context discounts; this is not one universal per-turn price. It does not establish that Operator autonomously sends guest messages without configured tools and permissions. [Credit guide](https://docs.conduit.ai/setting-up-conduit/credits)

## What sales can say

Say Operator is the in-product workspace assistant for configuring and inspecting Conduit—drafting agents and Skills, checking Knowledge, reasoning about escalations—not a guest-facing agent and not a billed add-on with its own rate card. You may say Messaging’s published feature list includes Operator alongside workflows and escalation, that Operator Skills can be managed over MCP on eligible v3 workspaces, and that Operator can use device tools after Devices is enabled.

Do not pitch Operator as the coming Operations product, as autopilot housekeeping, or as the internal-agent gallery. Do not promise unattended guest actions, resolution rates, or that “operator” in API message flags means this assistant. Keep copy aligned with [Product catalog](#knowledge/products-capabilities) and [AI Agents](#knowledge/product-agents).

## Questions to resolve

Operator credit metering is documented above; there is no single flat per-turn price. Remaining questions concern default enabled tools, guest-conversation write permissions, and how Messaging’s Operator inclusion maps to each workspace version. Confirm with product before using Operator as a primary campaign object.