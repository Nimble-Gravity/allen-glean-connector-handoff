"""Tests for GleanConfig — instance-name normalization (tolerate a pasted URL)."""

from glean_index.client import GleanConfig


def test_instance_normalized_from_full_url():
    cfg = GleanConfig(instance="https://ed1d9232-be.glean.com/api/index/v1/", indexing_api_key="x")
    assert cfg.instance == "ed1d9232"


def test_instance_normalized_from_host_only():
    assert (
        GleanConfig(instance="ed1d9232-be.glean.com", indexing_api_key="x").instance == "ed1d9232"
    )
    assert (
        GleanConfig(instance=" acme-prod.glean.com ", indexing_api_key="x").instance == "acme-prod"
    )


def test_bare_instance_unchanged():
    assert GleanConfig(instance="acme-prod", indexing_api_key="x").instance == "acme-prod"
    assert GleanConfig(instance="ed1d9232", indexing_api_key="x").instance == "ed1d9232"
