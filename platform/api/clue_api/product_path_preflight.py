"""One startup gate: the integration product path fails loudly when a required credential
is absent (contract §9), instead of composing silently-degraded provider slots.

Every ``Secrets`` credential field is ``SecretStr | None``, and several compositions accept the
``None`` quietly — the email-lookup service, for instance, builds per-provider "unavailable"
outcomes when a key is absent, so an unconfigured pilot deployment looks alive and returns nothing.
The pilot product path turns those provider flags on by default, so the check belongs *once*, at
each composition root, before any wiring happens: a deployment that cannot serve the path it
declares refuses to start and names every missing ``CLUE_*`` variable at once.

The default product path is untouched — an operator who has not opted into the pilot overlay keeps
today's flag-by-flag behaviour, including the degraded-but-running compositions.
"""

from __future__ import annotations

from pydantic import SecretStr

from clue_config import Secrets, Settings


class ProductPathCompositionError(RuntimeError):
    """A declared product path requires a credential this deployment does not carry."""


# (settings flag, secrets attribute, the env var named in the error).
# A flag appears once per credential it needs; the error de-duplicates the env names.
_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    ("exa_websets_lifecycle_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("exa_account_deep_acquisition_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("exa_contact_deep_acquisition_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("sumble_account_gap_enrichment_enabled", "sumble_api_key", "CLUE_SUMBLE_API_KEY"),
    ("sumble_committee_acquisition_enabled", "sumble_api_key", "CLUE_SUMBLE_API_KEY"),
    ("chat_enabled", "openrouter_api_key", "CLUE_OPENROUTER_API_KEY"),
    # Slice F appends: (contact_channel/email lookup, exa+sumble keys).
)


def _is_absent(value: SecretStr | None) -> bool:
    """A credential is absent when it is unset **or** blank.

    ``.env.example`` ships every provider key as a bare ``CLUE_EXA_API_KEY=``, which
    pydantic-settings reads as ``SecretStr("")`` rather than ``None`` — so an ``is None`` test lets
    a copied example file through, and the pilot process starts with a dead provider slot.
    Whitespace is stripped for the same reason (a key that is only spaces configures nothing).
    """

    return value is None or not value.get_secret_value().strip()


def assert_product_path_composition(settings: Settings, secrets: Secrets) -> None:
    """Refuse to compose an ``integration_pilot`` process that is missing a required credential."""

    if settings.product_path != "integration_pilot":
        return
    missing = sorted(
        {
            env_name
            for flag, secret_attr, env_name in _REQUIREMENTS
            if getattr(settings, flag) and _is_absent(getattr(secrets, secret_attr))
        }
    )
    if missing:
        raise ProductPathCompositionError(
            "integration_pilot product path is missing required credentials: " + ", ".join(missing)
        )
