"""Regression tests for the `/latest`-rewriting request hook wired into
SDMXProgressiveClient._get_session(). Built-in providers must see no change
in behaviour; only an endpoint declaring `latest_version_strategy` is
rewritten."""

import pytest
import respx

from config import SDMX_ENDPOINTS
from sdmx_progressive_client import SDMXProgressiveClient

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@respx.mock
async def test_builtin_providers_are_never_rewritten():
    for key, ep in SDMX_ENDPOINTS.items():
        assert ep.get("latest_version_strategy") is None, key
        client = SDMXProgressiveClient(
            base_url=ep["base_url"], agency_id=ep["agency_id"], endpoint_key=key
        )
        url = f"{client.base_url}/dataflow/{client.agency_id}/DF_TEST/latest"
        route = respx.get(url).respond(200, text="ok")
        session = await client._get_session()
        response = await session.get(url)
        assert response.status_code == 200
        assert route.calls.last.request.url.path.endswith("/latest")
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_omit_strategy_strips_the_trailing_latest_segment(monkeypatch):
    monkeypatch.setitem(
        SDMX_ENDPOINTS,
        "TESTOMIT",
        {
            "base_url": "https://sdmx.test.example/rest",
            "agency_id": "TESTOMIT",
            "latest_version_strategy": "omit",
        },
    )
    client = SDMXProgressiveClient(
        base_url="https://sdmx.test.example/rest", agency_id="TESTOMIT", endpoint_key="TESTOMIT"
    )
    route = respx.get("https://sdmx.test.example/rest/dataflow/TESTOMIT/DF_TEST").respond(
        200, text="ok"
    )
    session = await client._get_session()
    response = await session.get("https://sdmx.test.example/rest/dataflow/TESTOMIT/DF_TEST/latest")
    assert response.status_code == 200
    assert route.calls.last.request.url.path == "/rest/dataflow/TESTOMIT/DF_TEST"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_pinned_version_strategy_substitutes_the_literal_version(monkeypatch):
    monkeypatch.setitem(
        SDMX_ENDPOINTS,
        "TESTPIN",
        {
            "base_url": "https://sdmx.test.example/rest",
            "agency_id": "TESTPIN",
            "latest_version_strategy": "2.0.0",
        },
    )
    client = SDMXProgressiveClient(
        base_url="https://sdmx.test.example/rest", agency_id="TESTPIN", endpoint_key="TESTPIN"
    )
    route = respx.get("https://sdmx.test.example/rest/dataflow/TESTPIN/DF_TEST/2.0.0").respond(
        200, text="ok"
    )
    session = await client._get_session()
    response = await session.get("https://sdmx.test.example/rest/dataflow/TESTPIN/DF_TEST/latest")
    assert response.status_code == 200
    assert route.calls.last.request.url.path == "/rest/dataflow/TESTPIN/DF_TEST/2.0.0"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_strategy_only_rewrites_a_trailing_latest_segment(monkeypatch):
    """A path that merely contains 'latest' mid-segment (not as the final
    path component) must be left untouched."""
    monkeypatch.setitem(
        SDMX_ENDPOINTS,
        "TESTOMIT2",
        {
            "base_url": "https://sdmx.test.example/rest",
            "agency_id": "TESTOMIT2",
            "latest_version_strategy": "omit",
        },
    )
    client = SDMXProgressiveClient(
        base_url="https://sdmx.test.example/rest", agency_id="TESTOMIT2", endpoint_key="TESTOMIT2"
    )
    route = respx.get(
        "https://sdmx.test.example/rest/dataflow/TESTOMIT2/DF_latest_test"
    ).respond(200, text="ok")
    session = await client._get_session()
    response = await session.get(
        "https://sdmx.test.example/rest/dataflow/TESTOMIT2/DF_latest_test"
    )
    assert response.status_code == 200
    assert route.calls.last.request.url.path == "/rest/dataflow/TESTOMIT2/DF_latest_test"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_no_endpoint_key_is_never_rewritten():
    client = SDMXProgressiveClient(
        base_url="https://sdmx.test.example/rest", agency_id="ANON"
    )
    route = respx.get("https://sdmx.test.example/rest/dataflow/ANON/DF_TEST/latest").respond(
        200, text="ok"
    )
    session = await client._get_session()
    response = await session.get("https://sdmx.test.example/rest/dataflow/ANON/DF_TEST/latest")
    assert response.status_code == 200
    assert route.calls.last.request.url.path.endswith("/latest")
    await client.close()
