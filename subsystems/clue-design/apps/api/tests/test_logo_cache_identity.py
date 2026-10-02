"""Product hosts must never reuse parent-company or pre-verification logo entries."""
from types import SimpleNamespace

from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache


def test_product_hosts_are_distinct_cache_keys():
    key = DurableLogoFamilyCache._key
    assert key("https://cloud.google.com/") != key("https://google.com/")
    assert key("https://aws.amazon.com/") != key("https://amazon.com/")
    assert key("https://www.acme.com/path") == key("https://acme.com/")


def test_legacy_unverified_family_is_a_miss(monkeypatch):
    from lumen_api.design_store import DesignStoreBridge
    monkeypatch.setattr(
        DesignStoreBridge, "_run",
        lambda self, fn: {"family": {"site": "https://acme.com/", "cells": {}}},
    )
    cache = DurableLogoFamilyCache(blobs=SimpleNamespace(workspace_id="test"))
    # A legacy row must be refused before trying to read any of its blobs.
    assert cache._get("https://acme.com/") is None
