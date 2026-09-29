"""The four v3 media tools shared by account and person jobs."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import text

from clue_api.arv2 import media_acquisition as acquisition
from clue_api.arv2 import media_retrieval as retrieval
from clue_api.arv2 import media_store as store
from clue_api.arv2 import media_telemetry as telemetry
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.deepgram_media_client import DeepgramMediaError
from clue_api.arv2.gemini_media_client import GeminiMediaError
from clue_api.arv2.media_resolution import Resolution
from clue_api.arv2.media_types import Candidate, MediaModel
from clue_api.arv2.research_operations import fingerprint


class DiscoverMediaArgs(MediaModel):
    query: str = Field(min_length=3, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    include_domains: list[str] | None = Field(None, max_length=12)
    known_urls: list[str] = Field(default_factory=list, max_length=12)
    discovery_ref: UUID | None = None
    offset: int = Field(0, ge=0)
    page_size: int = Field(6, ge=1, le=10)


class ReadMediaArgs(MediaModel):
    url: str | None = None
    candidate_ref: UUID | None = None
    purpose: str = Field(min_length=1, max_length=2000)
    episode_hint: str | None = None
    alternate_urls: list[str] = Field(default_factory=list, max_length=8)
    repair_version: UUID | None = None
    refresh_expired: bool = False

    @model_validator(mode="after")
    def one_source(self) -> ReadMediaArgs:
        if (self.url is None) == (self.candidate_ref is None):
            raise ValueError("provide exactly one URL or candidate_ref")
        return self


class SearchTranscriptsArgs(MediaModel):
    query: str = Field(min_length=1, max_length=2000)
    item_refs: list[UUID] | None = Field(None, max_length=20)
    offset: int = Field(0, ge=0)
    page_size: int = Field(8, ge=1, le=8)
    search_ref: UUID | None = None


class OpenTranscriptArgs(MediaModel):
    version_ref: UUID | None = None
    passage_ref: str | None = None
    start: int = Field(0, ge=0)
    end: int | None = Field(None, gt=0)
    neighbors: int = Field(0, ge=0, le=2)
    quote_index: int | None = Field(None, ge=0)


async def discover_media(runtime: Any, args: DiscoverMediaArgs) -> dict[str, Any]:
    if args.discovery_ref:
        async with runtime._conn_factory() as conn:
            saved = await store.get_attempt(runtime, conn, args.discovery_ref)
        if saved["kind"] != "discovery":
            raise store.unavailable("not a discovery reference")
        aid = args.discovery_ref
        ids = saved["data"]["candidates"]
    else:
        request = {
            "query": " ".join(args.query.split()),
            "domains": sorted(args.include_domains or []),
            "urls": args.known_urls,
        }
        aid = uuid5(runtime.scope.job_id, "media-discovery:" + fingerprint(request))
        async with runtime._conn_factory() as conn:
            existing = (
                await conn.execute(
                    text(
                        "SELECT attempt_id FROM arv2_media_attempt WHERE workspace_id=:ws AND "
                        "job_id=:job AND attempt_id=:id"
                    ),
                    {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "id": aid},
                )
            ).scalar_one_or_none()
        if existing:
            return await discover_media(runtime, args.model_copy(update={"discovery_ref": aid}))
        candidates = []
        if args.known_urls:
            candidates = [Candidate(url=url) for url in args.known_urls]
        else:
            op, body = await runtime.operate(
                "exa",
                "media_discovery",
                request,
                lambda caller: runtime.clients.exa(caller).search(
                    request["query"],
                    num_results=20,
                    include_domains=args.include_domains,
                    label="media.discovery",
                ),
            )
            for result in body.get("results", []):
                if isinstance(result, dict) and result.get("url"):
                    candidates.append(
                        Candidate(
                            url=result["url"],
                            title=str(result.get("title") or "")[:500],
                            description=str(result.get("text") or "")[:1200],
                            identity_evidence=["discovery_result:" + str(op.operation_id)],
                        )
                    )
        ids = []
        async with runtime._conn_factory() as conn:
            for c in candidates:
                cid = uuid5(aid, c.url)
                await store.attempt(
                    runtime,
                    conn,
                    kind="candidate",
                    outcome="unverified",
                    purpose=args.purpose,
                    data=c.model_dump(mode="json"),
                    attempt_id=cid,
                )
                ids.append(str(cid))
            await store.attempt(
                runtime,
                conn,
                kind="discovery",
                outcome="found" if ids else "empty",
                purpose=args.purpose,
                data={"candidates": ids},
                attempt_id=aid,
            )
    output: list[dict[str, Any]] = []
    async with runtime._conn_factory() as conn:
        for cid in ids[args.offset : args.offset + args.page_size]:
            row = await store.get_attempt(runtime, conn, UUID(cid))
            candidate = Candidate.model_validate(row["data"])
            summary = {
                "candidate_ref": cid,
                "url": candidate.url,
                "title": candidate.title[:500],
                "description": candidate.description[:1200],
                "family": candidate.family,
                "identity": "unverified_candidate",
                "origin": candidate.identity_evidence,
                "media_url": candidate.media_url,
                "recording_status": "candidate_not_yet_attempted",
            }
            if len(json.dumps([*output, summary], ensure_ascii=False).encode()) > 10_000:
                break
            output.append(summary)
    stop = args.offset + len(output)
    return {
        "discovery_ref": str(aid),
        "candidates": output,
        "next_offset": stop if stop < len(ids) else None,
        "total_saved": len(ids),
        "source_text_is_untrusted": True,
        "coverage": "searched_query_only",
    }


async def read_media(runtime: Any, args: ReadMediaArgs) -> dict[str, Any]:
    url = args.url
    selected: Candidate | None = None
    if args.candidate_ref:
        async with runtime._conn_factory() as conn:
            candidate_row = await store.get_attempt(runtime, conn, args.candidate_ref)
        if candidate_row["kind"] != "candidate":
            raise store.unavailable("not a candidate reference")
        url = candidate_row["data"]["url"]
        if candidate_row["outcome"] == "ambiguous":
            candidate = Candidate.model_validate(candidate_row["data"])
            if candidate.media_url and candidate.canonical_key:
                selected = candidate
    assert url is not None
    gaps: list[str] = []
    for target in [url, *args.alternate_urls]:
        try:
            async with runtime._conn_factory() as conn:
                if args.refresh_expired:
                    await store.refresh_expired(runtime, conn, target)
                resolved = await store.cached_resolution(runtime, conn, target)
            if resolved is None or args.repair_version:
                resolved = (
                    Resolution("resolved", (selected,))
                    if selected and target == url
                    else await acquisition.resolve_url(runtime, target, args.episode_hint)
                )
            if resolved.state == "ambiguous":
                candidates = []
                async with runtime._conn_factory() as conn:
                    for candidate in resolved.candidates:
                        ref = await store.attempt(
                            runtime,
                            conn,
                            kind="candidate",
                            outcome="ambiguous",
                            purpose=args.purpose,
                            data=candidate.model_dump(mode="json"),
                        )
                        candidates.append(str(ref))
                    discovery_ref = await store.attempt(
                        runtime,
                        conn,
                        kind="discovery",
                        outcome="ambiguous",
                        purpose=args.purpose,
                        data={"candidates": candidates},
                    )
                page = await discover_media(
                    runtime,
                    DiscoverMediaArgs(
                        query="resolved episode candidates",
                        purpose=args.purpose,
                        discovery_ref=discovery_ref,
                    ),
                )
                return {
                    **page,
                    "state": "ambiguous",
                    "gap": "choose_an_exact_episode",
                    "next_action": "Inspect candidate titles, URLs, types and origins. Select a "
                    "relevant candidate_ref or URL and call read_media again with a purpose "
                    "and episode_hint if useful. These candidates have not yet been attempted; "
                    "do not repeat the unchanged landing page or treat ambiguity as failure.",
                }
            if resolved.state != "resolved":
                gaps.extend(resolved.gaps)
                async with runtime._conn_factory() as conn:
                    await store.attempt(
                        runtime,
                        conn,
                        kind="resolution",
                        outcome=resolved.state,
                        purpose=args.purpose,
                        data={"url": target, "gaps": resolved.gaps},
                    )
                continue
            result = await acquisition.acquire(
                runtime, resolved, purpose=args.purpose, repair_version=args.repair_version
            )
            if result.get("version_ref"):
                try:
                    result["index"] = await retrieval.ensure_index(
                        runtime, UUID(result["version_ref"])
                    )
                except Exception as exc:
                    telemetry.record(
                        runtime,
                        "index_unavailable",
                        warning=True,
                        version_ref=result["version_ref"],
                        error_code=type(exc).__name__,
                    )
                    result["index"] = {"state": "unavailable", "gap": type(exc).__name__}
                result["resolution_gaps"] = gaps
                result["next_action"] = (
                    "Use open_transcript with this version_ref to read the transcript; use "
                    "search_transcripts for focused passages. Preserve speakers and source timing. "
                    "Deepgram Speaker numbers are voice clusters, not verified names; do not "
                    "assign the research subject to a cluster from the episode title alone. "
                    "Confidence and timing are machine estimates, not listening verification."
                )
                return result
            gaps.append(result.get("gap", result["state"]))
            if (
                result["state"] in {"unknown", "dispatched", "reserved", "unavailable"}
                and "operation_ref" in result
            ):
                return {
                    **result,
                    "resolution_gaps": gaps,
                    "next_action": "Inspect the saved provider outcome before retrying; "
                    "do not repurchase an uncertain transcription. Preserve the gap.",
                }
        except RefusalError:
            raise
        except (GeminiMediaError, DeepgramMediaError) as exc:
            # Explicit request rejection may fall through to another public source. An
            # uncertain paid outcome never triggers an automatic second acquisition.
            if exc.http_status not in {400, 404, 413, 415, 422}:
                return {"state": "unknown", "gap": "acquisition_outcome_unknown"}
            gaps.append(f"transcription_rejected_http_{exc.http_status}")
        except (ValueError, KeyError) as exc:
            gaps.append(str(exc))
    async with runtime._conn_factory() as conn:
        await store.attempt(
            runtime,
            conn,
            kind="read",
            outcome="unavailable",
            purpose=args.purpose,
            data={"gaps": gaps},
        )
    return {
        "state": "unavailable",
        "gaps": gaps,
        "source_text_is_untrusted": True,
        "next_action": "No transcript obtained through this route. Use the reported gaps to "
        "distinguish recording resolution, retrieval and transcription failures. A publisher "
        "player, feed, indexed transcript or targeted search may offer a useful alternative; "
        "an unrecognized recording link does not prove the recording is unavailable.",
    }


async def search_transcripts(runtime: Any, args: SearchTranscriptsArgs) -> dict[str, Any]:
    return await retrieval.search(
        runtime,
        args.query,
        item_ids=args.item_refs,
        offset=args.offset,
        limit=args.page_size,
        search_ref=args.search_ref,
    )


async def open_transcript(runtime: Any, args: OpenTranscriptArgs) -> dict[str, Any]:
    if args.quote_index is not None:
        if args.version_ref is None:
            raise store.unavailable("quote inspection requires a version_ref")
        async with runtime._conn_factory() as conn:
            saved = await store.load_transcript(runtime, conn, args.version_ref)
        if args.quote_index >= len(saved["quotes"]):
            raise store.unavailable("quote index outside saved metadata")
        quote = saved["quotes"][args.quote_index]
        value = quote["text"]
        stop = min(len(value), args.start + 1000)
        return {
            "version_ref": str(args.version_ref),
            "quote_index": args.quote_index,
            "text": value[args.start : stop],
            "start": args.start,
            "end": stop,
            "next_offset": stop if stop < len(value) else None,
            "verdict": quote.get("verdict"),
            "usable": quote.get("usable", False),
            "time_s": quote.get("ts_s"),
            "timing": "unavailable" if quote.get("ts_s") is None else "model_estimated",
            "attribution": "unverified",
            "why": quote.get("why", "")[:500],
        }
    return await retrieval.open_passage(
        runtime,
        version_id=args.version_ref,
        passage=args.passage_ref,
        start=args.start,
        end=args.end,
        neighbors=args.neighbors,
    )
