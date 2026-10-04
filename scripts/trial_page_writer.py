"""Trial the separate page writer on saved research, without new research spend.

Reads an exported research bundle (dossiers, seller context and documents, committee) and runs the
production page writer on it: the same guides, view, checks, repair and provider call path as a
recipe-25 job (``clue_api.arv2.page_writer``, model calls through the ARV2 provider caller). It
writes the seller brief once, then the account's Overview + Insights and each contact page, and
saves Markdown for reading plus a cost ledger. Nothing is written to a database.

    set -a; source .env; set +a
    uv run python scripts/trial_page_writer.py BUNDLE.json OUT_DIR --account "<name>" --label it1

Paid calls go to OpenRouter with RESEARCH_NARRATIVE_AGENT_MODEL (and _EFFORT). Bundle data is
customer research: keep OUT_DIR outside the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "platform" / "api"))

from clue_api.arv2.calls import CallSpec, ProviderCaller, SpendEstimate  # noqa: E402
from clue_api.arv2.openrouter import (  # noqa: E402
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.page_writer import (  # noqa: E402
    PRIVATE,
    ModelCall,
    PageWriterError,
    seller_brief_request,
    seller_brief_system,
    write_account_pages,
    write_contact_page,
)
from clue_api.arv2.page_writer_runtime import writer_effort, writer_model_id  # noqa: E402
from clue_api.arv2.page_writer_view import Person  # noqa: E402
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink  # noqa: E402
from clue_api.arv2.transport import HttpxTransport  # noqa: E402
from clue_config import GatewayConfig, Secrets, load_settings  # noqa: E402

#: Reading aid only (never a check): sentences that spend words on what is not proven.
CAVEAT = re.compile(
    r"not (?:establish|proof|prove|confirm|a buying signal|a signal|evidence)"
    r"|does not (?:establish|mean|show|name|prove)|is not (?:a |an |evidence|proof)"
    r"|unconfirmed|do not assume|no (?:checked |public )?source (?:states|shows)"
    r"|not established|cannot be|was not found|were not found",
    re.I,
)


def model_call(ledger: list[dict[str, Any]], step: str) -> ModelCall:
    """The production provider path, with the ledger kept in memory instead of the database."""
    settings = load_settings()
    api_key = Secrets().openrouter_api_key
    if api_key is None:
        raise SystemExit("CLUE_OPENROUTER_API_KEY is not set")
    model, effort = writer_model_id(settings), writer_effort()

    async def call(messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        rows = BufferedLedger()
        caller = ProviderCaller(
            transport=HttpxTransport(),
            raw_sink=BufferedRawSink(),
            ledger=rows,
            now=lambda: datetime.now(UTC),
        )
        request = openrouter_chat_request(
            base_url=GatewayConfig().base_url,
            api_key=api_key,
            model=model,
            messages=[dict(m) for m in messages],
            response_format={"type": "json_object"} if json_mode else None,
            reasoning={"effort": effort} if effort else None,
            timeout_s=settings.arv2_page_writer_timeout_s,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=f"page-writer-trial-{step}",
            request=request,
            estimate=SpendEstimate(usd=Decimal("0.20")),
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={"purpose": f"page_writer_trial:{step}"},
        )
        started = time.monotonic()
        result = await asyncio.to_thread(caller.call, spec)
        for row in rows.drain():
            ledger.append(
                {
                    "step": step,
                    "model": model,
                    "seconds": round(time.monotonic() - started, 1),
                    "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                }
            )
        return openrouter_message_text(result.json())

    return call


def sentences(section: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield from section.get("intro") or []
    for item in section.get("items") or []:
        yield from item.get("body") or []
        if item.get("send_line"):
            yield item["send_line"]


def metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    """Reading aids for comparing runs; none of these gate anything."""
    out: dict[str, Any] = {}
    private: list[str] = []
    for page in result.get("pages") or []:
        words = caveats = count = 0
        for section in page.get("sections") or []:
            for item in section.get("items") or []:
                if PRIVATE.search(item.get("h2") or ""):
                    private.append(f"{page['page']}/{section['key']}: {item.get('h2')}")
            for sentence in sentences(section):
                text = sentence.get("text") or ""
                count += 1
                words += len(text.split())
                caveats += bool(CAVEAT.search(text))
                if PRIVATE.search(text):
                    private.append(f"{page['page']}/{section['key']}: {text[:100]}")
        out[page.get("page")] = {"sentences": count, "words": words, "caveat_sentences": caveats}
    out["private_mentions"] = private
    return out


def render(result: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}"]
    for page in result.get("pages") or []:
        lines.append(f"\n## Page: {page['page']}")
        for section in page.get("sections") or []:
            lines.append(f"\n### {section['key']}")
            for s in section.get("intro") or []:
                lines.append(f"{s.get('text')}  `{' '.join(s.get('refs') or [])}`")
            for item in section.get("items") or []:
                lines.append(f"\n**{item.get('h2')}**")
                for s in item.get("body") or []:
                    lines.append(f"{s.get('text')}  `{' '.join(s.get('refs') or [])}`")
                if item.get("send_line"):
                    lines.append(f"> ✉ {item['send_line'].get('text')}")
            for gap in section.get("gaps") or []:
                lines.append(f"- _Gap:_ {gap}")
    return "\n".join(lines) + "\n"


def committee(bundle: Mapping[str, Any], account_job: Mapping[str, Any]) -> list[Person]:
    jobs = {j["subject_id"]: j for j in bundle["jobs"] if j["subject_type"] == "person"}
    titles = {
        sid: next((c["value"] for c in claims if c["field_key"] == "contact.current_title"), None)
        for sid, claims in bundle["claims"].items()
    }
    return [
        Person(
            contact_id=UUID(member["contact_id"]),
            name=(jobs.get(member["contact_id"]) or {}).get("name") or member["contact_id"],
            title=titles.get(member["contact_id"]),
            suggested_role=(member.get("proposed_role") or "").replace("_", " ") or None,
            dossier=(jobs.get(member["contact_id"]) or {}).get("dossier"),
        )
        for member in bundle["committee"][account_job["account_id"]]
    ]


def record(
    ledger: dict[str, Any], run: Path, step: str, slug: str, written: Any, title: str
) -> None:
    steps = [c for c in ledger["calls"] if c["step"] == step]
    ledger[step] = {
        "attempts": written.attempts,
        "metrics": metrics(written.result),
        "seconds": sum(c["seconds"] for c in steps),
        "cost_usd": sum(c.get("cost_usd") or 0 for c in steps),
    }
    (run / f"{slug}.raw.json").write_text(json.dumps(written.result, indent=1))
    (run / f"{slug}.md").write_text(render(written.result, title))
    print(step, written.attempts, "attempt(s)", ledger[step]["metrics"]["private_mentions"])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("out")
    parser.add_argument(
        "--account", required=True, help="account name as it appears in the bundle (a substring)"
    )
    parser.add_argument("--label", required=True)
    parser.add_argument("--only", choices=["brief", "account", "contacts"], default=None)
    parser.add_argument("--contacts", type=int, default=0, help="limit contact pages (0 = all)")
    parser.add_argument("--rebrief", action="store_true")
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle).read_text())
    out = Path(args.out)
    run = out / args.label
    run.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, Any] = {"label": args.label, "calls": []}

    brief_path = out / "seller-brief.md"
    if args.rebrief or not brief_path.exists():
        context = bundle["context"]
        request = seller_brief_request(
            seller_name=context["seller_name"],
            products=context["products"],
            gaps=context.get("gaps") or [],
            documents=[
                (d["pin"]["kind"], d["pin"]["path"], d["body"])
                for d in bundle["documents"].values()
            ],
        )
        brief = await model_call(ledger["calls"], "seller-brief")(
            [
                {"role": "system", "content": seller_brief_system()},
                {"role": "user", "content": request},
            ],
            False,
        )
        brief_path.write_text(brief.strip())
    if args.only == "brief":
        return
    brief = brief_path.read_text()

    account_job = next(
        j
        for j in bundle["jobs"]
        if j["subject_type"] == "account"
        and args.account.lower() in json.dumps(j["dossier"]["document"]).lower()
    )
    people = committee(bundle, account_job)

    story = ""
    story_path = run / "account-story.txt"
    if args.only in (None, "account"):
        try:
            written = await write_account_pages(
                model_call(ledger["calls"], "account"),
                seller_brief=brief,
                account_name=args.account,
                account_dossier=account_job["dossier"],
                people=people,
            )
        except PageWriterError as error:
            ledger["account"] = {"error": str(error)}
            print("account failed:", error)
        else:
            record(ledger, run, "account", "account", written, f"{args.account} — account pages")
            story = written.story
            story_path.write_text(story)
    elif story_path.exists():
        story = story_path.read_text()

    if args.only in (None, "contacts"):
        targets = [p for p in people if p.dossier]
        if args.contacts:
            targets = targets[: args.contacts]

        async def one(person: Person) -> None:
            step = f"contact:{person.name}"
            slug = "contact-" + re.sub(r"[^a-z]+", "-", person.name.lower()).strip("-")
            try:
                written = await write_contact_page(
                    model_call(ledger["calls"], step),
                    seller_brief=brief,
                    account_name=args.account,
                    account_story=story,
                    person=person,
                    account_dossier=account_job["dossier"],
                )
            except PageWriterError as error:
                ledger[step] = {"error": str(error)}
                print(step, "failed:", error)
                return
            record(ledger, run, step, slug, written, f"{person.name} — contact page")

        await asyncio.gather(*(one(p) for p in targets))

    ledger["total_cost_usd"] = round(sum((c.get("cost_usd") or 0) for c in ledger["calls"]), 4)
    (run / "ledger.json").write_text(json.dumps(ledger, indent=1, default=str))
    print("total cost", ledger["total_cost_usd"])


if __name__ == "__main__":
    asyncio.run(main())
