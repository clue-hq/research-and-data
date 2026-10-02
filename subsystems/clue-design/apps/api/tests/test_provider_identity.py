"""Provider metadata identity checks, independent of logo pixel inspection."""

import json

import pytest
from lumen_ingestion.provider_identity import ProviderIdentityError, validate_vendor_identity


@pytest.mark.parametrize(
    "requested, returned",
    [
        ("Acme", "Acme Inc."),
        ("Acme Cloud", "Acme Cloud"),
        ("AWS", "Amazon Web Services"),
        ("Amazon Web Services", "AWS"),
        ("AWS", "Amazon Web Services (AWS)"),
        ("Café-Cloud", "CAFÉ Cloud LLC"),
    ],
)
def test_exact_host_and_meaningful_name_or_acronym_match(requested, returned):
    evidence = validate_vendor_identity(
        {"domain": "WWW.cloud.acme.com.", "name": returned, "id": "brand_1"},
        requested_domain="https://cloud.acme.com/pricing",
        company_name=requested,
    )
    assert evidence["domain_match"] == "exact_host"
    assert evidence["name_match"] in {"normalized_exact", "acronym"}
    assert evidence["provider_name"] == returned
    assert evidence["provider_id"] == "brand_1"


@pytest.mark.parametrize(
    "requested_host, returned_host",
    [
        ("cloud.acme.com", "acme.com"),
        ("acme.com", "cloud.acme.com"),
        ("cloud.acme.com", "mail.acme.com"),
        ("acme.com", "acme.com.evil.test"),
    ],
)
def test_parent_subbrand_sibling_and_suffix_domains_are_not_equivalent(
    requested_host, returned_host
):
    with pytest.raises(ProviderIdentityError) as error:
        validate_vendor_identity(
            {"domain": returned_host, "name": "Acme"},
            requested_domain=requested_host,
            company_name="Acme",
        )
    assert error.value.code == "identity_mismatch"


@pytest.mark.parametrize(
    "requested, returned",
    [
        ("Acme Cloud", "Acme"),
        ("Acme Cloud", "Acme Mail"),
        ("Amazon Web Services", "Amazon"),
        ("Google Cloud", "Google"),
        ("Acme", "Unrelated"),
    ],
)
def test_matching_host_does_not_override_a_conflicting_product_name(requested, returned):
    with pytest.raises(ProviderIdentityError) as error:
        validate_vendor_identity(
            {"domain": "brand.test", "name": returned},
            requested_domain="brand.test",
            company_name=requested,
        )
    assert error.value.code == "identity_mismatch"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"domain": "acme.com"},
        {"domain": "", "name": "Acme"},
        {"domain": "acme.com", "name": "Inc."},
    ],
)
def test_missing_or_nonmeaningful_identity_is_unverified(payload):
    with pytest.raises(ProviderIdentityError) as error:
        validate_vendor_identity(payload, requested_domain="acme.com", company_name="Acme")
    assert error.value.code == "identity_unverified"


def test_extra_name_qualifier_is_uncertain_not_a_claimed_conflict():
    with pytest.raises(ProviderIdentityError) as error:
        validate_vendor_identity(
            {"domain": "casiola.com", "name": "Casiola Vacation Homes"},
            requested_domain="casiola.com",
            company_name="Casiola",
        )
    assert error.value.code == "identity_unverified"


def test_domain_only_caller_retains_identity_without_claiming_name_match():
    evidence = validate_vendor_identity(
        {"domain": "acme.com", "name": "Acme", "id": "brand_1"},
        requested_domain="www.acme.com",
    )
    assert evidence["name_match"] == "not_requested"
    assert evidence["requested_company_name"] is None


def test_scheme_relative_and_idna_domains_share_the_same_exact_host():
    evidence = validate_vendor_identity(
        {"domain": "xn--bcher-kva.example", "name": "Bücher"},
        requested_domain="//www.bücher.example./catalog",
        company_name="Bücher",
    )
    assert evidence["requested_domain"] == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "Acme https://img.logo.dev/acme.com?token=pk_fixture",
        "Acme https%3A%2F%2Fimg.logo.dev%2Facme.com%3Ftoken%3Dpk_fixture",
        "Acme Authorization: Bearer sk_fixture",
        "Acme token=pk_fixture",
        "Acme pk_fixture",
        "Acme\nPrivate",
        "A" * 257,
    ],
)
@pytest.mark.parametrize("name_source", ["provider", "requested", "both"])
def test_unsafe_names_are_unverified_without_disclosing_metadata(unsafe_name, name_source):
    returned = unsafe_name if name_source != "requested" else "Acme"
    requested = unsafe_name if name_source != "provider" else None
    with pytest.raises(ProviderIdentityError) as caught:
        validate_vendor_identity(
            {"domain": "acme.com", "name": returned},
            requested_domain="acme.com",
            company_name=requested,
        )
    assert caught.value.code == "identity_unverified"
    assert unsafe_name not in str(caught.value)
    assert "fixture" not in str(caught.value)


@pytest.mark.parametrize(
    "domain, returned, requested, code",
    [
        ("other.example", "Private Other", "Private Acme", "identity_mismatch"),
        ("acme.com", "Private Other", "Private Acme", "identity_mismatch"),
        ("acme.com", "Private Acme Cloud", "Private Acme", "identity_unverified"),
    ],
)
def test_identity_errors_do_not_interpolate_input_metadata(domain, returned, requested, code):
    with pytest.raises(ProviderIdentityError) as caught:
        validate_vendor_identity(
            {"domain": domain, "name": returned},
            requested_domain="acme.com",
            company_name=requested,
        )
    assert caught.value.code == code
    assert all(value not in str(caught.value) for value in (domain, returned, requested))


@pytest.mark.parametrize(
    "provider_id",
    [
        "https://img.logo.dev/acme.com?token=pk_fixture",
        "token=pk_fixture",
        "Bearer sk_fixture",
        "pk_fixture",
        "id\nfixture",
        "i" * 129,
        {"token": "pk_fixture"},
    ],
)
def test_successful_evidence_normalizes_domains_and_omits_unsafe_ids(provider_id):
    evidence = validate_vendor_identity(
        {
            "domain": "https://WWW.acme.com./private?token=pk_fixture#secret",
            "name": "  Acme Inc.  ",
            "id": provider_id,
        },
        requested_domain="https://acme.com/private?token=sk_fixture",
        company_name="  Acme  ",
    )
    assert evidence["requested_domain"] == evidence["provider_domain"] == "acme.com"
    assert evidence["requested_company_name"] == "Acme"
    assert evidence["provider_name"] == "Acme Inc."
    assert evidence["provider_id"] is None
    assert "fixture" not in json.dumps(evidence)
    assert "private" not in json.dumps(evidence)


def test_long_domain_cannot_escape_the_bounded_identity_evidence():
    domain = ".".join(["a" * 63] * 5)
    with pytest.raises(ProviderIdentityError) as caught:
        validate_vendor_identity({"domain": domain, "name": "Acme"}, requested_domain=domain)
    assert caught.value.code == "identity_unverified"
