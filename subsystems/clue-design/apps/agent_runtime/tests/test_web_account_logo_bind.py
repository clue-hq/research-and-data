"""`bind_account_logo` — the G1+G2 bridge, agent side (clone-fidelity F4.3, ruling R25-1).

`fetch_logo` puts a target account's REAL published mark into the working document. Until this
task nothing carried it any further: the ladder wrote no `design_asset` row (G1) and stamped no
`design_account.logo_asset_id` (G2), so the F1.4 account derive — which reads exactly that one
column — personalized every batch page with an empty logo slot no matter how many logos the
agent had fetched.

`bind_account_logo(account_id, asset_id)` is that carry, and it is deliberately a SECOND,
NAMED act rather than a side effect of fetching:

* **Nothing auto-binds** (ruling R25-2). There is no code path from a ladder outcome to an
  account row that does not pass through this call with an account id and an asset id somebody
  named. A `needs_review` fetch registers nothing, so there is no id to pass — and passing one
  anyway is refused, never improvised.
* **Only a ladder-fetched mark** may reach an account row through this tool. A generated image
  is not a company's logo; a placeholder is not a company's logo. The never-synthesize register
  is structural here, not advisory.
* **An empty account logo is CORRECT.** Every refusal below says so in the words the agent
  reads, and none of them suggests drawing one.

The binder is a capability the API injects (the `cloned_section_registry` precedent), so this
file fakes it and pins what the TOOL does with each answer. The durable half — the real registry
write, the account stamp, workspace scoping — is `apps/api/tests/test_abm_batch_publish.py`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]

LADDER_ASSET_ID = "asset_ing_0123456789abcdef"
DIGEST = "c" * 64


def _ladder_record(asset_id: str = LADDER_ASSET_ID) -> dict:
    """What `fetch_logo`'s ingest leaves in `web_doc["assets"]`."""
    return {
        "id": asset_id,
        "label": "Goodman Campbell logo (light)",
        "kind": "vector",
        "status": "ready",
        "source": {"kind": "website", "url": "https://goodmancampbell.com/brand/logo.svg"},
        "media": {
            "mime_type": "image/svg+xml",
            "digest": {"algorithm": "sha256", "value": DIGEST},
            "location": {
                "provider": "local-store",
                "opaque_ref": f"sha256/{DIGEST[:2]}/{DIGEST}",
                "url": None,
            },
        },
        "provenance": {"created_by": "logo_ladder", "source_label": "website"},
        "tags": ["target-account", "logo-ladder"],
    }


def _generated_record(asset_id: str = "asset_gen_1") -> dict:
    record = _ladder_record(asset_id)
    record["source"] = {"kind": "generated", "request_id": asset_id, "model": "stub"}
    record["provenance"] = {"created_by": "openai:image", "source_label": "generated"}
    record["tags"] = ["generated"]
    return record


class FakeBinder:
    """Answers what `DurableAgentAccountLogoBinder` answers, and records every bind."""

    def __init__(self, *, accounts=("acc_goodman",), refuse=None) -> None:
        self.workspace_id = "ws_test"
        self.accounts = {
            account_id: {"account_id": account_id, "name": "Goodman Campbell", "logo_asset_id": None}
            for account_id in accounts
        }
        self.refuse = refuse
        self.binds: list = []

    def bind(self, *, account_id, record):
        from lumen_api.agent_account_logos import AccountLogoRefused

        if self.refuse is not None:
            raise AccountLogoRefused(*self.refuse)
        if account_id not in self.accounts:
            raise AccountLogoRefused(
                "account_logo.unknown_account",
                f"no account {account_id!r} in this workspace",
            )
        previous = self.accounts[account_id]["logo_asset_id"]
        self.accounts[account_id]["logo_asset_id"] = record["id"]
        self.binds.append({"account_id": account_id, "asset_id": record["id"]})
        return {
            "account_id": account_id,
            "account_name": self.accounts[account_id]["name"],
            "asset_id": record["id"],
            "digest": (record.get("media") or {}).get("digest", {}).get("value"),
            "previous_asset_id": previous,
            "changed": previous != record["id"],
        }


