"""Interactive, no-frontend Stage-0 quality trial.

Run from the repository root:

    uv run python scripts/00_stage0_trial.py

The CLI creates or resumes an isolated trial workspace, then sends each message through the
production Head-of-ABM deepagent runtime. It intentionally does not bind Exa, website scraping, or
campaign files. Durable truth lives in Postgres/artifact storage; an inspectable report is written
under ``.context/stage0-trials/<session>/`` after every turn.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from cli_multiline import (
    HELP_LINE,
    PASTE_TERMINATOR,
    read_file_message,
    read_pasted_message,
)

import clue_obs
from clue_api.stage0_trial import (
    Stage0Trial,
    Stage0TrialPaths,
    create_stage0_trial_session,
)
from clue_api.trial.stage0_runtime import (
    memory_assembly_factory,
    memory_write_factory_builder,
)
from clue_db import db_lifespan
from clue_research.stage0 import ICPSynthesisStatus

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_TRIAL_ROOT = _REPOSITORY_ROOT / ".context" / "stage0-trials"


def _ask(label: str, supplied: str | None, *, default: str | None = None) -> str:
    if supplied is not None and supplied.strip():
        return supplied.strip()
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(f"{label} is required")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an inspectable manual-conversation-only Stage-0 deepagent trial."
    )
    parser.add_argument("--session", help="Session slug to create or resume.")
    parser.add_argument(
        "--new",
        action="store_true",
        help="Require creation of a new session instead of resuming an existing one.",
    )
    parser.add_argument("--company-name", help="Client/company identity seed for a new session.")
    parser.add_argument("--website", help="Identity seed only; this CLI will not fetch it.")
    parser.add_argument("--product-name", help="Unconfirmed product candidate for Stage 0.")
    parser.add_argument("--project-name", help="End-to-end ABM project name.")
    return parser


async def _show_status(trial: Stage0Trial) -> None:
    snapshot = await trial.snapshot()
    client_kb = snapshot["client_knowledge_base"]
    print("\nCurrent durable Stage-0 state")
    print(f"  workspace      : {snapshot['workspace_id']}")
    print(f"  project        : {trial.state.project_id}")
    print(f"  product        : {trial.state.product_name} (candidate)")
    print(f"  client entity  : {trial.state.client_entity_id}")
    print(f"  KB version     : {trial.state.client_kb_version}")
    print(f"  claims         : {len(client_kb['claims'])}")  # type: ignore[index]
    print(f"  memories       : {len(snapshot['memories'])}")  # type: ignore[arg-type]
    print(f"  ICP versions   : {len(snapshot['icps'])}")  # type: ignore[arg-type]
    if snapshot["icp_proposals_stale"]:
        # Without this the operator sees no proposals and no reason, then /confirm-icp refuses.
        print(f"  ICP proposals  : superseded — {snapshot['icp_proposals_stale_reason']}")
    print(f"  report         : {trial.paths.report_markdown}")


async def _interactive(trial: Stage0Trial) -> None:
    print("\nStage 0 conversation is ready.")
    print(
        "This run uses only what you say here. It does not read campaign files, fetch the website,"
    )
    print("call Exa, or scrape the web.")
    print(
        "\nCommands: /status  /report  /confirm-product  /synthesize-icp  "
        "/confirm-icp NUMBER  /paste  /file PATH  /quit"
    )
    print(HELP_LINE)
    print(
        "\nStart naturally. For example: “Let me explain our company, product, customers, and what "
        "we are trying to achieve.”"
    )
    while True:
        try:
            message = (await asyncio.to_thread(input, "\nYou > ")).strip()
        except EOFError:
            message = "/quit"
        if not message:
            continue
        if message in {"/quit", "/exit"}:
            await trial.export_report()
            print(f"\nSaved: {trial.paths.report_markdown}")
            return
        try:
            await _dispatch(trial, message)
        except (ValueError, RuntimeError) as exc:
            # A refused human gate (unconfirmed product, no grounded proposal) is a normal answer
            # to a normal command, and a refused *integrity* check (a statement that no longer
            # hashes to its captured evidence) is a loud but recoverable one. Neither should end
            # the session: durable state is untouched, so print and hand the prompt back.
            print(f"\nError: {type(exc).__name__}: {exc}")


async def _dispatch(trial: Stage0Trial, message: str) -> None:
    """Run one command (or one conversation turn) against the live trial."""
    if message == "/paste":
        print(f"Paste your text, then a line containing only '{PASTE_TERMINATOR}':")
        # Always a conversation turn: a pasted line that happens to start with "/" is content,
        # not a command.
        await _turn(trial, await asyncio.to_thread(read_pasted_message, input))
        return
    if message == "/file" or message.startswith("/file "):
        body = await asyncio.to_thread(read_file_message, message.removeprefix("/file"))
        await _turn(trial, body)
        return
    if message == "/status":
        await _show_status(trial)
        return
    if message == "/report":
        await trial.export_report()
        print(f"\nReport refreshed: {trial.paths.report_markdown}")
        return
    if message == "/confirm-product":
        await trial.confirm_product()
        print(f"\nConfirmed product: {trial.state.product_name}")
        return
    if message == "/synthesize-icp":
        outcome = await trial.synthesize_icp_proposals()
        if outcome.excluded_statement_ids:
            print(
                f"\nExcluded {len(outcome.excluded_statement_ids)} statement(s) whose evidence "
                "artifact is no longer available (erased):"
            )
            for statement_id in outcome.excluded_statement_ids:
                print(f"  - {statement_id}")
        if outcome.status is not ICPSynthesisStatus.GROUNDED:
            print(f"\nNot ready: {', '.join(outcome.reason_codes)}")
            print(
                "Nothing durable grounds an ICP yet. Tell the agent who you want to target "
                "and what you sell, then try again."
            )
            return
        print(f"\nGenerated {len(outcome.proposals)} ICP proposal(s):")
        for number, proposal in enumerate(outcome.proposals, start=1):
            print(f"  {number}. {proposal.label or proposal.icp_key} [{proposal.icp_key}]")
        print(f"Inspect: {trial.paths.icp_proposals}")
        print("Continue the conversation so the agent can critique them before you confirm.")
        return
    if message.startswith("/confirm-icp "):
        raw_number = message.removeprefix("/confirm-icp ").strip()
        try:
            number = int(raw_number)
        except ValueError as exc:
            raise ValueError("/confirm-icp requires a proposal number") from exc
        confirmation = await trial.confirm_icp_proposal(number)
        print(f"\nConfirmed ICP: {confirmation.ref.icp_key}@{confirmation.ref.icp_version}")
        return
    await _turn(trial, message)


async def _turn(trial: Stage0Trial, message: str) -> None:
    """Send one Stage-0 conversation turn and print the agent's reply."""
    outcome, assistant = await trial.run_turn(message)
    print(f"\nHead of ABM [{outcome.status.value}] >")
    print(assistant or "(No user-facing message was committed; inspect the report.)")


