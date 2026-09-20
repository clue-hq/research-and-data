## Purpose and users

Conduit’s public developer story is to [build with Conduit](https://www.conduit.ai/developers) either by calling the REST API or by giving an AI client native access through MCP. That is a workspace-data and configuration interface, not a replacement for the hospitality product. The same workspace still holds members, inboxes, channels, Knowledge, agents, tools, workflows, and settings; operators configure those surfaces in the app. [Source](https://docs.conduit.ai/)

A developer is needed when the account must sync Conduit records into another system, drive Cursor/Claude/Codex/VS Code against a live workspace, author custom code tools, or create agents/workflows/knowledge programmatically. Guest messaging, the unified inbox, [AI Agents](#knowledge/product-agents), [visual Workflows](#knowledge/product-workflows), PMS listing sync, and marketplace templates stay product features that hospitality teams can run without writing integrations. Docs also say most teams can customize voice, policies, enable or disable workflows, and write custom API functions after going live—the last of those is the developer path, not the default path. [Source](https://docs.conduit.ai/overview/how-conduit-agents-work)

Unknown from these pages: how many customers use API/MCP versus the visual builder, and whether a dedicated engineering hire is required versus a technical operator.

## Interfaces and capabilities

| Surface | What sources describe | Auth model | Distinct from product UI |
| --- | --- | --- | --- |
| REST API | Typed endpoints for workspaces, contacts, conversations, tickets, calls, knowledge, agents, skills, workflows, connected devices | Bearer token; workspace-scoped | Programmatic CRUD/send vs inbox and Build screens | [Source](https://www.conduit.ai/developers)
| OpenAPI | Unique operation IDs, typed parameters, response schemas, operation descriptions for SDK generation and LLM function calling | Same API tokens | Schema for clients, not a separate product | [Source](https://www.conduit.ai/developers)
| MCP server | Streamable HTTP at `https://api.conduit.ai/v1/mcp`; MCP revision 2025-06-18 | OAuth 2.1 for interactive clients; `capi_` tokens for server-to-server | Same authenticated capabilities as tools, with read/write/idempotent/destructive annotations | [Source](https://docs.conduit.ai/mcp/overview)
| Custom code tools | Python or JavaScript tools, plus connection tools, MCP tools, and per-agent overrides | Enabled in Tools; also creatable via API/MCP | Code the agent may call only if that agent is granted the tool | [Source](https://docs.conduit.ai/)
| Visual workflows | Trigger → actions/conditions in the builder; API can list/get/create/update workflows and read executions | Product UI plus workflow API | Managed automation; not an event-subscription webhook catalog | [Source](https://docs.conduit.ai/workflows/getting-started)

REST overview lists contacts, conversations, tickets, calls, escalations, custom attributes, knowledge, workspace metadata, agents, skills, custom tools, workflows, reservations, appointments, helpdesk tickets, and insights such as automation rate. Base URL is `https://api.conduit.ai/v1`. [Source](https://docs.conduit.ai/api-reference/introduction)

MCP can look up contacts, conversations, tickets, calls, reservations, and appointments; search knowledge; send messages on a conversation, ticket, or contact channel; manage agents, skills, custom code tools, and contact custom attributes; list accessible workspaces; and manage Operator skills (`operatorSettings.skills`). Device inspect/control tools exist only when the Devices add-on is enabled. Portal session, verification, offer, and template tools need the Portals add-on. `operator_*` tools are MCP-only with no matching REST route. [Source](https://docs.conduit.ai/mcp/overview)

The ChatGPT/Codex plugin is a narrower, read-only subset (five tools). Sending messages or using the full catalog requires a direct MCP connection. [Source](https://docs.conduit.ai/mcp/overview)

Documented “webhooks” are not a general Conduit outbound event bus. Workflows include a **Send webhook (HTTP)** action. Some PMS setups (for example Beds24) paste a Conduit **Webhook URL** so the PMS can push into Conduit. Neither is documented as a public subscribe-to-inbox-events API. [Source](https://docs.conduit.ai/workflows/workflow-usage)

## Implementation patterns

**Keep the system of record in Conduit, poll for deltas.** List Conversations with `updated_after`, then List Conversation Messages with `created_after`. Cursors page a snapshot; timestamps find what changed. Deduplicate on message `id`. Filter on `created_at`, not `sent_at`, or backdated channel imports can be skipped. Distinguish AI sends with `is_sent_by_autopilot`—do not infer automation from `sender.user_id`. [Source](https://docs.conduit.ai/api-reference/introduction)

**MCP in an IDE or assistant.** Pin one `workspace_id` at session start (`list_workspaces`). Pre-approve read tools if the client allows it; never allow-list `send_*`, `patch_*`, `create_*`, `update_*`, or `delete_*`. Pass a stable `idempotency_key` on every send so retries do not double-message guests. [Source](https://docs.conduit.ai/mcp/overview)

**Custom agent actions.** Author Python/JavaScript tools in Tools (or via `create_custom_tool`). MCP guidance is to call `list_custom_tool_runtimes` first so the model matches the entrypoint and return shape. Then grant that tool on the specific agent (`set_agent_tool_access` / Toggle Agent Tool). The REST route existing is not that grant. [Source](https://docs.conduit.ai/mcp/overview)

**Managed custom workflows.** Ops teams still build proactive, routing, and triage flows in the visual builder (tags, delays, Slack/email, inject AI). Developers use workflow APIs when they need to version or inspect those graphs outside the UI. [Source](https://docs.conduit.ai/workflows/types-of-workflows)

## Dependencies and controls

Tokens are generated under **Settings > API & MCP**. The setting is personal; tokens can cover one or more workspaces where the user is an admin. Start read-only; write tools such as `send_conversation_message` need a read/write token (or OAuth `mcp:write`). Scope every request to a workspace the token can access. Rotate/revoke in the same settings screen; revocation is described as immediate. [Source](https://docs.conduit.ai/api-reference/introduction)

MCP OAuth 2.1 uses Dynamic Client Registration and workspace consent. A valid token with an empty `list_workspaces` result is not workspace-scoped. HTTP 403 means missing workspace access or missing write privilege—not that the tool is absent from the catalog. Device writes also follow workspace policy and contact scope. Portal writes need **Manage Portals**; Operator skill writes need **Manage Agents**. [Source](https://docs.conduit.ai/mcp/overview)

Per-agent tool access is the control that decides whether a guest-facing agent may execute a custom function or connection tool. Publishing an agent, enabling a workflow, and handing an MCP client a write token are three different authorizations. Keep human approval on MCP writes that send guest messages.

## Packaging and limits

Both the REST API and MCP server are documented as available on the **v3 plan**, enabled by contacting `support@conduit.ai`. Public [Pricing](#knowledge/pricing) lists Messaging / Guest / Devices / Full Suite unit rates and a Startup package; it does not publish a standalone API or MCP SKU. Do not treat those package starting rates as developer-platform prices. [Source](https://docs.conduit.ai/api-reference/introduction)

Default rate limit is **120 requests per minute per workspace**, shared by REST and MCP. 429 includes `Retry-After`. Some workspaces may have higher limits by plan or entitlement. List endpoints paginate with `limit` 1–100 (default 20) and `cursor`. [Source](https://docs.conduit.ai/api-reference/introduction)

Workflow **runs** are free; credits apply only when a successful run finishes a paid action. **Send webhook (HTTP)** is listed at **0 credits**. That is usage for an outbound HTTP step, not evidence of unlimited webhook subscriptions. [Source](https://docs.conduit.ai/workflows/workflow-usage)

Gaps: no public quota for custom tools, no SLA, no documented webhook signature/event catalog, and no mapping of “v3 plan” to a named row on the marketing pricing table.

## Sales and technical discovery

Ask whether the buying team needs (1) visual guest-journey automation, (2) a custom tool an [agent](#knowledge/product-agents) should call, (3) an external system of record that must poll Conduit, or (4) MCP inside ChatGPT/Claude/Cursor. Custom code needs someone able to implement and maintain it, but in-app custom tools are separate from external REST/MCP enablement. REST/MCP access is described as requiring support-enabled v3 access; that wording does not establish a separately priced package. Connecting an existing MCP client may be an administrator task, while building a custom integration needs engineering. Do not require API access merely to use a visual workflow or in-app tool. Confirm add-ons before promising device or portal APIs. Confirm write-token and per-agent tool policy before promising that “the agent can hit our API.”

Treat vendor rhetoric about going live in a week as a company claim, not a measured implementation SLA. Pair this page with [Integrations](#knowledge/integrations) for PMS/channel connections and [Operator](#knowledge/product-operator) for non-code configuration work.
