"""Prompt-only preview. No DB, fleet, Exa, AI Ark or other research-provider clients."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
from datetime import date
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import dotenv_values
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from research_preview_support import Audit, PreviewTools, content, save

from clue_agents import AgentRole
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_api.arv2.account_exa_brief import account_exa_arguments
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_tools import AccountResearchDeepArgs, ToolRuntime
from clue_api.arv2.exa_client import deep_reasoning_body
from clue_api.arv2.quality_provider_tools import AcquireResearchTool
from clue_api.arv2.quality_views import _passage
from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_config import Secrets, default_gateway_config, load_settings
from clue_obs.langfuse import flush_langfuse, observation, propagate_trace
from clue_obs.production import install_production_langfuse, install_production_tracing
from clue_storage.fs import FsStorage

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument(
    "--source-context",
    type=Path,
    required=True,
    help="Retained context export with 05-context-manifest.json and documents/",
)
parser.add_argument(
    "--project-library",
    type=Path,
    required=True,
    help="Read-only exported project status.md and decisions.md",
)
parser.add_argument("--prepare-only", action="store_true")
parser.add_argument("--target-name", default="Zafran Security")
parser.add_argument("--target-domain", default="zafran.io")
parser.add_argument("--recipe-version", type=int, default=7)
options = parser.parse_args()
HERE = options.output.resolve()
INPUT = HERE / "inputs"
SOURCE = options.source_context.resolve()
SESSION = "account-exa-brief-preview-" + str(uuid4())
START = monotonic()


async def main():
    if any(
        (HERE / name).exists() for name in ("exa-query.generated.md", "head-brief.generated.md")
    ):
        raise RuntimeError("Generated output exists; use a new directory to preserve the sample.")
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "traces").mkdir(exist_ok=True)
    original = json.loads((SOURCE / "05-context-manifest.json").read_text())
    refs = [original["icp"], *original["personas"], *original["seller_documents"]]
    manifest = {k: v for k, v in original.items() if k != "field_catalog"}
    manifest["document_paths"] = {}
    documents = []
    for ref in refs:
        name = Path(ref["path"]).name
        raw = (SOURCE / "documents" / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref["sha256"], name
        dest = INPUT / "documents" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        documents.append((name, raw.decode()))  # Includes the complete YAML, not only prose.
        cursor = 0
        while True:
            view = _passage(raw.decode(), cursor, f"documents/{ref['document_id']}")
            save(INPUT / "research/documents" / ref["document_id"] / f"{cursor}.json", view)
            if view["next_path"] is None:
                break
            cursor = int(Path(view["next_path"]).stem)
        manifest["document_paths"][ref["document_id"]] = (
            f"/research/documents/{ref['document_id']}/0.json"
        )
    for name in ("status.md", "decisions.md"):
        src = options.project_library / name
        if not src.is_file():
            raise ValueError(f"Export the real project file before previewing: {src}")
        dst = INPUT / "project" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
    manifest.update(
        target={"name": options.target_name, "domain": options.target_domain},
        run_date="2026-09-24",
        recent_window_start="2025-12-24",
        preview_only=True,
        capabilities_path="/research/capabilities/0.json",
    )
    save(INPUT / "research/context.json", manifest)
    scope = JobScope(
        workspace_id=original["workspace_id"],
        project_id=original["project_id"],
        project_run_id=uuid4(),
        run_id=uuid4(),
        job_id=uuid4(),
        account_id=uuid4(),
        account_name=options.target_name,
        account_domain=options.target_domain,
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort="full",
        committee_cap=1,
        today=date(2026, 9, 24),
        catalog_version="v4",
        input_refs={"quality_recipe_version": options.recipe_version},
    )
    # Schema-only binding: these operations are never installed as executable preview tools.
    acquisition = AcquireResearchTool(cast(ToolRuntime, SimpleNamespace(scope=scope)))
    caps = json.dumps(acquisition.capabilities(), ensure_ascii=False)
    cursor = 0
    while True:
        view = _passage(caps, cursor, "capabilities")
        save(INPUT / "research/capabilities" / f"{cursor}.json", view)
        if view["next_path"] is None:
            break
        cursor = int(Path(view["next_path"]).stem)
    resolved = quality_profiles(
        quality_tools(scope, FsStorage(INPUT / "storage"), purge=False),
        version=options.recipe_version,
    ).resolve(AgentRole.ACCOUNT_RESEARCH)
    save(
        HERE / "production-resource-manifest.json",
        resolved.resource_manifest.model_dump(mode="json"),
    )
    disclosures = resolved.skill_disclosures()
    for disclosure in disclosures:
        path = INPUT / disclosure.materialized_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resolved.open_skill(disclosure.resource.address))
    save(HERE / "skill-disclosures.json", [d.model_dump(mode="json") for d in disclosures])
    dossier = next(d for d in disclosures if d.resource.name == "account-dossier")
    # Open the selected governed skill in full. Do not send governed YAML to the native
    # skills index, whose independent frontmatter schema requires `description`.
    selected_skill = resolved.open_skill(dossier.resource.address)
    system = resolved.prompt_body + "\n\n" + resolved.generated_resource_map
    system += "\n\nSelected account-dossier skill (complete body):\n" + selected_skill
    system += (
        "\n\nPREVIEW SCOPE: prepare one request using the fresh Head-of-ABM brief and "
        "pinned documents. Finish with capture_exa_request. Capabilities describe production "
        "operations, which cannot execute here. Do not nominate people, write claims, "
        "delegate, or call research providers. No preliminary web results were supplied. "
        "Project files describe the retained project's real status; this is a fresh query "
        "exercise, not continuation of its earlier research jobs."
    )
    (HERE / "account-system-prompt.md").write_text(system)
    head_skill = (
        ROOT / "platform/agents/catalog/skills/account-research-briefing/v1/SKILL.md"
    ).read_text()
    head_system = (
        "You are the Head of ABM writing a fresh delegation brief using the finalized "
        "account-research-briefing skill below. Return only directive_text with "
        "{{account_name}} and {{account_domain}} placeholders. This is a prompt-only "
        "preview: no launch or research calls. Current founder assignment: investigate "
        f"{options.target_name} for {original.get('seller_name', 'Clue')}, "
        "with at most one eventual person-depth subject; recent "
        "developments use the nine calendar months ending 24 September 2026. This "
        "supersedes the retained ICP's older six-month timing priority. Keep pinned "
        "qualification criteria as the researcher's own evaluation context, separate "
        "from source-research instructions. Do not reuse a previous delegation brief. "
        "No phone enrichment, downstream customer inventory, or verification gates. "
        "Project files and full selected documents follow.\n\n" + head_skill
    )
    head_user = (
        f"Prepare a fresh brief for the selected {original.get('seller_name', 'Clue')} "
        "project. Retained documents are "
        "historical inputs.\n"
    )
    for name in ("status.md", "decisions.md"):
        head_user += (
            f"\n<PROJECT_FILE name={json.dumps(name)}>\n"
            + (INPUT / "project" / name).read_text()
            + "\n</PROJECT_FILE>\n"
        )
    for name, body in documents:
        head_user += f"\n<DOCUMENT name={json.dumps(name)}>\n{body}\n</DOCUMENT>\n"
    (HERE / "head-system-prompt.md").write_text(head_system)
    (HERE / "head-input.md").write_text(head_user)
    (HERE / "head-of-abm-briefing-skill.snapshot.md").write_text(head_skill)
    if options.prepare_only:
        print(
            "Prepared complete pinned documents, project files, production capabilities "
            "and selected skill. No model calls."
        )
        return
    env = dotenv_values(ROOT / ".env")
    models = {
        role: env[role.upper() + "_AGENT_MODEL"] for role in ("head_of_abm", "account_research")
    }
    for role in models:
        key = role.upper() + "_AGENT_MODEL_EFFORT"
        if env.get(key):
            os.environ.setdefault(key, env[key])
    settings = load_settings(_env_file=ROOT / ".env")
    secrets = Secrets(_env_file=ROOT / ".env")
    tracing = install_production_tracing(settings, secrets, service_name="research-prompt-preview")
    traced = install_production_langfuse(
        settings, secrets, runtime=tracing, service_name="research-prompt-preview"
    )
    gateway = default_gateway_config()
    provider = build_agent_model_provider(config=gateway, secrets=secrets)
    lf = build_langfuse_callbacks()
    callbacks = [Audit(HERE, START), *([lf.handler] if lf else [])]
    head = provider.build(
        model_id=models["head_of_abm"],
        role="head_of_abm",
        timeout_s=gateway.timeout_s,
        max_retries=gateway.max_retries,
        max_output_tokens=6000,
        temperature=0,
    )
    with (
        observation("research.prompt-preview.head-brief") as span,
        propagate_trace(
            trace_name="research.prompt-preview.head-brief",
            session_id=SESSION,
            tags=["prompt-preview", "no-research"],
        ),
    ):
        save(
            HERE / "head-trace-linkage.json",
            {"trace_id": span.trace_id, "observation_id": span.id, "session_id": SESSION},
        )
        result = await head.ainvoke(
            [SystemMessage(content=head_system), HumanMessage(content=head_user)],
            config={"callbacks": callbacks},
        )
    brief = content(result)
    if not brief.strip():
        raise RuntimeError("Head-of-ABM returned no brief")
    (HERE / "head-brief.generated.md").write_text(brief)
    (INPUT / "delegation-brief.md").write_text(
        brief.replace("{{account_name}}", options.target_name).replace(
            "{{account_domain}}", options.target_domain
        )
    )
    save(HERE / "head-response.json", result.model_dump(mode="json"))
    print("Fresh Head-of-ABM brief generated; no old brief loaded.", flush=True)

    captured = []

    class PreviewRequest(AccountResearchDeepArgs):
        context_gaps: list[str] = []

    async def capture_exa_request(
        charter: str,
        additional_queries: list[str],
        context_gaps: list[str],
        same_name_exclusions: list[str] | None = None,
        num_results: int = 40,
    ) -> str:
        """Capture the exact proposed request without calling Exa, then end the preview."""
        if captured:
            return "The original sample is already captured."
        args = AccountResearchDeepArgs(
            charter=charter,
            additional_queries=additional_queries,
            same_name_exclusions=same_name_exclusions or [],
            num_results=num_results,
        )
        request = deep_reasoning_body(**account_exa_arguments(**args.model_dump()))
        value = {
            "query": request["query"],
            "context_gaps": context_gaps,
            "tool_arguments": args.model_dump(),
            "request": request,
        }
        captured.append(value)
        save(HERE / "exa-request.captured.json", value)
        save(HERE / "exa-request.wire.json", request)
        save(HERE / "additional-queries.generated.json", request.get("additionalQueries", []))
        (HERE / "exa-query.generated.md").write_text(request["query"])
        (HERE / "exa-system.actual.md").write_text(request["systemPrompt"])
        return "Captured for founder review. No Exa request was made."

    capture = StructuredTool.from_function(
        coroutine=capture_exa_request, args_schema=PreviewRequest, return_direct=True
    )
    account = provider.build(
        model_id=models["account_research"],
        role="account_research",
        timeout_s=gateway.timeout_s,
        max_retries=gateway.max_retries,
        max_output_tokens=14000,
        temperature=0,
    )
    graph = create_deep_agent(
        model=account,
        system_prompt=(HERE / "account-system-prompt.md").read_text(),
        tools=[capture],
        middleware=[PreviewTools()],
        backend=FilesystemBackend(root_dir=INPUT, virtual_mode=True),
        name="account-exa-prompt-preview",
    )
    opening = (
        "Prepare the main Exa query and complementary additional queries for "
        f"{options.target_name} "
        f"({options.target_domain}), as of 24 September 2026. The Head-of-ABM assignment "
        "is /delegation-brief.md. Complete pinned references and identity are in "
        "/research/context.json; original documents are under /documents/. The "
        "selected account-dossier skill is already supplied in full. Batch "
        "independent reads of the remaining context. Project status and decisions "
        "are under /project/. This is a fresh-research preview, so there are no "
        "target findings or preliminary web results to assume. Do not research or "
        "launch other work: finish by calling capture_exa_request."
    )
    (HERE / "account-opening-message.md").write_text(opening)
    with (
        observation("research.prompt-preview.account") as root_span,
        propagate_trace(
            trace_name="research.prompt-preview.account",
            session_id=SESSION,
            tags=["prompt-preview", "no-research", "step4-r7"],
        ),
    ):
        save(
            HERE / "trace-linkage.json",
            {"trace_id": root_span.trace_id, "observation_id": root_span.id, "session_id": SESSION},
        )
        output = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [HumanMessage(content=opening)]},
                config={"callbacks": callbacks, "recursion_limit": 24},
            ),
            timeout=600,
        )
    save(HERE / "account-messages.json", [m.model_dump(mode="json") for m in output["messages"]])
    if not captured:
        raise RuntimeError("The researcher did not capture an Exa assignment")
    hashes = {
        str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in INPUT.rglob("*")
        if p.is_file()
    }
    save(
        HERE / "manifest.json",
        {
            "session_id": SESSION,
            "requested_models": models,
            "langfuse_installed": traced,
            "elapsed_seconds": round(monotonic() - START, 2),
            "research_provider_calls": 0,
            "application_database_writes": 0,
            "source_context": str(SOURCE),
            "quality_recipe_version": options.recipe_version,
            "input_hashes": hashes,
            "limitations": [
                "Uses retained pinned test-project documents plus a read-only export of its "
                "project status and decisions, not a fresh customer production snapshot.",
                "Fresh Head-of-ABM model call applies the finalized briefing skill; isolated "
                "from the production launch lifecycle.",
                "Account uses real Deep Agents and the normal configured model provider, but "
                f"preview-only tools and production revision-{options.recipe_version} instructions "
                "and account "
                "request builder, not the production C5 execution lifecycle.",
                "The selected dossier skill is opened in full before the model; this preview "
                "does not test progressive skill selection. No preliminary website, job "
                "board or enrichment calls.",
                "No claims, narrative, person research, Exa or AI Ark calls.",
            ],
        },
    )
    flush_langfuse()
    print(
        json.dumps(
            {
                "status": "captured",
                "query_words": len(captured[0]["query"].split()),
                "session_id": SESSION,
                "langfuse": traced,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