async def _main(args: argparse.Namespace) -> None:
    default_session = "trial-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    session = (args.session or default_session).strip().lower()
    paths = Stage0TrialPaths.for_session(_TRIAL_ROOT, session)
    async with db_lifespan():
        if paths.state.exists():
            if args.new:
                raise FileExistsError(f"session {session!r} already exists")
            state = paths.load_state()
            print(f"Resuming Stage-0 trial {session!r}.")
        else:
            company_name = _ask("Company/brand name", args.company_name)
            website = _ask("Company website", args.website)
            product_name = _ask("Product candidate", args.product_name)
            project_name = _ask(
                "Project name",
                args.project_name,
                default=f"{company_name} Stage 0 trial",
            )
            paths, state = await create_stage0_trial_session(
                paths_root=_TRIAL_ROOT,
                session_name=session,
                company_name=company_name,
                website=website,
                product_name=product_name,
                project_name=project_name,
            )
            print(f"Created isolated Stage-0 trial {state.session_slug!r}.")
        trial = await Stage0Trial.build(
            state=state,
            paths=paths,
            memory_assembly_factory=memory_assembly_factory,
            memory_write_factory_builder=memory_write_factory_builder,
        )
        try:
            await trial.export_report()
            await _interactive(trial)
        finally:
            await trial.close()


if __name__ == "__main__":
    clue_obs.setup()
    asyncio.run(_main(_parser().parse_args()))
