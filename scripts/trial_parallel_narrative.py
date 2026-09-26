"""Offline preparation and explicit paid execution of the saved-claim narrative trial.

No research tools, application database, fleet or page publication. Model calls use the
existing governed model provider, usage accounting and Langfuse callback composition.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / ".artifacts/narrative-selection-20260926"
DRAFT = ROOT / "docs/superpowers/drafts/2026-09-26-parallel-narrative/PROMPTS.md"
OUTPUT_VERSION = 3
SECTION_ORDER = {
    "overview": [
        "what-they-do",
        "why-they-fit",
        "why-now",
        "buying-committee",
        "approach",
        "research-notes",
    ],
    "insights": [
        "business-context",
        "organization-and-teams",
        "money-and-momentum",
        "strategy-and-initiatives",
        "tools-they-already-use",
        "buying-signals",
        "contact-insights",
    ],
    "nick": [
        "why-this-person",
        "problem-right-now",
        "experience-and-perspective",
        "angles",
        "openers",
        "research-notes",
    ],
}


def section_order(path):
    page, section = path.stem.split("--", 1)
    order = SECTION_ORDER.get(page, [])
    return (page, order.index(section) if section in order else len(order), section)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sentence(Strict):
    text: str = Field(min_length=1, max_length=4000)
    claimIds: list[str] = Field(max_length=30)
    sellerEvidenceIds: list[str]
    kind: Literal["fact", "inference", "quote", "qualified", "gap"]
    qualifications: list[str] = Field(max_length=20)


class Item(Strict):
    h2: str = Field(min_length=1, max_length=180)
    body: list[Sentence] = Field(min_length=1, max_length=20)
    contactIds: list[str] = Field(max_length=10)
    sendLine: Sentence | None


class Section(Strict):
    key: str
    intro: list[Sentence] = Field(max_length=30)
    items: list[Item] = Field(max_length=30)
    gaps: list[str] = Field(max_length=30)


class SelectionNote(Strict):
    claimIds: list[str]
    reason: str


class Output(Strict):
    section: Section
    selectionNotes: list[SelectionNote]
    contextGaps: list[str]


def require_current_output(manifest):
    if manifest.get("output_version") != OUTPUT_VERSION:
        raise ValueError(
            f"This runner requires output version {OUTPUT_VERSION}. Prepare a fresh directory; "
            "use the archived executed runner to inspect/reproduce older contracts."
        )


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def localize_claims(packet, request_id):
    """Request-scoped aliases; never mutate evidence text or durable input records."""
    ids = [c["claim_id"] for c in packet["claims"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate claim IDs in packet; prepare one record per claim.")
    reverse = {cid: f"C{i}" for i, cid in enumerate(ids, 1)}
    view = json.loads(json.dumps(packet))

    def linked(cid):
        if cid is None:
            return None
        if cid not in reverse:
            raise ValueError(
                f"Linked claim {cid} is absent from packet; include its context first."
            )
        return reverse[cid]

    for claim in view["claims"]:
        claim["claim_id"] = reverse[claim["claim_id"]]
        if "superseded_by" in claim:
            claim["superseded_by"] = linked(claim["superseded_by"])
        value = claim["value_json"]
        review = value.get("review") if isinstance(value, dict) else None
        if isinstance(review, dict):
            if "duplicate_of" in review:
                review["duplicate_of"] = linked(review["duplicate_of"])
            if "conflicts_with" in review:
                review["conflicts_with"] = [linked(cid) for cid in review["conflicts_with"]]
    mapping = {
        "request_id": request_id,
        "packet_sha256": hashlib.sha256(compact(packet).encode()).hexdigest(),
        "aliases": {alias: cid for cid, alias in reverse.items()},
    }
    return view, mapping


def check_alias_binding(request, mapping):
    expected_view, expected_mapping = localize_claims(request["packet"], request["request_id"])
    if mapping != expected_mapping or request["model_packet"] != expected_view:
        raise ValueError("Alias mapping does not belong to this request and frozen packet.")


def resolve_claim_aliases(raw, request, mapping, docs):
    check_alias_binding(request, mapping)
    result = validate(raw, request["model_packet"], docs)
    aliases = mapping["aliases"]
    for sentence in sentences(result):
        sentence["claimIds"] = [aliases[cid] for cid in sentence["claimIds"]]
    for note in result["selectionNotes"]:
        note["claimIds"] = [aliases[cid] for cid in note["claimIds"]]
    # Persist and render durable UUID references, never request-local aliases.
    return validate(json.dumps(result), request["packet"], docs)


def load_request(out, item):
    request = json.loads((out / "inputs" / item["file"]).read_text())
    mapping_path = out / "reference-maps" / item["file"]
    if sha(mapping_path) != item["reference_map_sha256"]:
        raise ValueError("Saved alias mapping changed after preparation.")
    mapping = json.loads(mapping_path.read_text())
    check_alias_binding(request, mapping)
    return request, mapping


def prompts():
    text = DRAFT.read_text()
    blocks = re.findall(r"```text\n(.*?)\n```", text, re.S)
    assignments = {}
    for m in re.finditer(r"^### (.*?)\n\n```text\n(.*?)\n```", text, re.M | re.S):
        assignments[m[1]] = m[2]
    return blocks[0], blocks[1], assignments, blocks[-1]


def model_claim(original):
    """Remove only the archived dossier mirror; every other value survives exactly."""
    result = json.loads(json.dumps(original))
    v = result["value_json"]
    if isinstance(v, dict) and "dossier_entry" in v:
        entry = v.pop("dossier_entry")
        archived = entry.get("original", {})
        # These are the substantive keys which must already exist outside the mirror.
        for key in (
            "finding",
            "topic",
            "claim_type",
            "attribution",
            "time_context",
            "qualifications",
            "agent_interpretation",
        ):
            if key in archived:
                assert archived[key] == v.get(key), (original["claim_id"], key)
        result["dossier_origin"] = {k: val for k, val in entry.items() if k != "original"}
        # Keep anything found only in the original rather than dropping it by assumption.
        extra = {
            k: val for k, val in archived.items() if k not in v and k not in ("id", "source_paths")
        }
        if extra:
            result["original_only"] = extra
        if archived.get("source_paths"):
            result["original_source_paths"] = archived["source_paths"]
    return result


def prepare(out, model, concurrency):
    if (out / "started.json").exists():
        raise ValueError("A paid run already started here; preserve it and use another directory.")
    began = monotonic()
    source_manifest = json.loads((INPUT / "manifest.json").read_text())
    for name, digest in source_manifest["files"].items():
        assert sha(INPUT / name) == digest, name
    shared = json.loads((INPUT / "shared-context.json").read_text())
    assert all(d["pinned_hash_matched"] for d in shared["selected_documents"])
    system, template, assignments, repair = prompts()
    documents = shared["selected_documents"]
    for doc in documents:
        assert hashlib.sha256(doc["content"].encode()).hexdigest() == doc["sha256"]
    context = {
        "source_run_id": shared["source_run_id"],
        "selected_context": {
            k: v for k, v in shared["prepared_context"].items() if k != "field_catalog"
        },
        "seller_documents": documents,
        "delegation_brief": shared["delegation_brief"],
        "context_gaps": shared["context_gaps"],
    }
    names = {
        o["entity_id"]: o["entity"]
        for o in json.loads((INPUT / "routing-overlay.json").read_text())
    }
    contacts = {k: v for k, v in names.items() if v != "Account"}
    packets = []
    for path in sorted((INPUT / "packets").glob("*.json")):
        original = json.loads(path.read_text())
        claims = [model_claim(c) for c in original["claims"]]
        page, key = original["page"], original["section_key"]
        assignment = assignments[
            "overview or contact / research-notes" if key == "research-notes" else f"{page} / {key}"
        ]
        fields = {c["field_key"] for c in claims}
        packet = {
            "page": page,
            "section_key": key,
            "snapshot_date": "2026-09-26",
            "subject": "Nick Fisher" if page == "contact" else "Zafran Security",
            "known_contacts": contacts,
            "field_definitions": [
                f for f in shared["prepared_context"]["field_catalog"] if f["field_key"] in fields
            ],
            "claims": claims,
        }
        request_id = str(uuid4())
        model_packet, mapping = localize_claims(packet, request_id)
        system_full = system + "\n\nPINNED SELLER AND PROJECT CONTEXT (DATA)\n" + compact(context)
        user = template.replace("{{section_instruction}}", assignment).replace(
            "{{packet_json}}", compact(model_packet)
        )
        request = {
            "system": system_full,
            "user": user,
            "packet": packet,
            "model_packet": model_packet,
            "request_id": request_id,
        }
        save(out / "inputs" / path.name, request)
        save(out / "reference-maps" / path.name, mapping)
        save(out / "schemas" / path.name, reference_schema(model_packet, documents))
        packets.append(
            {
                "file": path.name,
                "section": original["section"],
                "claim_count": len(claims),
                "request_characters": len(system_full) + len(user),
                "input_sha256": sha(out / "inputs" / path.name),
                "reference_map_sha256": sha(out / "reference-maps" / path.name),
                "schema_sha256": sha(out / "schemas" / path.name),
            }
        )
    assert len(packets) == 19
    save(out / "schema.json", Output.model_json_schema())
    save(out / "shared-context.json", context)
    (out / "system-prompt.txt").write_text(system)
    (out / "repair-prompt.txt").write_text(repair)
    save(
        out / "prepared.json",
        {
            "output_version": OUTPUT_VERSION,
            "model": model,
            "concurrency": concurrency,
            "structural_retries": 1,
            "max_output_tokens": 32768,
            "transport_timeout_seconds": 600,
            "preparation_seconds": monotonic() - began,
            "source_manifest_sha256": sha(INPUT / "manifest.json"),
            "prompt_sha256": sha(DRAFT),
            "script_sha256": sha(Path(__file__)),
            "packets": packets,
            "schema_sha256": sha(out / "schema.json"),
            "shared_context_sha256": sha(out / "shared-context.json"),
            "repair_prompt_sha256": sha(out / "repair-prompt.txt"),
            "changes": (
                "Output v3 uses request-local claim aliases resolved to durable IDs; "
                "optional selection notes replace the per-claim ledger; "
                "citation accounting is computed in code. Inputs omit only duplicate dossier "
                "original mirrors and unrelated field definitions; no findings shortened."
            ),
        },
    )
    return packets


def sentences(output):
    section = output["section"]
    yield from section["intro"]
    for item in section["items"]:
        yield from item["body"]
        if item["sendLine"]:
            yield item["sendLine"]


def validate(raw, packet, docs):
    """Structural errors permit one repair; meaning/coverage remain diagnostics."""
    result = Output.model_validate_json(raw).model_dump()
    if result["section"]["key"] != packet["section_key"]:
        raise ValueError("Returned the wrong section key.")
    ids = {c["claim_id"] for c in packet["claims"]}
    docids = {d["document_id"] for d in docs}
    invalid_claims, invalid_documents, invalid_contacts = set(), set(), set()
    for sentence in sentences(result):
        invalid_claims.update(set(sentence["claimIds"]) - ids)
        invalid_documents.update(set(sentence["sellerEvidenceIds"]) - docids)
    for item in result["section"]["items"]:
        invalid_contacts.update(set(item["contactIds"]) - set(packet["known_contacts"]))
    for note in result["selectionNotes"]:
        invalid_claims.update(set(note["claimIds"]) - ids)
    if invalid_claims or invalid_documents or invalid_contacts:
        raise ValueError(
            json.dumps(
                {
                    "invalid_claim_ids": sorted(invalid_claims),
                    "invalid_seller_document_ids": sorted(invalid_documents),
                    "invalid_contact_ids": sorted(invalid_contacts),
                    "instruction": (
                        "Use exact IDs from the supplied packet; preserve factual meaning."
                    ),
                }
            )
        )
    return result


def reference_schema(packet, docs):
    """Constrain literal references, not which substantive claims the writer selects."""
    schema = Output.model_json_schema()
    defs = schema["$defs"]
    defs["ClaimReference"] = {"type": "string", "enum": [c["claim_id"] for c in packet["claims"]]}
    ref = {"$ref": "#/$defs/ClaimReference"}
    defs["Sentence"]["properties"]["claimIds"]["items"] = ref
    defs["SelectionNote"]["properties"]["claimIds"]["items"] = ref
    defs["Sentence"]["properties"]["sellerEvidenceIds"]["items"] = {
        "type": "string",
        "enum": [d["document_id"] for d in docs],
    }
    defs["Item"]["properties"]["contactIds"]["items"] = {
        "type": "string",
        "enum": list(packet["known_contacts"]),
    }
    defs["Section"]["properties"]["key"] = {"type": "string", "enum": [packet["section_key"]]}
    return schema


def prepare_recovery(source, out):
    """One additional, explicit recovery attempt for failed sections only."""
    if out.exists():
        raise ValueError("Recovery output already exists; use a fresh directory.")
    assert (source / "summary.json").exists(), "Wait for the first trial to settle."
    m = json.loads((source / "prepared.json").read_text())
    require_current_output(m)
    docs = json.loads((source / "shared-context.json").read_text())["seller_documents"]
    repair = (source / "repair-prompt.txt").read_text()
    chosen = []
    for item in m["packets"]:
        slug = Path(item["file"]).stem
        receipt = json.loads((source / "receipts" / f"{slug}.json").read_text())
        if receipt["status"] == "completed":
            continue
        assert receipt["status"] == "structural_failure", (
            "Do not replay ambiguous provider failures."
        )
        request, mapping = load_request(source, item)
        last_attempt = receipt["attempts"][-1]["attempt"]
        previous = json.loads((source / "responses" / f"{slug}.{last_attempt}.json").read_text())[
            "content"
        ]
        raw = (
            previous
            if isinstance(previous, str)
            else "".join(b["text"] for b in previous if b.get("type") == "text")
        )
        try:
            resolve_claim_aliases(raw, request, mapping, docs)
        except ValueError as exc:
            feedback = str(exc)
        else:
            raise ValueError("Already valid output must not be regenerated.")
        request["user"] += "\n\n" + repair.replace("{{validation_errors_json}}", feedback).replace(
            "{{previous_response}}", raw
        )
        save(out / "inputs" / item["file"], request)
        save(out / "reference-maps" / item["file"], mapping)
        save(out / "schemas" / item["file"], reference_schema(request["model_packet"], docs))
        chosen.append(
            {
                **item,
                "input_sha256": sha(out / "inputs" / item["file"]),
                "schema_sha256": sha(out / "schemas" / item["file"]),
                "request_characters": len(request["system"]) + len(request["user"]),
            }
        )
    assert chosen
    for name in ("schema.json", "shared-context.json", "repair-prompt.txt", "system-prompt.txt"):
        shutil.copyfile(source / name, out / name)
    m.update(
        packets=chosen,
        structural_retries=0,
        recovery_of=str(source),
        preparation_seconds=0,
        script_sha256=sha(Path(__file__)),
        changes="Failed sections only; exact bad-ID feedback and provider reference enums.",
    )
    save(out / "prepared.json", m)
    return chosen


def diagnose(result, packet):
    """Compute citation accounting; uncited does not mean omitted or unsupported."""
    cited = {cid for s in sentences(result) for cid in s["claimIds"]}
    diag = {
        "method": "supplied_minus_sentence_citations",
        "limitation": "Citation presence does not prove semantic coverage or entailment.",
    }
    for role in ("primary", "context"):
        expected = {c["claim_id"] for c in packet["claims"] if c["role"] == role}
        diag[role] = {
            "supplied_count": len(expected),
            "supplied_claim_ids": sorted(expected),
            "cited_claim_ids": sorted(expected & cited),
            "not_directly_cited_claim_ids": sorted(expected - cited),
        }
    # Notes are advisory explanations, never evidence that a claim appeared in prose.
    diag["selection_notes"] = result["selectionNotes"]
    diag["cited_claims"] = len(cited)
    diag["uncited_primary_claims"] = sorted(
        {c["claim_id"] for c in packet["claims"] if c["role"] == "primary"} - cited
    )
    diag["uncited_factual_sentences"] = [
        s["text"]
        for s in sentences(result)
        if s["kind"] in ["fact", "quote"] and not s["claimIds"] and not s["sellerEvidenceIds"]
    ]
    return diag


def render(out):
    shared = json.loads((out / "shared-context.json").read_text())
    docs = {d["document_id"]: d for d in shared["seller_documents"]}
    pages = {}
    for request_path in sorted((out / "inputs").glob("*.json"), key=section_order):
        slug = request_path.stem
        packet = json.loads(request_path.read_text())["packet"]
        path = out / "sections" / f"{slug}.json"
        page = slug.split("--")[0]
        lines = pages.setdefault(
            page,
            [
                f"# {page}: narrative trial",
                "",
                (
                    "Generated from saved r18 claims. Trial output, not published "
                    "to the application. "
                    "Source links resolve supplied claim references; "
                    "they do not certify entailment."
                ),
                "",
            ],
        )
        lines += [f"## {packet['section_key']}", ""]
        if not path.exists():
            lines += ["Section failed or pending; see the run receipt.", ""]
            continue
        result = json.loads(path.read_text())
        byid = {c["claim_id"]: c for c in packet["claims"]}

        def sentence(s, byid=byid):
            urls = []
            for cid in s["claimIds"]:
                c = byid[cid]
                v = c["value_json"]
                sources = v.get("sources", []) if isinstance(v, dict) else []
                found = [src["url"] for src in sources if isinstance(src, dict) and src.get("url")]
                if c.get("source_url"):
                    found.append(c["source_url"])
                if not found:
                    found = ["../../../narrative-selection-20260926/complete-findings.md"]
                for url in found:
                    pair = (cid, url)
                    if pair not in urls:
                        urls.append(pair)
            refs = " ".join(f"[{cid[:8]}]({url})" for cid, url in urls)
            refs += " " + " ".join(
                f"[seller {d[:8]}](../shared-context.json)"
                for d in s["sellerEvidenceIds"]
                if d in docs
            )
            quals = (
                ("\n\nQualifications: " + "; ".join(s["qualifications"]))
                if s["qualifications"]
                else ""
            )
            return f"{s['text']} {refs.strip()}\n\n*{s['kind']}*{quals}\n"

        for s in result["section"]["intro"]:
            lines += [sentence(s), ""]
        for item in result["section"]["items"]:
            lines += [f"### {item['h2']}", ""]
            for s in item["body"]:
                lines += [sentence(s), ""]
            if item["sendLine"]:
                lines += ["Suggested opener:", sentence(item["sendLine"]), ""]
        lines += ["Gap: " + g for g in result["section"]["gaps"]]
        lines += ["Context gap: " + g for g in result["contextGaps"]]
        lines += [""]
    for name, lines in pages.items():
        (out / "pages").mkdir(exist_ok=True)
        (out / "pages" / f"{name}.md").write_text("\n".join(lines) + "\n")


async def run(out):
    from langchain_core.messages import HumanMessage, SystemMessage
    from research_preview_support import Audit, content

    from clue_api.agent_model_wiring import build_agent_model_provider
    from clue_api.langfuse_callbacks import build_langfuse_callbacks
    from clue_config import Secrets, default_gateway_config, load_settings
    from clue_gateway.metadata import cost_cents_from_metadata
    from clue_obs import setup
    from clue_obs.langfuse import current_ids, flush_langfuse, observation, propagate_trace
    from clue_obs.production import install_production_langfuse, install_production_tracing

    if (out / "started.json").exists():
        raise ValueError("This paid trial already started; do not automatically buy it again.")
    m = json.loads((out / "prepared.json").read_text())
    require_current_output(m)
    for item in m["packets"]:
        assert sha(out / "inputs" / item["file"]) == item["input_sha256"]
        load_request(out, item)
        assert sha(out / "schemas" / item["file"]) == item["schema_sha256"]
    assert sha(out / "schema.json") == m["schema_sha256"]
    assert sha(out / "shared-context.json") == m["shared_context_sha256"]
    assert sha(out / "repair-prompt.txt") == m["repair_prompt_sha256"]
    settings = load_settings(_env_file=ROOT / ".env")
    secrets = Secrets(_env_file=ROOT / ".env")
    setup(fmt="json", run_log_path=out / "runtime-events.jsonl")
    runtime = install_production_tracing(settings, secrets, service_name="parallel-narrative-trial")
    enabled = install_production_langfuse(
        settings, secrets, runtime=runtime, service_name="parallel-narrative-trial"
    )
    if not enabled:
        raise ValueError("Langfuse is not configured; stop before any paid calls.")
    # Isolated transport allowance, not a page completion deadline. Large structured
    # responses may exceed the 60-second performance target and must still be saved.
    config = default_gateway_config().model_copy(
        update={"fallback_model": None, "timeout_s": m["transport_timeout_seconds"]}
    )
    model = build_agent_model_provider(config=config, secrets=secrets).build(
        model_id=m["model"],
        role="research_narrative",
        timeout_s=config.timeout_s,
        max_retries=0,
        max_output_tokens=m["max_output_tokens"],
        temperature=0,
    )
    # Provider-native structured output, passed through the existing governed wrapper.
    base_model = model
    model = base_model.bind(
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ResearchNarrativeSection",
                "strict": True,
                "schema": json.loads((out / "schema.json").read_text()),
            },
        }
    )
    runid = str(uuid4())
    began = monotonic()
    save(
        out / "started.json",
        {
            "run_id": runid,
            "model": m["model"],
            "started_at": datetime.now(UTC).isoformat(),
            "gateway_timeout_s": config.timeout_s,
            "langfuse_configured": enabled,
        },
    )
    (out / "traces").mkdir(exist_ok=True)
    audit = Audit(out, began)
    sem = asyncio.Semaphore(m["concurrency"])
    context = json.loads((out / "shared-context.json").read_text())
    receipts = []

    async def one(item):
        slug = Path(item["file"]).stem
        request, mapping = load_request(out, item)
        packet = request["packet"]
        section_model = model
        if item.get("schema_sha256"):
            schema_path = out / "schemas" / item["file"]
            assert sha(schema_path) == item["schema_sha256"]
            section_model = base_model.bind(
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ResearchNarrativeSection",
                        "strict": True,
                        "schema": json.loads(schema_path.read_text()),
                    },
                }
            )
        messages = [SystemMessage(content=request["system"]), HumanMessage(content=request["user"])]
        receipt = {
            "section": item["section"],
            "attempts": [],
            "input_sha256": item["input_sha256"],
            "request_id": request["request_id"],
            "reference_map_sha256": item["reference_map_sha256"],
        }
        async with sem:
            receipt["queue_seconds"] = monotonic() - began
            lf = build_langfuse_callbacks()
            assert lf is not None
            max_attempts = 1 + m["structural_retries"]
            for attempt in range(1, max_attempts + 1):
                callstart = monotonic()
                with observation(
                    "narrative.section.attempt",
                    metadata={
                        "section": item["section"],
                        "trial_run_id": runid,
                        "attempt": attempt,
                        "packet_hash": item["input_sha256"],
                        "request_id": request["request_id"],
                        "reference_map_sha256": item["reference_map_sha256"],
                        "claim_count": item["claim_count"],
                    },
                ) as obs:
                    ids = current_ids()
                    try:
                        answer = await section_model.ainvoke(
                            messages,
                            config={
                                "callbacks": [audit, lf.handler],
                                "run_name": slug,
                                "metadata": {
                                    "trial_run_id": runid,
                                    "section": item["section"],
                                    "attempt": attempt,
                                },
                            },
                        )
                        raw = content(answer)
                        save(
                            out / "responses" / f"{slug}.{attempt}.json",
                            answer.model_dump(mode="json"),
                        )
                        cents, cost_source = cost_cents_from_metadata(answer.response_metadata)
                        ar = {
                            "attempt": attempt,
                            "seconds": monotonic() - callstart,
                            "cost_cents": str(cents) if cents is not None else None,
                            "cost_source": cost_source,
                            "usage": answer.usage_metadata,
                            "response_metadata": answer.response_metadata,
                            "trace_id": ids.trace_id if ids else None,
                        }
                        receipt["attempts"].append(ar)
                        try:
                            result = resolve_claim_aliases(
                                raw, request, mapping, context["seller_documents"]
                            )
                        except Exception as exc:
                            ar["structural_error"] = str(exc)
                            obs.update(output={"status": "structural_error", "error": str(exc)})
                            if attempt == max_attempts:
                                receipt["status"] = "structural_failure"
                                break
                            repair = (
                                (out / "repair-prompt.txt")
                                .read_text()
                                .replace("{{validation_errors_json}}", json.dumps([str(exc)]))
                                .replace("{{previous_response}}", raw)
                            )
                            messages += [HumanMessage(content=repair)]
                            continue
                        save(out / "sections" / f"{slug}.json", result)
                        save(out / "diagnostics" / f"{slug}.json", diagnose(result, packet))
                        receipt["status"] = "completed"
                        obs.update(
                            output={
                                "status": "completed",
                                "item_count": len(result["section"]["items"]),
                            }
                        )
                        break
                    except Exception as exc:
                        receipt["status"] = "provider_or_runtime_failure"
                        receipt["error"] = str(exc)
                        receipt["failed_attempt_seconds"] = monotonic() - callstart
                        obs.update(
                            output={"status": receipt["status"], "error_type": type(exc).__name__}
                        )
                        break
            receipt["finished_seconds"] = monotonic() - began
            save(out / "receipts" / f"{slug}.json", receipt)
            receipts.append(receipt)
            print(
                json.dumps(
                    {
                        "section": item["section"],
                        "status": receipt["status"],
                        "seconds": round(receipt["finished_seconds"], 2),
                    }
                ),
                flush=True,
            )

    with propagate_trace(  # noqa: SIM117 -- keep the trace and trial span visually separate
        trace_name="parallel-narrative-trial",
        session_id=runid,
        metadata={
            "source_run_id": context["source_run_id"],
            "workspace_id": context["selected_context"]["workspace_id"],
            "project_id": context["selected_context"]["project_id"],
        },
        tags=["narrative-trial", "isolated"],
    ):
        with observation(
            "narrative.trial", metadata={"trial_run_id": runid, "model": m["model"]}
        ) as parent:
            ids = current_ids()
            save(out / "trace.json", {"trace_id": ids.trace_id if ids else None})
            await asyncio.gather(*(one(item) for item in m["packets"]))
            elapsed = monotonic() - began
            summary = {
                "run_id": runid,
                "model": m["model"],
                "wall_seconds": elapsed,
                "preparation_seconds": m["preparation_seconds"],
                "ready_to_stored_seconds": elapsed + m["preparation_seconds"],
                "over_60_second_target": elapsed + m["preparation_seconds"] > 60,
                "statuses": dict(Counter(r["status"] for r in receipts)),
                "known_cost_cents": sum(
                    float(a["cost_cents"])
                    for r in receipts
                    for a in r["attempts"]
                    if a.get("cost_cents") is not None
                ),
                "unpriced_attempts": sum(
                    a.get("cost_cents") is None for r in receipts for a in r["attempts"]
                ),
                "failed_calls_with_unknown_cost": sum(
                    r["status"] == "provider_or_runtime_failure" for r in receipts
                ),
                "page_settled_seconds": {
                    p: max(
                        r["finished_seconds"] for r in receipts if r["section"].startswith(p + "/")
                    )
                    + m["preparation_seconds"]
                    for p in sorted({r["section"].split("/")[0] for r in receipts})
                },
                "page_ready_seconds": {
                    p: (
                        max(
                            r["finished_seconds"]
                            for r in receipts
                            if r["section"].startswith(p + "/")
                        )
                        + m["preparation_seconds"]
                        if all(
                            r["status"] == "completed"
                            for r in receipts
                            if r["section"].startswith(p + "/")
                        )
                        else None
                    )
                    for p in sorted({r["section"].split("/")[0] for r in receipts})
                },
                "latency_scope": (
                    "Frozen selection overlay already exists; includes request preparation, "
                    "concurrency queue, callbacks/accounting and section storage. "
                    "Excludes historical "
                    "selection construction and later Markdown review/rendering."
                ),
                "receipts": receipts,
            }
            save(out / "summary.json", summary)
            parent.update(output={k: v for k, v in summary.items() if k != "receipts"})
    flush_langfuse()
    render(out)
    print(json.dumps({k: v for k, v in summary.items() if k != "receipts"}, indent=2), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prepare", "run", "render", "prepare-recovery"])
    ap.add_argument("--source", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="openai/gpt-6-luna")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    if args.concurrency < 1:
        raise ValueError("Concurrency must be positive.")
    if args.mode == "prepare":
        print(json.dumps(prepare(args.out, args.model, args.concurrency), indent=2))
    elif args.mode == "prepare-recovery":
        if args.source is None:
            raise ValueError("--source is required for recovery.")
        print(json.dumps(prepare_recovery(args.source, args.out), indent=2))
    elif args.mode == "run":
        asyncio.run(run(args.out))
    else:
        render(args.out)


if __name__ == "__main__":
    main()
