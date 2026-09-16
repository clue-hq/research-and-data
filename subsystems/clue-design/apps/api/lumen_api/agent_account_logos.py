"""Binding a ladder-fetched mark to a TARGET ACCOUNT (clone-fidelity F4.3, ruling R25-1).

The logo ladder has been able to fetch a target company's real published mark for a while
(``lumen_ingestion.logo_ladder`` → the lane-agnostic ``logo_fetch`` prep → each substrate's
``fetch_logo``). What it could never do is make that mark an *account* fact:

* the fetched asset landed only in the WORKING DOCUMENT's by-value ``assets`` table, so no
  ``design_asset`` row existed and ``HybridRepository.require_asset_record`` refused it (gap G1);
* nothing wrote ``design_account.logo_asset_id`` (gap G2), which is the single column
  ``account_values()`` reads to resolve ``{{account.logo}}``.

So a batch derive over fifty accounts personalized fifty names and zero logos, however many
times an agent had fetched one. This module is the carry, and it is the SMALLEST honest shape:
one capability, one method, both halves in one call, and every door fail-closed.

**Why a capability and not a route.** The design agent is fleet work that holds no database
handle — the rule
:class:`~lumen_api.agent_cloned_sections.DurableAgentClonedSectionRegistry` already follows, for
the same reason. The API composes this object at turn setup, the runtime receives typed methods,
and the tenant comes from the injected blob store rather than from anything the agent says.

**Both durable writes go through the GOVERNED tools** (``design_register_asset_record`` and
``design_update_web_account``), exactly as
:class:`~lumen_api.agent_custom_components.DurableAgentCustomComponentRegistry`'s two writes do
— ruling R-D6-5 and the no-bypass guard that enforces it. So an agent-bound account logo is
journaled and A9-keyed exactly like the human PATCH of the same field, and the account tool's
own precondition (the logo must resolve to a known asset) becomes a second, independent check
on G1 having actually happened.

**Four laws this write obeys, in the order it checks them.**

1. **Workspace-scoped, fail-closed** (the B3 law). The account is read through
   ``(account_id, workspace_id)``; another tenant's account is exactly as unresolvable as an
   absent one, and neither stamps anything.
2. **Nothing auto-binds.** There is no path into here from a ladder OUTCOME. The caller names an
   account and names a record; a ``needs_review`` fetch produced no record to name, and the tool
   above refuses rather than improvising one. *An empty account logo is CORRECT* — the
   never-synthesize register, which this module exists to serve rather than to work around.
3. **Bytes before the stamp.** Custody is registered and then *probed*: a record whose bytes
   nothing durable holds is refused and the account is left alone. An account row pointing at
   unservable bytes is the white-chip failure with extra steps, and it would be discovered on a
   published page rather than here.
4. **Converges.** The registry write is a content-addressed upsert and the stamp is an
   assignment, so re-binding the same mark changes nothing and says so (``changed: false``).
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict

from clue_storage import StorageError
from clue_toolbelt import PreconditionFailed
from py_lumen_obs import get_logger

from clue_design.storage import SOURCE_KEY_ASSET

from .asset_custody import register_engine_write
from .database import NotFoundError
from .design_store import CustodyState, DesignBlobStore, HybridRepository
from .observability import log_event

# The ladder's own renderability predicate (one home, no drift): the bind door and the ladder
# must agree about what "a renderable mark" means. Cross-package import is the established
# direction (`lumen_ingestion` and `lumen_api` import each other at composition seams).
from lumen_ingestion.logo_ladder import svg_is_renderable

JsonObject = Dict[str, Any]

_logger = get_logger("lumen_api.agent_account_logos")

__all__ = [
    "FETCHED_LOGO_PROVENANCES",
    "LADDER_PROVENANCE",
    "VENDOR_PROVENANCE",
    "AccountLogoRefused",
    "DurableAgentAccountLogoBinder",
    "is_fetched_logo",
    "is_ladder_fetched",
]

#: ``provenance.created_by`` values that mean "a real published mark somebody's
#: brand actually serves" — the ladder's site harvest, or the Brandfetch Brand
#: API's keyed retrieval (vendor-first, 2026-09-02). This is what the bind
#: gates on: a generated image is not a company's logo, and neither is a
#: placeholder. Both are stamped by ``lumen_agent.tools.logo_fetch._assemble``.
LADDER_PROVENANCE = "logo_ladder"
VENDOR_PROVENANCE = "brandfetch"
FETCHED_LOGO_PROVENANCES = frozenset({LADDER_PROVENANCE, VENDOR_PROVENANCE, "logo_dev"})


class AccountLogoRefused(Exception):
    """A bind rule was broken. ``code`` is the stable ``account_logo.*`` label the tool reports.

    Same shape (and same reasoning) as
    :class:`~lumen_api.fragments.abm_page.AbmAssemblyRefused`: a refusal an agent can act on
    names WHICH rule and WHICH thing.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_fetched_logo(record: Any) -> bool:
    """True when ``record`` is a mark fetched from the company's own site or
    retrieved from the logo vendor keyed by the company's domain."""
    if not isinstance(record, dict):
        return False
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return str(provenance.get("created_by") or "") in FETCHED_LOGO_PROVENANCES