def _tools(tmp_path: Path, *, binder=None, assets=None) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
    )
    if binder is not None:
        config = replace(config, account_logo_binder=binder)
    seed = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_abm", "ABM page", None)["web_doc"]
    tools = LumenWebTools(config, "Build an ABM page", initial_web_doc=seed)
    tools.web_doc = {**tools.web_doc, "assets": dict(assets or {})}
    return tools


# --------------------------------------------------------------------------- #
# the happy path
# --------------------------------------------------------------------------- #


def test_binding_a_fetched_logo_stamps_the_account_and_says_what_it_means(tmp_path: Path) -> None:
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={LADDER_ASSET_ID: _ladder_record()})

    payload = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))

    assert payload["status"] == "ok"
    assert payload["account_id"] == "acc_goodman"
    assert payload["asset_id"] == LADDER_ASSET_ID
    assert binder.binds == [{"account_id": "acc_goodman", "asset_id": LADDER_ASSET_ID}]
    assert binder.accounts["acc_goodman"]["logo_asset_id"] == LADDER_ASSET_ID
    # It tells the author what the bind BUYS — the derive, not this page.
    assert "{{account.logo}}" in payload["note"]


def test_an_alternative_binds_like_a_cell(tmp_path: Path) -> None:
    """`fetch_logo` registers its alternatives with the same provenance as its cells, so
    one the agent judged the better fit for this account is bindable too."""
    from lumen_api.agent_account_logos import is_fetched_logo

    alternative = _ladder_record("asset_ing_a17e12a71fe00000")
    alternative["label"] = "Goodman Campbell logo (alternative: icon)"
    alternative["provenance"] = {"created_by": "brandfetch", "source_label": "brandfetch"}
    assert is_fetched_logo(alternative)

    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={alternative["id"]: alternative})

    payload = json.loads(tools.bind_account_logo("acc_goodman", alternative["id"]))

    assert payload["status"] == "ok"
    assert binder.accounts["acc_goodman"]["logo_asset_id"] == alternative["id"]


def test_re_binding_the_same_logo_converges(tmp_path: Path) -> None:
    """Red case 8's second half: the same bind twice is the same account row, said honestly."""
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={LADDER_ASSET_ID: _ladder_record()})

    first = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))
    second = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))

    assert first["status"] == second["status"] == "ok"
    assert first["changed"] is True and second["changed"] is False
    assert binder.accounts["acc_goodman"]["logo_asset_id"] == LADDER_ASSET_ID


# --------------------------------------------------------------------------- #
# the refusals — an empty account logo is CORRECT
# --------------------------------------------------------------------------- #


def test_a_needs_review_fetch_leaves_nothing_to_bind_and_the_bind_refuses(
    tmp_path: Path,
) -> None:
    """Ruling R25-1: a `needs_review` ladder outcome NEVER auto-binds.

    `fetch_logo` registers nothing when the ladder cannot attribute a mark, so the document
    holds no asset to name — and naming one anyway is refused rather than improvised.
    """
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={})

    payload = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))

    assert payload["status"] == "error"
    assert payload["error_code"] == "account_logo.unknown_asset"
    assert binder.binds == []
    assert binder.accounts["acc_goodman"]["logo_asset_id"] is None
    # The refusal says empty is correct and never suggests drawing one.
    assert "correct" in payload["message"].lower()
    assert "never draw" in payload["message"].lower()


def test_a_generated_image_is_not_a_company_logo(tmp_path: Path) -> None:
    """The never-synthesize register, structurally: only the ladder's own mark may bind."""
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={"asset_gen_1": _generated_record()})

    payload = json.loads(tools.bind_account_logo("acc_goodman", "asset_gen_1"))

    assert payload["status"] == "error"
    assert payload["error_code"] == "account_logo.not_a_fetched_logo"
    assert binder.binds == []


def test_an_unknown_account_refuses_and_stamps_nothing(tmp_path: Path) -> None:
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={LADDER_ASSET_ID: _ladder_record()})

    payload = json.loads(tools.bind_account_logo("acc_elsewhere", LADDER_ASSET_ID))

    assert payload["status"] == "error"
    assert payload["error_code"] == "account_logo.unknown_account"
    assert binder.binds == []


def test_a_turn_with_no_binder_says_so_rather_than_pretending(tmp_path: Path) -> None:
    tools = _tools(tmp_path, binder=None, assets={LADDER_ASSET_ID: _ladder_record()})

    payload = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))

    assert payload["status"] == "error"
    assert payload["error_code"] == "account_logo.binder_unavailable"


