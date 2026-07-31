#!/usr/bin/env python3
"""Thin HTTP-only client for the local Sumble Clue Trial server."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_API = "http://127.0.0.1:8010"


class TrialApiError(RuntimeError):
    def __init__(self, status: int, detail: object) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class TrialApi:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        encoded = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            request_headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            f"{self._base}{path}",
            data=encoded,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw).get("detail")
            except (json.JSONDecodeError, AttributeError):
                detail = raw.decode(errors="replace")
            raise TrialApiError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise TrialApiError(0, f"cannot reach {self._base}: {exc.reason}") from exc
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise TrialApiError(500, "server returned a non-object JSON response")
        return decoded

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            path,
            body,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )


def _ask(label: str, supplied: str | None = None, *, default: str | None = None) -> str:
    if supplied and supplied.strip():
        return supplied.strip()
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    if answer:
        return answer
    if default is not None:
        return default
    raise ValueError(f"{label} is required")


def _confirmed_icp(status: dict[str, Any]) -> tuple[str, int]:
    stage0 = status.get("stage0")
    rows = stage0.get("icps") if isinstance(stage0, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("confirm an ICP before adding an account")
    latest = rows[-1]
    if not isinstance(latest, dict):
        raise ValueError("confirmed ICP payload is malformed")
    key, version = latest.get("icp_key"), latest.get("version")
    if not isinstance(key, str) or not isinstance(version, int):
        raise ValueError("confirmed ICP payload is missing its key/version")
    return key, version


def _account_id(status: dict[str, Any]) -> str:
    manifest = status.get("manifest")
    value = manifest.get("account_entity_id") if isinstance(manifest, dict) else None
    if not isinstance(value, str) or not value:
        raise ValueError("add an account before starting research")
    return value


def _workspace_id(status: dict[str, Any]) -> str:
    session = status.get("session")
    value = session.get("workspace_id") if isinstance(session, dict) else None
    if not isinstance(value, str) or not value:
        raise ValueError("trial response is missing its workspace")
    return value


def _print_status(status: dict[str, Any]) -> None:
    manifest = status.get("manifest", {})
    stage0 = status.get("stage0", {})
    claims = stage0.get("client_knowledge_base", {}).get("claims", {})
    print(f"\nTrial            : {status.get('trial_id')}")
    print(f"Stage-0 claims   : {len(claims) if isinstance(claims, dict) else '?'}")
    print(f"Confirmed ICPs   : {len(stage0.get('icps', []))}")
    print(f"Account          : {manifest.get('account_entity_id') or '(not added)'}")
    print(f"Project phase    : {manifest.get('phase') or '(not started)'}")
    print(f"Run status       : {manifest.get('run_status') or '(not started)'}")
    print(f"C7 view          : {status.get('canonical_research_view_url') or '(not ready)'}")


def _print_preview(preview: dict[str, Any]) -> None:
    print("\nPlanned Sumble acquisition (no request has been sent yet):")
    for call in preview.get("calls", []):
        if not isinstance(call, dict):
            continue
        maximum = call.get("maximum_credits")
        cap = str(maximum) if maximum is not None else "unbounded per returned technology"
        state = "will run" if call.get("will_run", True) else "skipped"
        print(f"  - {call.get('surface')}: {cap} credits ({state})")
    print(f"Hard cap for bounded calls: {preview.get('hard_credit_cap')} credits")


def _print_view(view_response: dict[str, Any]) -> None:
    view = view_response.get("view")
    if not isinstance(view, dict):
        print(json.dumps(view_response, indent=2, ensure_ascii=False))
        return
    summary = view.get("status_summary", {})
    print(
        "\nC7 status: "
        f"{summary.get('available_statement_count', 0)}/"
        f"{summary.get('total_statement_count', 0)} available, "
        f"{summary.get('stale_statement_count', 0)} stale, "
        f"{summary.get('restricted_statement_count', 0)} restricted"
    )
    for section in view.get("sections", []):
        if not isinstance(section, dict):
            continue
        print(f"\n[{section.get('kind')}]")
        items = section.get("items", [])
        if not items:
            print("  (empty — no filler was generated)")
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("item_kind") == "statement":
                state = item.get("state", {})
                print(
                    f"  - {item.get('field_key')}: {item.get('value_json')} "
                    f"[{state.get('availability', 'unknown')}]"
                )
            else:
                print(f"  - reference: {item.get('owner_ref') or item.get('item_id')}")


def _view(api: TrialApi, trial_id: str) -> dict[str, Any]:
    status = api.get(f"/v1/trials/{trial_id}")
    path = status.get("canonical_research_view_url")
    if not isinstance(path, str):
        raise ValueError("the C7 research view is not ready")
    return api.get(
        path,
        headers={"X-Workspace-Id": _workspace_id(status), "X-Actor": "human"},
    )


def _account_add(api: TrialApi, trial_id: str, domain: str) -> None:
    status = api.get(f"/v1/trials/{trial_id}")
    icp_key, icp_version = _confirmed_icp(status)
    name = input("Account name (optional): ").strip() or None
    allow_tech = (
        input("Run confirmed Tech Stack despite unbounded per-result credits? [y/N]: ")
        .strip()
        .lower()
        == "y"
    )
    body: dict[str, Any] = {
        "icp_key": icp_key,
        "icp_version": icp_version,
        "domain": domain,
        "name": name,
        "project_budget_cap_cents": "5000",
        "sumble_credit_cap": 3,
        "allow_unbounded_tech": allow_tech,
    }
    key = str(uuid.uuid4())
    try:
        response = api.post(
            f"/v1/trials/{trial_id}/accounts",
            body,
            idempotency_key=key,
        )
    except TrialApiError as exc:
        detail = exc.detail
        if (
            exc.status == 409
            and isinstance(detail, dict)
            and detail.get("code") == "readiness_override_required"
        ):
            print("\nStage 0 has not cleared the automatic provider-spend gate:")
            for reason in detail.get("reason_codes", []):
                print(f"  - {reason}")
            reason = input(
                "Type a reason to explicitly override for this manual trial, "
                "or leave blank to stop: "
            ).strip()
            if not reason:
                return
            body["readiness_override_reason"] = reason
            response = api.post(
                f"/v1/trials/{trial_id}/accounts",
                body,
                idempotency_key=str(uuid.uuid4()),
            )
        else:
            raise
    print(f"\nAdmitted account: {response.get('account_entity_id')}")
    _print_preview(response.get("research_preview", {}))


def _research(api: TrialApi, trial_id: str, supplied_account: str | None) -> None:
    status = api.get(f"/v1/trials/{trial_id}")
    account = supplied_account or _account_id(status)
    preview = api.post(
        f"/v1/trials/{trial_id}/accounts/{account}:research",
        {"action": "preview"},
    )
    _print_preview(preview)
    if input("\nSpend the bounded Sumble credits shown above? [y/N]: ").strip().lower() != "y":
        print("No Sumble request was sent.")
        return
    acquired = api.post(
        f"/v1/trials/{trial_id}/accounts/{account}:research",
        {"action": "acquire"},
    )
    acquisition = acquired.get("acquisition", {})
    print(
        "\nAcquisition complete. "
        f"Realized credits: {acquisition.get('realized_credits', '?')}; "
        f"phase: {acquired.get('research', {}).get('project_run', {}).get('phase', '?')}"
    )
    if (
        input("Approve this direct account for deep research and verification? [y/N]: ")
        .strip()
        .lower()
        != "y"
    ):
        print("Stopped at the durable tier checkpoint. Resume this trial later.")
        return
    completed = api.post(
        f"/v1/trials/{trial_id}/accounts/{account}:research",
        {"action": "approve_direct_research"},
    )
    research = completed.get("research", {})
    run = research.get("project_run", {})
    print(f"\nResearch ended at {run.get('phase')} ({run.get('status')}).")
    if research.get("research_view_error"):
        print(f"C7 view unavailable: {research['research_view_error']}")
    else:
        _print_view(_view(api, trial_id))


def _interactive(api: TrialApi, trial_id: str) -> None:
    print(f"\nResumable Clue trial: {trial_id}")
    print(
        "Commands: /status /jobs /report /confirm-product /synthesize-icp "
        "/confirm-icp N /account add DOMAIN /research [ACCOUNT] /view [ACCOUNT] "
        "/claims [FIELD] /evidence CLAIM /cost /quit"
    )
    print("Anything else is sent as a Stage-0 message to the Head of ABM agent.")
    while True:
        try:
            message = input("\nYou > ").strip()
        except EOFError:
            message = "/quit"
        if not message:
            continue
        try:
            if message in {"/quit", "/exit"}:
                print(f"Resume later with: uv run python scripts/clue_trial.py resume {trial_id}")
                return
            if message == "/status":
                _print_status(api.get(f"/v1/trials/{trial_id}"))
                continue
            if message == "/jobs":
                payload = api.get(f"/v1/trials/{trial_id}/events")
                for event in payload.get("events", []):
                    print(f"{event.get('at')}  {event.get('kind')}")
                continue
            if message == "/report":
                payload = api.get(f"/v1/trials/{trial_id}/report")
                print(json.dumps(payload.get("quality_limits"), indent=2))
                print("The API also exported trial-report.json under .context/sumble-trials.")
                continue
            if message == "/confirm-product":
                api.post(f"/v1/trials/{trial_id}/product:confirm", {})
                print("Product confirmed by you.")
                continue
            if message == "/synthesize-icp":
                payload = api.post(f"/v1/trials/{trial_id}/icps:synthesize", {})
                if payload.get("status") != "grounded":
                    reasons = ", ".join(payload.get("reason_codes", []))
                    print(f"Not ready: {reasons}")
                    print("Say more about your product and who you target, then try again.")
                    continue
                for index, proposal in enumerate(payload.get("proposals", []), start=1):
                    print(f"{index}. {proposal.get('label') or proposal.get('icp_key')}")
                continue
            if message.startswith("/confirm-icp "):
                proposal = int(message.removeprefix("/confirm-icp ").strip())
                payload = api.post(
                    f"/v1/trials/{trial_id}/icps/{proposal}:confirm",
                    {},
                )
                print(f"Confirmed {payload.get('icp_key')}@{payload.get('icp_version')}.")
                continue
            if message.startswith("/account add "):
                _account_add(api, trial_id, message.removeprefix("/account add ").strip())
                continue
            if message == "/research" or message.startswith("/research "):
                supplied = message.removeprefix("/research").strip() or None
                _research(api, trial_id, supplied)
                continue
            if message == "/view" or message.startswith("/view "):
                _print_view(_view(api, trial_id))
                continue
            if message == "/claims" or message.startswith("/claims "):
                field_filter = message.removeprefix("/claims").strip()
                payload = _view(api, trial_id)
                view = payload.get("view", {})
                for section in view.get("sections", []):
                    for item in section.get("items", []):
                        field = str(item.get("field_key", ""))
                        if not field_filter or field_filter == field:
                            print(json.dumps(item, indent=2, ensure_ascii=False))
                continue
            if message.startswith("/evidence "):
                needle = message.removeprefix("/evidence ").strip()
                payload = _view(api, trial_id)
                matches = []
                for section in payload.get("view", {}).get("sections", []):
                    for item in section.get("items", []):
                        if needle in json.dumps(item, sort_keys=True):
                            matches.append(item)
                print(json.dumps(matches, indent=2, ensure_ascii=False))
                continue
            if message == "/cost":
                print(
                    json.dumps(
                        api.get(f"/v1/trials/{trial_id}/cost"),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                continue
            response = api.post(
                f"/v1/trials/{trial_id}/turns",
                {"message": message},
            )
            print(f"\nHead of ABM [{response.get('status')}] >")
            print(response.get("assistant") or "(No user-facing response was committed.)")
        except (TrialApiError, ValueError) as exc:
            print(f"\nError: {exc}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HTTP-only client for the local Clue Trial.")
    parser.add_argument(
        "--api",
        default=DEFAULT_API,
        help=f"Trial API URL (default {DEFAULT_API}).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    new = commands.add_parser("new")
    new.add_argument("--trial-id")
    new.add_argument("--company-name")
    new.add_argument("--website")
    new.add_argument("--product-name")
    new.add_argument("--project-name")
    resume = commands.add_parser("resume")
    resume.add_argument("trial_id")
    status = commands.add_parser("status")
    status.add_argument("trial_id")
    report = commands.add_parser("report")
    report.add_argument("trial_id")
    report.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    api = TrialApi(args.api)
    try:
        if args.command == "doctor":
            payload = api.get("/v1/trial/doctor")
            print(json.dumps(payload, indent=2))
            raise SystemExit(0 if payload.get("ready") else 1)
        if args.command == "new":
            company = _ask("Company/brand name", args.company_name)
            website = _ask("Company website", args.website)
            product = _ask("Product candidate", args.product_name)
            project = _ask(
                "ABM project name",
                args.project_name,
                default=f"{company} trial",
            )
            payload = api.post(
                "/v1/trials",
                {
                    "trial_id": args.trial_id,
                    "company_name": company,
                    "website": website,
                    "product_name": product,
                    "project_name": project,
                },
            )
            _interactive(api, str(payload["trial_id"]))
            return
        if args.command == "resume":
            api.get(f"/v1/trials/{args.trial_id}")
            _interactive(api, args.trial_id)
            return
        if args.command == "status":
            _print_status(api.get(f"/v1/trials/{args.trial_id}"))
            return
        if args.command == "report":
            payload = api.get(f"/v1/trials/{args.trial_id}/report")
            if args.output is None:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                args.output.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(f"Saved non-authoritative report copy: {args.output}")
    except TrialApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
