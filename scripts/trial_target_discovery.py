"""Isolated target-account discovery trial. No application DB writes, no fleet, no accounts.

Runs the platform's discovery pipeline — Websets long list, then the verifier's website and gate
Answers — against one ICP document, once per *arm*, so arms can be compared on the same ICP:

  A  production exactly: the ICP as stored, ``compile_brief`` unchanged
  B  the ICP's comma-split gates repaired (``repair_front_matter``)
  C  B, with a query that says what the company IS (``company_query`` override)
  D  C, plus one exclusion criterion (``exclusion_criterion`` override)
  E  Exa ``/search`` (category ``company``) on the C query, then the same verifier

The provider-facing pieces are imported from production (``compile_brief``, ``ExaWebsetsClient``,
``ExaClient.answer``, ``gate_question``/``website_question``/``system_prompt``, ``apply_guards``,
``fit_score``, ``disposition``); only the database-bound orchestration of ``discovery_driver`` is
replaced by the plain loop below. Every call's raw body and ledger row lands in the run directory.

    set -a; source .env; set +a
    uv run python scripts/trial_target_discovery.py run --icp PATH --overrides PATH \\
        --arms A B C D E --count 10 --budget-usd 10 \\
        --run-dir .artifacts/target-discovery-trial-20260930/run-01
    uv run python scripts/trial_target_discovery.py report --run-dir …/run-01
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.discovery_brief import DiscoveryBrief, Gate, compile_brief, parse_window_months
from clue_api.arv2.discovery_verifier import (
    OUTPUT_SCHEMA,
    WEBSITE_SCHEMA,
    apply_guards,
    disposition,
    fit_score,
    gate_question,
    system_prompt,
    website_question,
)
from clue_api.arv2.exa_client import ANSWER_ESTIMATE_USD, SEARCH_ESTIMATE_USD, ExaClient
from clue_api.arv2.exa_websets_client import CREDITS_PER_MATCH, ExaWebsetsClient
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_research.identity.normalize import registrable_domain
from clue_spend.errors import ProviderTransportError
from clue_spend.ledger import BufferedLedger, BufferedRawSink
from clue_spend.transport import HttpxTransport

ARMS = ("A", "B", "C", "D", "E", "G")
WEBSETS_ARMS = ("A", "B", "C", "D", "G")
AGENT_PROMPT = (
    Path(__file__).resolve().parents[1]
    / "docs/superpowers/drafts/2026-09-30-target-discovery-trial/agent-brief-prompt.md"
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AGENT_ESTIMATE_USD = Decimal("0.25")
#: Fields a gate or qualifier row legitimately carries. Any other key whose value is ``null`` is a
#: fragment of the value before it, split off at a comma by inline YAML.
KNOWN_FIELDS = frozenset(
    {"key", "rule", "test", "criterion", "field_key", "description", "display", "titles"}
)
#: Websets accepted five criteria in the 2026-09-10 experiment (arm W5); production caps at three.
MAX_TRIAL_CRITERIA = 5
POLL_INTERVAL_S = 15.0
WEBSET_WALL_S = 1200.0
VERIFY_CONCURRENCY = 4


class TrialError(RuntimeError):
    """The trial refuses — a missing override, a spent budget — rather than guessing."""


# -- the ICP -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Icp:
    text: str
    front: dict[str, Any]
    repaired: dict[str, Any]
    body: str


def _repair_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Rejoin ``row``'s comma fragments onto the text field they were split from, in order."""
    out: dict[str, Any] = {}
    last: str | None = None
    for key, value in row.items():
        if value is None and key not in KNOWN_FIELDS and last is not None:
            out[last] = f"{out[last]}, {key}"
            continue
        out[key] = value
        if isinstance(value, str):
            last = key
    return out


def repair_front_matter(front: Mapping[str, Any]) -> dict[str, Any]:
    """The front matter with every comma-split gate/qualifier value rejoined."""
    repaired = dict(front)
    for section in ("hard_gates", "qualifier_fields"):
        rows = front.get(section)
        if isinstance(rows, list):
            repaired[section] = [
                _repair_row(row) if isinstance(row, Mapping) else row for row in rows
            ]
    return repaired


def fragment_count(front: Mapping[str, Any]) -> int:
    """How many comma fragments the front matter carries (0 for an intact document)."""
    count = 0
    for section in ("hard_gates", "qualifier_fields"):
        for row in front.get(section) or ():
            if isinstance(row, Mapping):
                count += sum(
                    1 for key, value in row.items() if value is None and key not in KNOWN_FIELDS
                )
    return count