#: Deprecated alias (pre-vendor name); same object so identity checks hold.
is_ladder_fetched = is_fetched_logo


class DurableAgentAccountLogoBinder:
    """The sole account-logo capability exposed to one website-mode agent turn."""

    def __init__(
        self,
        *,
        blobs: DesignBlobStore,
        cache_dir: str | Path,
        invocations: Any,
    ) -> None:
        # The byte store carries the tenant and the row store is built from it, so the two can
        # never name different workspaces — the D4/D5 rule the cloned-section registry follows.
        self.blobs = blobs
        self.workspace_id = blobs.workspace_id
        # The TURN's engine cache: the ladder's ``ingest_asset`` wrote the bytes there, and a
        # fleet worker injects its own tree.
        self.cache_dir = Path(cache_dir)
        # The governed write path (R-D6-5). Required, not optional: a binder that could fall
        # back to the repository would be the bypass the guard exists to prevent.
        self.invocations = invocations

    def _repository(self) -> HybridRepository:
        return HybridRepository(self.workspace_id)

    def _invoke(self, name: str, body: JsonObject) -> JsonObject:
        """Run one governed design tool as the agent. A refusal RAISES, typed."""
        try:
            result = self.invocations.invoke(
                name, body, workspace_id=self.workspace_id, actor="agent"
            )
        except PreconditionFailed as refused:
            # The tool's own reason codes, relayed rather than re-worded: the account tool
            # already refuses an unknown account and a logo that resolves to nothing, and
            # inventing a second vocabulary for the same refusal is how two truths start.
            raise AccountLogoRefused(
                f"account_logo.{'_'.join(refused.reason_codes[:1]) or 'refused'}",
                "; ".join(failure.message for failure in refused.failures)
                or "the governed write refused",
            ) from refused
        return dict(result.references)

    def bind(self, *, account_id: str, record: JsonObject) -> JsonObject:
        """Register ``record`` durably (G1) and stamp it on ``account_id`` (G2). One gesture.

        Returns ``{account_id, account_name, asset_id, digest, previous_asset_id, changed}``.
        Raises :class:`AccountLogoRefused` — never a bare exception — at every door, and stamps
        nothing when it does.
        """
        repository = self._repository()
        account = repository.get_web_account(str(account_id))
        if account is None:
            raise AccountLogoRefused(
                "account_logo.unknown_account",
                f"no target account {account_id!r} in this workspace. Accounts are "
                "workspace-local, so an id from somewhere else is as unresolvable as one that "
                "was never created. Nothing was registered and nothing was stamped.",
            )

        asset_id = str((record or {}).get("id") or "")
        digest = ((record or {}).get("media") or {}).get("digest") or {}
        digest_value = str(digest.get("value") or "")
        if not asset_id or not digest_value:
            raise AccountLogoRefused(
                "account_logo.unusable_record",
                "that asset record carries no id or no sha256 digest, so nothing durable could "
                "be addressed by it. Nothing was stamped.",
            )

        # Mutated in place by the custody write (it re-points `media.location` at platform
        # storage), and the caller's copy is a live document record — so work on our own.
        stored_record = copy.deepcopy(record)
        try:
            register_engine_write(
                self.blobs,
                self.cache_dir,
                source_key=SOURCE_KEY_ASSET,
                record=stored_record,
            )
        except StorageError as error:
            raise AccountLogoRefused(
                "account_logo.bytes_unavailable",
                f"the mark's bytes could not be given durable custody ({error}). The account "
                "was left as it was; an empty account logo is CORRECT, and a page that renders "
                "one is a clean page, never a broken one.",
            ) from error

        # BYTES BEFORE THE STAMP. `register_engine_write` is fail-soft on a cache file that is
        # simply absent (the engine reports its own misses), so "it did not raise" is not proof.
        # Probe for RETRIEVABLE bytes — the same distinction the scene backstop learned the hard
        # way — because an account row pointing at bytes nobody holds renders an empty box on
        # every page derived from it, forever.
        state = self.blobs.custody_states([digest_value]).get(
            digest_value, CustodyState.ABSENT
        )
        if state is not CustodyState.READABLE:
            raise AccountLogoRefused(
                "account_logo.bytes_unavailable",
                f"asset {asset_id!r} names bytes that nothing durable holds ({state.value}), so "
                "binding it would point this account at an image no page can serve. The account "
                "was left as it was; an empty account logo is CORRECT.",
            )

        # THE MARK MUST BE ABLE TO PAINT (F4 wave item 2, the CP2 walk's F-3): the ladder
        # accepted a 124-byte sprite-reference SVG — no viewBox, no artwork — and the bind
        # reported success while every derived page rendered a 0×0 nothing. "bound: true with
        # nothing delivered" is the exact failure mode this plan's data model exists to
        # prevent, so an SVG that cannot paint standalone refuses HERE, before any durable
        # write. The predicate is the ladder's own (one home, no drift).
        media = stored_record.get("media") if isinstance(stored_record, dict) else None
        mime = str((media or {}).get("mime_type") or "").lower()
        if "svg" in mime:
            # FAIL CLOSED (wave round 2, the re-walk's N-4): the custody probe above just
            # vouched READABLE, so a read that raises here is a real inconsistency — skipping
            # the check on it would bind a mark nobody inspected. A guard never fails open
            # silently.
            try:
                svg_bytes = self.blobs.read(digest_value)
            except Exception as error:  # noqa: BLE001 - refused, never skipped
                raise AccountLogoRefused(
                    "account_logo.bytes_unavailable",
                    f"asset {asset_id!r} passed the custody probe but its bytes could not be "
                    f"read back ({type(error).__name__}) — binding a mark nobody could inspect "
                    "would be a co-brand on faith. The account was left as it was.",
                ) from error
            if not svg_is_renderable(svg_bytes):
                raise AccountLogoRefused(
                    "account_logo.no_renderable_mark",
                    f"asset {asset_id!r} is an SVG that cannot paint anything on its own — no "
                    "intrinsic geometry or no drawable artwork (a sprite reference, not a "
                    "logo). Binding it would report a co-brand that renders 0×0 on every "
                    "page. The account was left as it was; an empty account logo is CORRECT, "
                    "and a real file from the client beats a broken fetch.",
                )

        # G1 — the registry `require_asset_record` (and therefore `account_values`) reads. The
        # store write is a content-addressed upsert, so re-binding the same mark converges.
        self._invoke("design_register_asset_record", {"record": stored_record})
        try:
            repository.require_asset_record(asset_id)
        except NotFoundError as error:  # pragma: no cover - a write that did not write
            raise AccountLogoRefused(
                "account_logo.registration_failed",
                f"asset {asset_id!r} did not resolve in this workspace's registry after being "
                "written. Nothing was stamped.",
            ) from error

        # G2 — the one column the F1.4 account derive reads. The tool's own precondition
        # re-checks that the logo resolves, which is an independent verdict on G1 above.
        previous = account.get("logo_asset_id")
        self._invoke(
            "design_update_web_account",
            {"account_id": str(account_id), "patch": {"logo_asset_id": asset_id}},
        )
        updated = repository.require_web_account(str(account_id))
        log_event(
            _logger,
            logging.INFO,
            "design_account.logo_bound",
            workspace_id=self.workspace_id,
            account_id=str(account_id),
            asset_id=asset_id,
            digest=digest_value,
            changed=previous != asset_id,
        )
        return {
            "account_id": str(account_id),
            "account_name": updated.get("name"),
            "asset_id": asset_id,
            "digest": digest_value,
            "previous_asset_id": previous,
            "changed": previous != asset_id,
        }
