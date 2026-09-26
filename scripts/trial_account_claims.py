"""Isolated saved-account claim-writing experiment; production selectors stay unchanged.

prepare clones only the named dev DB and original artifact bytes. smoke rolls back
real claim writes. run uses the configured account model and Langfuse, with no
acquisition tools. The harness uses native Deep Agents and the shared claim writer;
it deliberately does not certify C5/fleet/reconciliation lifecycle integration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.dossier_findings import Finding, Review, assessment_for  # noqa: F401
from clue_api.arv2.dossier_import import finding_proposal
from clue_api.arv2.quality_claims import (
    submit_proposal,
)
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    grant_manifest,
    persist_source,
    read_source,
    resolve_source,
)
from clue_api.arv2.research_operations import OperationScope
from clue_storage.fs import FsStorage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".artifacts/arv4-clue-zafran-20260925-r13"
DRAFT = ROOT / "docs/superpowers/drafts/2026-09-25-account-claims-trial"
SOURCE_DB = "clue_zafran_r13_20260925"
CONTAINER = "clue-zafran-quality-live"


def run_paths(number):
    if number < 1:
        raise ValueError("Run number must be positive")
    suffix = f"{number:02d}"
    return (
        ROOT / f".artifacts/account-claims-trial-20260925/run-{suffix}",
        f"clue_account_claims_trial_20260925_{suffix}",
    )


OUT, DB = run_paths(1)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def db_config():
    info = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
    env = dict(x.split("=", 1) for x in info["Config"]["Env"] if "=" in x)
    user = env["POSTGRES_USER"]
    url = (
        f"postgresql+asyncpg://{quote(user, safe='')}:"
        f"{quote(env['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:59274/{DB}"
    )
    return user, url


def scope_from(m):
    return JobScope(
        workspace_id=m["workspace_id"],
        project_id=m["project_id"],
        project_run_id=UUID(m["project_run_id"]),
        run_id=UUID(m["run_id"]),
        job_id=UUID(m["job_id"]),
        account_id=UUID(m["account_id"]),
        account_name="Zafran Security",
        account_domain="zafran.io",
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort="full",
        committee_cap=0,
        today=date(2026, 9, 24),
        catalog_version="v4",
        input_refs={"quality_recipe_version": 15},
        subject_kind=m.get("subject_kind", "account"),
        contact_id=UUID(m["contact_id"]) if m.get("contact_id") else None,
        person_name=m.get("person_name", ""),
        person_linkedin_url=m.get("person_linkedin_url", ""),
    )


class Writer:
    def __init__(self, manifest, engine, storage):
        self.m, self.engine, self.storage = manifest, engine, storage
        self.scope = scope_from(manifest)
        self.context = UUID(manifest["context_id"])
        self.grant = EvidenceGrant(
            OperationScope(
                self.scope.workspace_id, self.scope.run_id, self.scope.job_id, self.scope.account_id
            ),
            UUID(manifest["trial_id"]),
            UUID(manifest["grant_id"]),
        )
        self.sources = {s["path"]: s for s in manifest["sources"]}
        self.prefix = f"trial:{manifest['trial_id']}:"
        self.actor_ref = manifest.get("actor_ref", f"account-claim-trial:{manifest['trial_id']}")
        self.lock = asyncio.Lock()

    async def rows(self, conn):
        rows = (
            (
                await conn.execute(
                    text("""SELECT c.id,c.value_json,c.write_markers,
          q.conclusion,q.revision,c.superseded_by FROM arv2_quality_proposal p
          JOIN claim c ON c.id=p.claim_id LEFT JOIN claim_quality_current q ON q.claim_id=c.id
          WHERE p.workspace_id=:ws AND p.job_id=:job AND c.entity_id=:entity
          AND EXISTS(SELECT 1 FROM claim_quality_assessment a WHERE a.claim_id=c.id
            AND a.actor_ref=:actor) ORDER BY c.collected_at,c.id"""),
                    {
                        "ws": self.scope.workspace_id,
                        "job": self.scope.job_id,
                        "entity": self.scope.person_subject_id or self.scope.account_id,
                        "actor": self.actor_ref,
                    },
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def write(self, conn, args, *, dossier_entry=None):
        unknown = set(args.source_paths) - self.sources.keys()
        if unknown:
            raise ValueError(f"Use an exact source path from /evidence/index.md: {sorted(unknown)}")
        if args.review.duplicate_of or args.review.conflicts_with:
            known = {r["id"]: r for r in await self.rows(conn)}
            if set(args.review.conflicts_with) - known.keys():
                raise ValueError("conflicts_with must name stored claims from this isolated trial.")
        if args.review.duplicate_of:
            if args.review.duplicate_of not in known:
                raise ValueError("duplicate_of must name a stored claim from this isolated trial.")
            if known[args.review.duplicate_of]["value_json"]["review"]["status"] == "duplicate":
                raise ValueError("Point to the canonical claim, not another duplicate.")
        refs = []
        for path in sorted(set(args.source_paths)):
            refs.append(
                await resolve_source(conn, self.grant, UUID(self.sources[path]["source_id"]))
            )
        proposal = finding_proposal(args, refs, origin=dossier_entry, key_prefix=self.prefix)
        receipt = await submit_proposal(
            conn,
            self.storage,
            self.scope,
            self.grant,
            proposal,
            context_id=self.context,
            actor_ref=f"account-claim-trial:{self.m['trial_id']}",
            purge_unevidenced=False,
        )
        return {**asdict(receipt), "review_status": args.review.status}

    async def export(self):
        async with self.engine.begin() as conn:
            rows = await self.rows(conn)
        save(OUT / "claims.json", rows)
        save(OUT / "workspace/claims/index.json", rows)
        kind = "Person" if self.scope.person_subject_id else "Account"
        lines = [f"# {kind} claims — isolated agent trial", "", f"Records: {len(rows)}", ""]
        for row in rows:
            v = row["value_json"]
            review = v["review"]
            lines.extend(
                [
                    f"## {v['topic']}",
                    "",
                    f"Claim: `{row['id']}` · {v['claim_type']} · **{review['status']}**",
                    "",
                    v["finding"]
                    if isinstance(v["finding"], str)
                    else json.dumps(v["finding"], indent=2, ensure_ascii=False),
                    "",
                    f"Review: {review['reason']}",
                    f"Attribution: {v.get('attribution')}",
                    f"Time: {v.get('time_context')}",
                    f"Qualifications: {json.dumps(v.get('qualifications'), ensure_ascii=False)}",
                ]
            )
            if review.get("duplicate_of"):
                lines.append(f"Duplicate of: `{review['duplicate_of']}`")
            if review.get("conflicts_with"):
                lines.append(
                    "Potential conflict with: "
                    + ", ".join(f"`{claim_id}`" for claim_id in review["conflicts_with"])
                )
            if review.get("expected_entity"):
                lines.append(f"Expected entity: {review['expected_entity']}")
            if v.get("agent_interpretation"):
                lines.append(f"Agent interpretation (not evidence): {v['agent_interpretation']}")
            for source in v["sources"]:
                lines.append(
                    f"- {source['url'] or 'Retained provider/report material'} — "
                    f"`{source['path']}` ({source['locator']})"
                )
            lines.append("")
        (OUT / "claims.md").write_text("\n".join(lines))
        return rows


async def prepare(*, dossier_mode=False):
    if OUT.exists():
        raise ValueError("Trial folder already exists; preserve it and choose a new run.")
    user, url = db_config()
    subprocess.run(
        ["docker", "exec", CONTAINER, "createdb", "-U", user, "-T", SOURCE_DB, DB], check=True
    )
    OUT.mkdir(parents=True)
    shutil.copytree(SOURCE / "blobs", OUT / "blobs")
    workspace = OUT / "workspace"
    for d in [
        "evidence",
        "context",
        "skills/account-claim-writing-trial",
        "claims",
        "work",
        "outputs",
    ]:
        (workspace / d).mkdir(parents=True, exist_ok=True)
    dossier = json.loads((SOURCE / "account-dossiers/account-dossier-v1.manifest.json").read_text())
    old = json.loads((SOURCE / "manifest.json").read_text())
    m = {
        k: dossier[k]
        for k in ["workspace_id", "project_id", "account_id", "run_id", "job_id", "context_id"]
    }
    m.update(
        trial_id=str(uuid4()),
        project_run_id=old["project_run_id"],
        database=DB,
        historical_evidence_revision=dossier["evidence_revision"],
        prepared_at=datetime.now(UTC).isoformat(),
    )
    scope = scope_from(m)
    op = OperationScope(scope.workspace_id, scope.run_id, scope.job_id, scope.account_id)
    engine = create_async_engine(url)
    storage = FsStorage(OUT / "blobs")
    async with engine.begin() as conn:
        initial = await persist_source(
            conn,
            storage,
            op,
            kind="research_report",
            body=(SOURCE / "account-dossiers/account-dossier-v1.md").read_text(),
            original_key=dossier["report"]["artifact_key"],
            origin_locator="saved_initial_account_dossier_v1",
            observed_at=datetime(2026, 9, 24, tzinfo=UTC),
            metadata={
                "title": "Initial account dossier v1 — agent synthesis, not external evidence"
            },
        )
        grant = await grant_manifest(conn, op, consumer_id=UUID(m["trial_id"]))
        m["grant_id"] = str(grant.grant_id)
        ids = [UUID(r["source_id"]) for r in dossier["source_inventory"]["sources"]]
        records = (
            (
                await conn.execute(
                    text(
                        "SELECT * FROM arv2_evidence_source "
                        "WHERE source_id=ANY(:ids) ORDER BY revision"
                    ),
                    {"ids": ids},
                )
            )
            .mappings()
            .all()
        )
        if len(records) != len(ids):
            raise ValueError("Initial manifest source inventory incomplete in clone")
        sources = []
        index = [
            "# Saved account source inventory",
            "",
            "All entries are account sources from the initial dossier manifest. "
            "No person-job or later reconciliation findings.",
            "",
        ]
        for record in [*records, initial.model_dump()]:
            if record["job_id"] != scope.job_id:
                raise ValueError("Non-account-job source in initial inventory")
            read = await read_source(conn, storage, grant, record["source_id"])
            path = read["path"]
            body = read["text"]
            try:
                rendered = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
            except ValueError:
                rendered = body
            content = (
                f"Source URL: {read['source_url']}\nSource kind: {read['kind']}\n"
                f"Origin: {record['origin_locator']}\n\n{rendered}\n"
            )
            (workspace / path.lstrip("/")).write_text(content)
            row = {
                "path": path,
                "source_id": str(record["source_id"]),
                "url": read["source_url"],
                "kind": read["kind"],
                "locator": record["origin_locator"],
                "sha256": record["artifact_sha256"],
                "title": read["metadata"].get("title"),
                "characters": len(body),
            }
            sources.append(row)
            index.append(
                f"- `{path}` | {row['kind']} | {row['characters']} chars | "
                f"{row['url'] or 'no public URL'} | {row['locator']}"
            )
        m["sources"] = sources
    await engine.dispose()
    (workspace / "evidence/index.md").write_text("\n".join(index) + "\n")
    save(workspace / "evidence/index.json", sources)
    shutil.copyfile(
        SOURCE / "account-dossiers/account-dossier-v1.md", workspace / "context/account-dossier.md"
    )
    shutil.copyfile(SOURCE / "head-brief.generated.md", workspace / "context/delegation-brief.md")
    for file in (SOURCE / "context").glob("*.md"):
        shutil.copyfile(file, workspace / "context" / file.name)
    shutil.copyfile(DRAFT / "SKILL.md", workspace / "skills/account-claim-writing-trial/SKILL.md")
    save(workspace / "claims/index.json", [])
    save(
        workspace / "trial-manifest.json",
        {
            "account": "Zafran Security (zafran.io)",
            "context": "/context/",
            "dossier": "/context/account-dossier.md",
            "sources": "/evidence/index.md",
            "claims": "/claims/index.json",
            "capabilities": "/capabilities.json",
            "coverage_output": "/work/coverage.md",
            "review_output": "/work/review.md",
            "claim_export": "/claims/index.json",
            "source_count": len(sources),
            "historical_evidence_revision": 351,
            "claim_scope": "only this isolated trial",
            "missing_originals": [],
            "date_of_original_research": "2026-09-24",
            "correction_limit": (
                "No correction tool in this first harness. Record an unresolved correction "
                "explicitly; a new write is not a replacement."
            ),
        },
    )
    save(
        workspace / "capabilities.json",
        {
            "record_research_finding": Finding.model_json_schema(),
            "read_trial_claims": (
                "Return all trial records including all review statuses; optional text query"
            ),
            "finish_trial": (
                "Export every stored record and end; supply summary and remaining gaps. "
                "Write /work/coverage.md and /work/review.md first."
            ),
        },
    )
    system = (DRAFT / "SYSTEM.md").read_text()
    task = (
        (DRAFT / "TASK.md")
        .read_text()
        .split("<!--")[0]
        .replace("{{claim_writing_skill_path}}", "/skills/account-claim-writing-trial/SKILL.md")
        .replace("{{trial_manifest_path}}", "/trial-manifest.json")
    )
    (OUT / "system-prompt.md").write_text(system)
    (OUT / "task-prompt.md").write_text(task)
    if dossier_mode:
        from account_dossier_trial import prepare_instructions

        prepare_instructions(OUT)
        m["trial_mode"] = "claim-ready-dossier"
    m["input_hashes"] = {
        str(f.relative_to(workspace)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in workspace.rglob("*")
        if f.is_file()
    }
    m["prompt_hashes"] = {
        name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
        for name in ["system-prompt.md", "task-prompt.md"]
    }
    m["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    m["limitations"] = [
        "Fresh Deep Agent with production account model, not original conversation",
        "Shared claim persistence and provenance; no C5/fleet lifecycle in this experiment",
        "Cloned historical identity/context IDs; "
        "isolated physical DB, blobs, output and write namespace",
        "Original source records and report preserved; wrapper duplicates remain discoverable",
    ]
    save(OUT / "manifest.json", m)
    print(json.dumps({"prepared": str(OUT), "database": DB, "sources": len(sources)}))


async def smoke(writer):
    async with writer.engine.connect() as conn:
        tx = await conn.begin()
        try:
            path = next(iter(writer.sources))
            base = {
                "topic": "OFFLINE CONTRACT PROBE",
                "claim_type": "reported_statement",
                "finding": "Scripted contract probe, not research.",
                "source_paths": [path],
                "attribution": "Offline fixture",
            }
            a = Finding(**base, review=Review(status="supported", reason="Offline contract probe"))
            first = await writer.write(conn, a)
            again = await writer.write(conn, a)
            assert first["claim_id"] == again["claim_id"] and again["replayed"]
            cases = [
                ("duplicate", "qualified"),
                ("wrong_entity", "invalid"),
                ("insufficient_context", "unresolved"),
                ("potential_conflict", "qualified"),
            ]
            for status, expected in cases:
                r = Review(
                    status=status,
                    reason="Offline metadata probe",
                    duplicate_of=first["claim_id"] if status == "duplicate" else None,
                    conflicts_with=[first["claim_id"]] if status == "potential_conflict" else [],
                )
                receipt = await writer.write(conn, Finding(**base, review=r))
                assert receipt["status"] == expected and receipt["claim_id"]
            rows = await writer.rows(conn)
            assert len(rows) == 5 and all(
                r["write_markers"]["claim_kind"] == "attributed_statement" for r in rows
            )
            if writer.m.get("trial_mode") == "claim-ready-dossier":
                origin = {"id": "F001", "section": "Offline fixture", "dossier_sha256": "probe"}
                probe = Finding(
                    **{**base, "finding": "Exact “quotation” | line\ncontinued"}, review=a.review
                )
                receipt = await writer.write(conn, probe, dossier_entry=origin)
                replay = await writer.write(conn, probe, dossier_entry=origin)
                assert replay["claim_id"] == receipt["claim_id"] and replay["replayed"]
                stored = next(r for r in await writer.rows(conn) if r["id"] == receipt["claim_id"])
                assert stored["value_json"]["finding"] == probe.finding
                assert stored["value_json"]["dossier_entry"] == origin
            try:
                await writer.write(
                    conn,
                    Finding(
                        **{**base, "source_paths": ["/evidence/not-present.json"]}, review=a.review
                    ),
                )
            except ValueError:
                pass
            else:
                raise AssertionError("Unknown source accepted")
        finally:
            await tx.rollback()
    assert not await writer.export()
    save(
        OUT / "offline-checks.json",
        {
            "passed": [
                "real stored statuses",
                "reported_statement mapping",
                "duplicate references",
                "identical retry",
                "unknown source rejection",
                "rollback leaves zero trial claims",
            ],
            "provider_calls": 0,
        },
    )
    print("Offline real-database writer checks passed; zero trial claims remain.")


async def run(writer):
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, FilesystemBackend
    from dotenv import dotenv_values
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.memory import InMemorySaver
    from research_preview_support import Audit, PreviewTools

    from clue_agents.tool_recovery import ToolRepairRoundsMiddleware
    from clue_api.agent_model_wiring import build_agent_model_provider
    from clue_api.langfuse_callbacks import build_langfuse_callbacks
    from clue_config import Secrets, default_gateway_config, load_settings
    from clue_obs import setup
    from clue_obs.langfuse import flush_langfuse, observation, propagate_trace
    from clue_obs.production import install_production_langfuse, install_production_tracing

    if (OUT / "started.json").exists():
        raise ValueError("Already started; do not silently repeat a paid run.")
    for name, sha in writer.m["input_hashes"].items():
        if name == "claims/index.json":
            continue
        assert hashlib.sha256((OUT / "workspace" / name).read_bytes()).hexdigest() == sha, name
    for name, sha in writer.m["prompt_hashes"].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == sha, name
    assert (OUT / "offline-checks.json").exists()
    env = dotenv_values(ROOT / ".env")
    for key in ["ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT"]:
        if env.get(key):
            os.environ[key] = env[key]
    os.environ["CLUE_LANGFUSE_ENVIRONMENT"] = "account-claims-trial-20260925"
    settings = load_settings(_env_file=ROOT / ".env")
    secrets = Secrets(_env_file=ROOT / ".env")
    setup(fmt="json", run_log_path=OUT / "runtime-events.jsonl")
    tracing = install_production_tracing(settings, secrets, service_name="account-claims-trial")
    lf_enabled = install_production_langfuse(
        settings, secrets, runtime=tracing, service_name="account-claims-trial"
    )
    config = default_gateway_config()
    model_id = env["ACCOUNT_RESEARCH_AGENT_MODEL"]
    model = build_agent_model_provider(config=config, secrets=secrets).build(
        model_id=model_id,
        role="account_research",
        timeout_s=config.timeout_s,
        max_retries=config.max_retries,
        max_output_tokens=16000,
        temperature=0,
    )
    (OUT / "traces").mkdir(exist_ok=True)
    audit = Audit(OUT, monotonic())
    lf = build_langfuse_callbacks()
    callbacks = [audit, *([lf.handler] if lf else [])]

    async def record_research_finding(**kwargs):
        """Store one finding with source references and explicit review status.

        Exact retries reuse the receipt; changes create a new record.
        No automatic source merging or correction.
        """
        async with writer.lock:
            async with writer.engine.begin() as conn:
                result = await writer.write(conn, Finding.model_validate(kwargs))
            await writer.export()
        return json.dumps(result, default=str)

    async def read_trial_claims(query: str = ""):
        """Read all saved trial statuses.

        Optional case-insensitive text search; no other run's claims are exposed.
        """
        async with writer.engine.begin() as conn:
            rows = await writer.rows(conn)
        return json.dumps(
            [r for r in rows if query.lower() in json.dumps(r, default=str).lower()],
            ensure_ascii=False,
            default=str,
        )

    async def finish_trial(summary: str, gaps: list[str]):
        """Finish the isolated trial after writes settle.

        Export all claims, including flagged records. Report incomplete processing honestly.
        """
        async with writer.lock:
            rows = await writer.export()
        save(
            OUT / "agent-completion.json",
            {
                "summary": summary,
                "gaps": gaps,
                "records": len(rows),
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
        return json.dumps({"finished": True, "records": len(rows), "export": "/claims/index.json"})

    tools = [
        StructuredTool.from_function(coroutine=record_research_finding, args_schema=Finding),
        StructuredTool.from_function(coroutine=read_trial_claims),
        StructuredTool.from_function(coroutine=finish_trial, return_direct=True),
    ]
    dossier_mode = writer.m.get("trial_mode") == "claim-ready-dossier"
    if dossier_mode:
        from account_dossier_trial import DOSSIER, inspect_dossier, render_dossier

        async def validate_dossier():
            """Check the saved dossier's syntax and references, without judging its meaning."""
            path = OUT / "workspace" / DOSSIER
            if not path.exists():
                return json.dumps({"errors": ["Write /" + DOSSIER + " first."]})
            records, errors = inspect_dossier(path.read_text(), writer.sources)
            return json.dumps({"entries": len(records), "errors": errors})

        async def finish_dossier(summary: str, gaps: list[str]):
            """Freeze the dossier for subsequent mechanical import; report actual remaining gaps."""
            feedback = json.loads(await validate_dossier())
            if feedback["errors"]:
                return json.dumps({"finished": False, **feedback})
            if not feedback["entries"]:
                return json.dumps({"finished": False, "error": "Dossier has no finding entries"})
            path = OUT / "workspace" / DOSSIER
            shutil.copyfile(path, OUT / "dossier.entries.md")
            records, _ = inspect_dossier(path.read_text(), writer.sources)
            (OUT / "dossier.readable.md").write_text(render_dossier(records, writer.sources))
            save(
                OUT / "agent-completion.json",
                {
                    "summary": summary,
                    "gaps": gaps,
                    "entries": len(records),
                    "finished_at": datetime.now(UTC).isoformat(),
                    "claims_written_by_agent": 0,
                    "dossier_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
            )
            return json.dumps(
                {
                    "finished": True,
                    "entries": len(records),
                    "instruction": "Dossier frozen. Return your final summary now.",
                }
            )

        tools = [
            StructuredTool.from_function(coroutine=validate_dossier),
            StructuredTool.from_function(coroutine=finish_dossier),
        ]
    allowed = {
        "ls",
        "read_file",
        "glob",
        "grep",
        "write_file",
        "edit_file",
        "write_todos",
        *[t.name for t in tools],
    }

    class BoundTools(PreviewTools):
        async def awrap_tool_call(self, request, handler):
            call = request.tool_call
            if (
                dossier_mode
                and (OUT / "agent-completion.json").exists()
                and call["name"] in {"write_file", "edit_file", "finish_dossier"}
            ):
                return ToolMessage(
                    content="Dossier is frozen; return your final summary.", tool_call_id=call["id"]
                )
            if call["name"] in {"write_file", "edit_file"}:
                path = call["args"].get("file_path", "")
                if not path.startswith(("/work/", "/outputs/")) or ".." in Path(path).parts:
                    return ToolMessage(
                        content="Original inputs are read-only; write in /work/ or /outputs/.",
                        tool_call_id=call["id"],
                    )
            try:
                return await super().awrap_tool_call(request, handler)
            except Exception as e:
                audit.event(
                    "tool_error",
                    name=call["name"],
                    error_type=type(e).__name__,
                    error=str(e)[:1600],
                )
                return ToolMessage(
                    content=json.dumps({"error": str(e)[:1600], "governed_repair_budgeted": True}),
                    tool_call_id=call["id"],
                    status="error",
                )

    backend = CompositeBackend(
        default=FilesystemBackend(root_dir=OUT / "workspace", virtual_mode=True),
        routes={},
        artifacts_root="/work",
    )
    graph = create_deep_agent(
        model=model,
        system_prompt=(OUT / "system-prompt.md").read_text(),
        tools=tools,
        middleware=[BoundTools(allowed), ToolRepairRoundsMiddleware()],
        backend=backend,
        checkpointer=InMemorySaver(),
        name="isolated-account-dossier-author" if dossier_mode else "isolated-account-claim-writer",
    )
    shutil.copyfile(Path(__file__), OUT / "harness.executed.py")
    if dossier_mode:
        import account_dossier_trial

        shutil.copyfile(account_dossier_trial.__file__, OUT / "dossier-adapter.executed.py")
    save(
        OUT / "started.json",
        {
            "time": datetime.now(UTC).isoformat(),
            "model": model_id,
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "langfuse": lf_enabled,
            "trial_id": writer.m["trial_id"],
        },
    )
    try:
        with (
            propagate_trace(
                trace_name="account-claims-trial",
                session_id=writer.m["trial_id"],
                tags=["account-claims-trial", "r13-replay"],
            ),
            observation(name="account-claims-trial", as_type="span"),
        ):
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=(OUT / "task-prompt.md").read_text())]},
                config={
                    "callbacks": callbacks,
                    "recursion_limit": 200,
                    "configurable": {"thread_id": writer.m["trial_id"]},
                },
            )
        save(OUT / "messages.json", [m.model_dump(mode="json") for m in result["messages"]])
        if not (OUT / "agent-completion.json").exists():
            raise RuntimeError("Agent ended without finishing trial")
    except BaseException as e:
        save(
            OUT / "interruption.json",
            {"type": type(e).__name__, "error": str(e), "time": datetime.now(UTC).isoformat()},
        )
        raise
    finally:
        await writer.export()
        flush_langfuse()
    if dossier_mode:
        from account_dossier_trial import import_dossier

        with observation(name="account-dossier-programmatic-import", as_type="span"):
            receipt = await import_dossier(writer, OUT)
        flush_langfuse()
        print(json.dumps({"imported": receipt["stored"], "errors": receipt["errors"]}, default=str))
    print("Agent trial finished; inspect claims.md and workspace/work/coverage.md.")


async def main():
    global OUT, DB
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "smoke", "run", "export", "import-dossier"])
    parser.add_argument("--run-number", type=int, default=1)
    parser.add_argument(
        "--dossier-mode", action="store_true", help="Prepare the isolated record-dossier experiment"
    )
    args = parser.parse_args()
    OUT, DB = run_paths(args.run_number)
    if args.action == "prepare":
        await prepare(dossier_mode=args.dossier_mode)
        return
    m = json.loads((OUT / "manifest.json").read_text())
    if m["database"] != DB or DB == SOURCE_DB:
        raise ValueError("Refuse non-trial database")
    _, url = db_config()
    engine = create_async_engine(url)
    writer = Writer(m, engine, FsStorage(OUT / "blobs"))
    try:
        if args.action == "smoke":
            await smoke(writer)
        elif args.action == "run":
            await run(writer)
        elif args.action == "import-dossier":
            if m.get("trial_mode") != "claim-ready-dossier":
                raise ValueError("Not a dossier-mode trial")
            from account_dossier_trial import import_dossier

            receipt = await import_dossier(writer, OUT)
            print(json.dumps({"stored": receipt["stored"], "errors": receipt["errors"]}))
        else:
            await writer.export()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