def load_icp_text(text: str) -> Icp:
    front, body = parse_front_matter(text)
    return Icp(text=text, front=front, repaired=repair_front_matter(front), body=body)


def build_brief(arm: str, icp: Icp, *, overrides: Mapping[str, str]) -> DiscoveryBrief:
    """What arm ``arm`` asks: A is production's brief byte for byte; the rest change one thing."""
    if arm == "A":
        return compile_brief(icp.front, icp.body)
    brief = compile_brief(icp.repaired, icp.body)
    if arm == "B":
        return brief
    query = overrides.get("company_query")
    if not query:
        raise TrialError(f"arm {arm} needs a company_query override")
    # compile_brief spends a spare criteria slot on the buyer sentence; that slot follows the query.
    criteria = tuple(query if c == brief.query else c for c in brief.criteria)
    brief = replace(brief, query=query, criteria=criteria)
    if arm in ("C", "E"):
        return brief
    exclusion = overrides.get("exclusion_criterion")
    if not exclusion:
        raise TrialError(f"arm {arm} needs an exclusion_criterion override")
    criteria = (*brief.criteria, exclusion)
    if len(criteria) > MAX_TRIAL_CRITERIA:
        raise TrialError(f"arm {arm} would send {len(criteria)} criteria")
    return replace(brief, criteria=criteria)


# -- money -------------------------------------------------------------------------------------


@dataclass
class Budget:
    cap_usd: Decimal
    spent_usd: Decimal = Decimal(0)

    def check(self, estimate: Decimal) -> None:
        if self.spent_usd + estimate > self.cap_usd:
            raise TrialError(
                f"budget: {self.spent_usd} spent + {estimate} estimated > cap {self.cap_usd}"
            )

    def spend(self, amount: Decimal) -> None:
        self.spent_usd += amount


# -- candidates --------------------------------------------------------------------------------


@dataclass
class Candidate:
    name: str
    url: str
    source: str
    description: str | None = None
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    verified_domain: str | None = None
    fit: float | None = None
    disposition: str | None = None
    #: Arm G: the agent's disqualifying gates this company failed (empty = not excluded).
    excluded_by: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return registrable_domain(self.url) or self.url.strip().lower()


def dedupe(rows: Iterable[Candidate], *, count: int) -> list[Candidate]:
    kept: list[Candidate] = []
    seen: set[str] = set()
    for row in rows:
        if row.domain in seen:
            continue
        seen.add(row.domain)
        kept.append(row)
        if len(kept) >= count:
            break
    return kept


def precision_table(grades: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, Any]]:
    """Per arm: how many graded, how many real targets, and precision = targets / graded."""
    table: dict[str, dict[str, Any]] = {}
    for arm, by_domain in grades.items():
        labels = list(by_domain.values())
        target = labels.count("target")
        table[arm] = {
            "graded": len(labels),
            "target": target,
            "not_target": labels.count("not_target"),
            "unclear": labels.count("unclear"),
            "precision": (target / len(labels)) if labels else None,
        }
    return table


# -- arm G: the brief written by an agent -------------------------------------------------------


def brief_from_agent(answer: Mapping[str, Any]) -> tuple[DiscoveryBrief, frozenset[str]]:
    """The agent's JSON answer as the brief the search sends, plus its disqualifying gate keys."""
    query = str(answer.get("query") or "").strip()
    if not query:
        raise TrialError("agent brief has no query")
    criteria = tuple(str(c).strip() for c in answer.get("criteria") or () if str(c).strip())
    if not 1 <= len(criteria) <= MAX_TRIAL_CRITERIA:
        raise TrialError(f"agent brief has {len(criteria)} criteria (1-{MAX_TRIAL_CRITERIA})")
    gates: list[Gate] = []
    disqualifying: set[str] = set()
    for raw in answer.get("gates") or ():
        key, rule = str(raw.get("key") or "").strip(), str(raw.get("rule") or "").strip()
        test = str(raw.get("test") or "").strip()
        if not key or not rule:
            raise TrialError(f"agent gate without key or rule: {raw!r}")
        gates.append(
            Gate(key=key, rule=rule, test=test, window_months=parse_window_months(rule, test))
        )
        if raw.get("disqualifying") is True:
            disqualifying.add(key)
    if not gates:
        raise TrialError("agent brief has no gates")
    brief = DiscoveryBrief(
        query=query, criteria=criteria, criteria_gate_keys=(), gates=tuple(gates), exclusions=()
    )
    return brief, frozenset(disqualifying)