@pytest.mark.parametrize(
    "account_id,asset_id", [("", LADDER_ASSET_ID), ("acc_goodman", "")]
)
def test_both_arguments_are_required(tmp_path: Path, account_id: str, asset_id: str) -> None:
    binder = FakeBinder()
    tools = _tools(tmp_path, binder=binder, assets={LADDER_ASSET_ID: _ladder_record()})

    payload = json.loads(tools.bind_account_logo(account_id, asset_id))

    assert payload["error_code"] == "account_logo.bad_request"
    assert binder.binds == []


def test_a_binder_refusal_surfaces_verbatim(tmp_path: Path) -> None:
    """The binder's own fail-closed doors (bytes, scoping) reach the agent unchanged."""
    binder = FakeBinder(
        refuse=("account_logo.bytes_unavailable", "nothing durable holds those bytes")
    )
    tools = _tools(tmp_path, binder=binder, assets={LADDER_ASSET_ID: _ladder_record()})

    payload = json.loads(tools.bind_account_logo("acc_goodman", LADDER_ASSET_ID))

    assert payload["error_code"] == "account_logo.bytes_unavailable"
    assert "nothing durable holds those bytes" in payload["message"]


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_the_bind_is_registered_on_the_author_role_beside_fetch_logo(tmp_path: Path) -> None:
    """`fetch_logo` without a bind is a logo that dies with the turn."""
    from lumen_agent import harness_web

    source = Path(harness_web.__file__).read_text()
    assert "tools.bind_account_logo" in source
    assert source.index("tools.fetch_logo") < source.index("tools.bind_account_logo")


# --------------------------------------------------------------------------- #
# prompt law — DRAFT wording, pinned by presence (the T17 lesson: never assert
# the opposite of what ships)
# --------------------------------------------------------------------------- #


def _squashed(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text)


def _director_prompt() -> str:
    from lumen_agent.prompts_web import build_web_orchestrator_prompt

    return build_web_orchestrator_prompt(
        doc_title="Insight Health",
        has_existing_content=False,
        brand_card="{}",
        review_cap=2,
        author_cap=2,
    )


def _author_prompt() -> str:
    from lumen_agent.prompts_web import build_web_author_prompt

    return build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_publish_the_derived_page_never_the_template_is_prompt_law(prompt_of) -> None:
    """Ruling R25-7's agent-facing sentence. The publish seam refuses a template; the prompt
    tells the agent why before it gets there."""
    prompt = _squashed(prompt_of())

    assert "PUBLISH THE DERIVED PAGE, NEVER THE TEMPLATE" in prompt
    assert "derived per account" in prompt


@pytest.mark.parametrize("prompt_of", [_director_prompt, _author_prompt])
def test_binding_a_fetched_mark_to_the_account_is_prompt_law(prompt_of) -> None:
    """R25-1/R25-2: the bind is a named per-account act, and an empty logo stays CORRECT."""
    prompt = _squashed(prompt_of())

    assert "bind_account_logo" in prompt
    assert "AN EMPTY LOGO SLOT IS CORRECT" in prompt


def test_the_recipe_says_the_same_two_things() -> None:
    """The recipe is where "what an ABM page must contain" lives; two laws, one voice."""
    recipe = (
        Path(__file__).resolve().parents[1]
        / "knowledge_docs/knowledge/web/abm-page.md"
    ).read_text()
    squashed = _squashed(recipe)

    assert "Publish only the resolved derived page" in squashed
    assert "bind_account_logo" in squashed
    assert "name-only presentation" in squashed


def test_vendor_fetched_records_pass_the_bind_gate_and_generated_ones_do_not():
    from lumen_api.agent_account_logos import is_fetched_logo

    vendor = {"provenance": {"created_by": "brandfetch"}}
    ladder = {"provenance": {"created_by": "logo_ladder"}}
    generated = {"provenance": {"created_by": "image_generation"}}
    assert is_fetched_logo(vendor) and is_fetched_logo(ladder)
    assert not is_fetched_logo(generated)
    # the old name still answers (deprecated alias, same object)
    from lumen_api.agent_account_logos import is_ladder_fetched

    assert is_ladder_fetched is is_fetched_logo