def excluded_by(verdicts: Sequence[Mapping[str, Any]], disqualifying: frozenset[str]) -> list[str]:
    """The disqualifying gates this company FAILED. An unclear gate never excludes."""
    return [
        v["gate_key"] for v in verdicts if v["verdict"] == "fail" and v["gate_key"] in disqualifying
    ]


def write_agent_brief(
    *,
    documents: Sequence[Path],
    conversation: str,
    api_key: SecretStr,
    model: str,
    run_dir: RunDir,
    budget: Budget,
) -> dict[str, Any]:
    """One model call playing the Head of ABM: read the documents and chat, answer the brief."""
    import httpx

    budget.check(AGENT_ESTIMATE_USD)
    parts = [f"## Document: {path.name}\n\n{path.read_text()}" for path in documents]
    parts.append(f"## What the user said in this project's chat\n\n{conversation.strip()}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": AGENT_PROMPT.read_text()},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
    }
    response = httpx.post(
        OPENROUTER_URL,
        json=body,
        timeout=300.0,
        headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
    )
    payload = response.json()
    run_dir.write_json(
        "arm-G-agent-call.json",
        {"request_model": model, "status": response.status_code, "response": payload},
    )
    cost = Decimal(str((payload.get("usage") or {}).get("cost") or "0"))
    budget.spend(cost)
    if response.status_code != 200:
        raise TrialError(f"agent brief call failed: http {response.status_code}")
    text = payload["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


# -- the run -----------------------------------------------------------------------------------


class RunDir:
    """Where one trial run keeps its inputs, raw bodies, ledger rows and candidates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        (path / "raw").mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: object) -> None:
        (self.path / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")

    def flush(self, raw: BufferedRawSink, ledger: BufferedLedger, budget: Budget) -> None:
        for ref, record, body in raw.drain():
            name = ref.replace(":", "_")
            (self.path / "raw" / f"{name}.json").write_bytes(body)
            meta = {
                "ref": ref,
                "record": asdict(record)
                if hasattr(record, "__dataclass_fields__")
                else str(record),
            }
            (self.path / "raw" / f"{name}.meta.json").write_text(json.dumps(meta, default=str))
        with (self.path / "ledger.jsonl").open("a") as handle:
            for row in ledger.drain():
                handle.write(json.dumps(asdict(row), default=str) + "\n")
                if row.phase == "result" and row.cost_usd:
                    budget.spend(row.cost_usd)


class Providers:
    """One ProviderCaller per call over shared buffers; the buffers are flushed to the run dir."""

    def __init__(
        self,
        *,
        exa_key: SecretStr,
        usd_per_credit: Decimal,
        answer_model: str,
        run_dir: RunDir,
        budget: Budget,
    ) -> None:
        self.exa_key = exa_key
        self.usd_per_credit = usd_per_credit
        self.answer_model = answer_model
        self.run_dir = run_dir
        self.budget = budget
        self.raw = BufferedRawSink()
        self.ledger = BufferedLedger()
        self.transport = HttpxTransport()

    def _caller(self) -> ProviderCaller:
        return ProviderCaller(
            transport=self.transport,
            raw_sink=self.raw,
            ledger=self.ledger,
            now=lambda: datetime.now(UTC),
        )

    def flush(self) -> None:
        self.run_dir.flush(self.raw, self.ledger, self.budget)

    def websets(self) -> ExaWebsetsClient:
        return ExaWebsetsClient(self._caller(), self.exa_key, usd_per_credit=self.usd_per_credit)

    def exa(self) -> ExaClient:
        return ExaClient(self._caller(), api_key=self.exa_key)


def _retrying[T](providers: Providers, call: Callable[[], T], attempts: int = 8) -> T:
    """A free read retried across a network drop (the 2026-09-30 run lost DNS mid-poll)."""
    for attempt in range(attempts):
        try:
            result = call()
            providers.flush()
            return result
        except ProviderTransportError:
            providers.flush()
            if attempt == attempts - 1:
                raise
            time.sleep(POLL_INTERVAL_S)
    raise AssertionError("unreachable")


def _long_list_websets(
    providers: Providers, arm: str, brief: DiscoveryBrief, count: int, run_name: str
) -> list[Candidate]:
    external_id = f"trial-target-discovery:{run_name}:{arm}"
    # A resumed run reads the webset it already bought (Exa keys it by externalId) rather than
    # buying a second one — a webset keeps finding, and billing, whether or not anyone reads it.
    view = _retrying(providers, lambda: providers.websets().find(external_id))
    if view is None:
        worst = Decimal(count * CREDITS_PER_MATCH) * providers.usd_per_credit
        providers.budget.check(worst)
        view = providers.websets().create(
            query=brief.query,
            count=count,
            criteria=brief.criteria,
            external_id=external_id,
            title=f"trial target discovery {run_name} arm {arm}",
            recall=False,
        )
        providers.flush()
    if view.error:
        raise TrialError(f"arm {arm}: websets refused the create: {view.error}")
    started = time.monotonic()
    while True:
        webset_id = view.webset_id
        view = _retrying(providers, lambda wid=webset_id: providers.websets().get(wid))
        if view.status == "idle":
            break
        if time.monotonic() - started > WEBSET_WALL_S:
            providers.websets().cancel(view.webset_id)
            providers.flush()
            break
        time.sleep(POLL_INTERVAL_S)
    final_id = view.webset_id
    items = _retrying(providers, lambda: providers.websets().items(final_id))
    providers.flush()
    searches = [asdict(s) for s in view.searches]
    providers.run_dir.write_json(
        f"arm-{arm}-webset.json",
        {
            "webset_id": view.webset_id,
            "status": view.status,
            "searches": searches,
            "wall_s": round(time.monotonic() - started),
            "items": len(items.items),
        },
    )
    return [
        Candidate(
            name=item.name,
            url=item.url,
            source="websets",
            description=item.description,
            evaluations=[dict(e) for e in item.evaluations],
        )
        for item in items.items
    ]


def _long_list_search(providers: Providers, brief: DiscoveryBrief, count: int) -> list[Candidate]:
    providers.budget.check(SEARCH_ESTIMATE_USD)
    result = providers.exa().search(
        brief.query,
        category="company",
        num_results=count * 2,
        label="trial-company-search",
        text_max_chars=600,
    )
    providers.flush()
    return [
        Candidate(
            name=hit.title or hit.url or "",
            url=hit.url or "",
            source="search",
            description=(hit.text or "")[:400],
        )
        for hit in result.results
        if hit.url
    ]


def _verify(
    providers: Providers, brief: DiscoveryBrief, candidate: Candidate, today: date
) -> Candidate:
    prompt = system_prompt(today)
    asks = 1 + len(brief.gates)
    providers.budget.check(ANSWER_ESTIMATE_USD * asks)
    site = providers.exa().answer(
        website_question(candidate.name, candidate.url),
        system_prompt=prompt,
        output_schema=WEBSITE_SCHEMA,
        model=providers.answer_model,
        label=f"trial-website-{candidate.domain}",
    )
    verified = None
    if isinstance(site.answer, Mapping):
        verified = registrable_domain(str(site.answer.get("website_domain") or ""))
    verified = verified or candidate.domain
    verdicts = []
    for gate in brief.gates:
        result = providers.exa().answer(
            gate_question(candidate.name, f"https://{verified}", gate),
            system_prompt=prompt,
            output_schema=OUTPUT_SCHEMA,
            model=providers.answer_model,
            label=f"trial-{gate.key}-{verified}",
        )
        verdicts.append(
            apply_guards(
                gate=gate,
                answer=result.answer,
                today=today,
            )
        )
    candidate.verified_domain = verified
    candidate.verdicts = [v.as_json() for v in verdicts]
    candidate.fit = fit_score(verdicts)
    candidate.disposition = disposition(verdicts)
    return candidate


def run_arm(
    providers: Providers,
    arm: str,
    icp: Icp,
    overrides: Mapping[str, str],
    *,
    count: int,
    verify: bool,
    run_name: str,
    agent: Callable[[], dict[str, Any]] | None = None,
) -> list[Candidate]:
    disqualifying: frozenset[str] = frozenset()
    if arm == "G":
        if agent is None:
            raise TrialError("arm G needs the agent inputs (--agent-docs, --conversation)")
        answer = agent()
        providers.run_dir.write_json("arm-G-agent-answer.json", answer)
        brief, disqualifying = brief_from_agent(answer)
    else:
        brief = build_brief(arm, icp, overrides=overrides)
    providers.run_dir.write_json(
        f"arm-{arm}-brief.json",
        {
            "query": brief.query,
            "criteria": list(brief.criteria),
            "gates": [asdict(g) for g in brief.gates],
            "disqualifying": sorted(disqualifying),
        },
    )
    started = time.monotonic()
    if arm in WEBSETS_ARMS:
        rows = _long_list_websets(providers, arm, brief, count, run_name)
    else:
        rows = _long_list_search(providers, brief, count)
    candidates = dedupe(rows, count=count)
    if verify:
        today = datetime.now(UTC).date()
        with ThreadPoolExecutor(VERIFY_CONCURRENCY) as pool:
            candidates = list(pool.map(lambda c: _verify(providers, brief, c, today), candidates))
        providers.flush()
        for candidate in candidates:
            candidate.excluded_by = excluded_by(candidate.verdicts, disqualifying)
    providers.run_dir.write_json(
        f"arm-{arm}-candidates.json",
        {
            "arm": arm,
            "wall_s": round(time.monotonic() - started),
            "candidates": [asdict(c) | {"domain": c.domain} for c in candidates],
        },
    )
    return candidates


# -- CLI ---------------------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> None:
    from clue_config import Secrets, Settings

    icp_text = Path(args.icp).read_text()
    icp = load_icp_text(icp_text)
    overrides = yaml.safe_load(Path(args.overrides).read_text()) if args.overrides else {}
    run_dir = RunDir(Path(args.run_dir))
    (run_dir.path / "icp.md").write_text(icp_text)
    run_dir.write_json("overrides.json", overrides)
    run_dir.write_json(
        "icp-repair.json",
        {
            "fragments": fragment_count(icp.front),
            "hard_gates_as_stored": icp.front.get("hard_gates"),
            "hard_gates_repaired": icp.repaired.get("hard_gates"),
        },
    )
    brief_arms = [arm for arm in args.arms if arm != "G"]
    for arm in brief_arms:  # refuse a missing override before anything is bought
        build_brief(arm, icp, overrides=overrides)
    if "G" in args.arms and not (args.agent_docs and args.conversation):
        raise TrialError("arm G needs --agent-docs and --conversation")
    if args.dry_run:
        for arm in brief_arms:
            brief = build_brief(arm, icp, overrides=overrides)
            print(
                json.dumps({"arm": arm, "query": brief.query, "criteria": brief.criteria}, indent=2)
            )
        return
    settings, secrets = Settings(), Secrets()
    if secrets.exa_api_key is None:
        raise TrialError("CLUE_EXA_API_KEY is not set")
    budget = Budget(cap_usd=Decimal(str(args.budget_usd)))
    providers = Providers(
        exa_key=SecretStr(secrets.exa_api_key.get_secret_value()),
        usd_per_credit=settings.arv2_discovery_websets_usd_per_credit,
        answer_model=settings.arv2_discovery_answer_model,
        run_dir=run_dir,
        budget=budget,
    )
    run_name = run_dir.path.name
    agent = None
    if "G" in args.arms:
        if secrets.openrouter_api_key is None:
            raise TrialError("CLUE_OPENROUTER_API_KEY is not set")
        import os

        docs = [Path(p) for p in args.agent_docs]
        conversation = Path(args.conversation).read_text()
        key = SecretStr(secrets.openrouter_api_key.get_secret_value())
        model = os.environ.get("HEAD_OF_ABM_AGENT_MODEL") or "x-ai/grok-4.6"

        def agent() -> dict[str, Any]:
            return write_agent_brief(
                documents=docs,
                conversation=conversation,
                api_key=key,
                model=model,
                run_dir=run_dir,
                budget=budget,
            )

    for arm in args.arms:
        print(f"arm {arm}: running (spent so far ${budget.spent_usd})", flush=True)
        try:
            found = run_arm(
                providers,
                arm,
                icp,
                overrides,
                count=args.count,
                verify=not args.no_verify,
                run_name=run_name,
                agent=agent,
            )
            print(f"arm {arm}: {len(found)} candidates, spent ${budget.spent_usd}", flush=True)
        except TrialError as error:
            providers.flush()
            print(f"arm {arm}: stopped — {error}", flush=True)
            if "budget" in str(error):
                break
    run_dir.write_json(
        "spend.json", {"spent_usd": str(budget.spent_usd), "cap_usd": str(budget.cap_usd)}
    )


def _report(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    grades_path = run_dir / "grades.json"
    grades = json.loads(grades_path.read_text()) if grades_path.exists() else {}
    print(json.dumps(precision_table(grades), indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--icp", required=True)
    run.add_argument("--overrides")
    run.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    run.add_argument("--count", type=int, default=10)
    run.add_argument("--budget-usd", type=float, default=10.0)
    run.add_argument("--run-dir", required=True)
    run.add_argument("--no-verify", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--agent-docs", nargs="*", help="arm G: the documents the agent reads")
    run.add_argument("--conversation", help="arm G: a text file of what the user said")
    run.set_defaults(handler=_run)
    report = sub.add_parser("report")
    report.add_argument("--run-dir", required=True)
    report.set_defaults(handler=_report)
    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
