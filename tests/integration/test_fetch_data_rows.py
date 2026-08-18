"""Integration tests for fetch_data_rows: the tools/sdmx_tools.py impl
function (real streaming via respx) and the main_server.py MCP tool
(orchestration around it)."""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest
import respx

from models.schemas import FetchRowsInput
from sdmx_progressive_client import DataStructureSummary, DimensionInfo
from tools.sdmx_tools import fetch_data_rows

pytestmark = pytest.mark.integration

CSV_BODY = (
    "DATAFLOW,FREQ,GEO_PICT,INDICATOR,TIME_PERIOD,OBS_VALUE\n"
    "SPC:DF_KAVA(3.0),A,FJ,KAVA_PROD,2020,1234\n"
    "SPC:DF_KAVA(3.0),A,FJ,KAVA_PROD,2021,1456\n"
    "SPC:DF_KAVA(3.0),A,TO,KAVA_PROD,2020,789\n"
)

DATA_URL = "https://example.org/rest/data/DF_KAVA/A.FJ.KAVA_PROD"


class FakeClient:
    """Client stub whose _get_session() is a real httpx.AsyncClient, so
    @respx.mock can intercept it - mirrors the FakeClient pattern in
    tests/integration/test_reference_metadata.py."""

    def __init__(self, structure=None):
        self.base_url = "https://example.org/rest"
        self.agency_id = "SPC"
        self.endpoint_key = "SPC"
        self._structure = structure
        self._session: httpx.AsyncClient | None = None

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None:
            self._session = httpx.AsyncClient()
        return self._session

    async def get_structure_summary(self, dataflow_id, agency_id=None, ctx=None):
        return self._structure

    def verify_scheme_and_host(self, data_url: str) -> bool:
        allowed = urlparse(self.base_url)
        requested = urlparse(data_url)
        return bool(
            requested.scheme and requested.netloc
            and (requested.scheme, requested.netloc) == (allowed.scheme, allowed.netloc)
        )


class TestFetchDataRowsImpl:
    """tools.sdmx_tools.fetch_data_rows: real streaming/parsing/error wiring."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_streams_and_parses_a_csv_response(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, text=CSV_BODY))

        result = await fetch_data_rows(FakeClient(), DATA_URL, max_rows=10, timeout_s=5.0)

        assert result.headers == [
            "DATAFLOW", "FREQ", "GEO_PICT", "INDICATOR", "TIME_PERIOD", "OBS_VALUE",
        ]
        assert len(result.rows) == 3
        assert result.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_more_rows_than_max_rows_are_truncated(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, text=CSV_BODY))

        result = await fetch_data_rows(FakeClient(), DATA_URL, max_rows=2, timeout_s=5.0)

        assert len(result.rows) == 2
        assert result.truncated is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_status_raises_with_the_status_code(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(404, text="Not Found"))

        with pytest.raises(httpx.HTTPStatusError, match="404"):
            await fetch_data_rows(FakeClient(), DATA_URL, max_rows=10, timeout_s=5.0)


class TestFetchDataRowsTool:
    """main_server.fetch_data_rows: orchestration around the impl function."""

    @pytest.fixture
    def mock_structure(self):
        return DataStructureSummary(
            id="TRADE_DSD",
            agency="SPC",
            version="1.0",
            dimensions=[
                DimensionInfo(id="FREQ", position=1, type="Dimension"),
                DimensionInfo(id="REF_AREA", position=2, type="Dimension"),
                DimensionInfo(id="TIME_PERIOD", position=3, type="TimeDimension"),
            ],
            key_family=["FREQ", "REF_AREA"],
            attributes=[],
            primary_measure="OBS_VALUE",
        )
    

    '''Use mocks to let main_server._resolve_client() return a fake client for testing'''

    @pytest.fixture
    def fake_client(self, mock_structure):
        return FakeClient(structure=mock_structure)

    @pytest.fixture
    def mock_session_state(self, fake_client):
        session = MagicMock()
        session.default_endpoint_key = "SPC"
        session.get_or_create_client = AsyncMock(return_value=fake_client)
        session.register_dataflow = MagicMock()
        session.snapshot_known_dataflows = MagicMock(return_value={})
        return session

    @pytest.fixture
    def mock_app_context(self, mock_session_state):
        app_ctx = MagicMock()
        app_ctx.get_session.return_value = mock_session_state
        return app_ctx

    @pytest.mark.asyncio
    @patch("main_server.get_app_context")
    async def test_missing_data_url_and_dataflow_id_is_an_error(
        self, mock_get_app, mock_app_context
    ):
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context

        result = await fetch_data_rows_tool(ctx=None)

        assert result.status == "error"
        assert "required" in (result.message or "")

    def test_data_url_with_key_raises_value_error(self):
        """Input validation: data_url is mutually exclusive with key."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            FetchRowsInput(data_url=DATA_URL, key="A.FJ")

    def test_data_url_with_filters_raises_value_error(self):
        """Input validation: data_url is mutually exclusive with filters."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            FetchRowsInput(data_url=DATA_URL, filters={"FREQ": "A"})

    def test_data_url_with_mismatched_dataflow_id_raises_value_error(self):
        """Input validation: provided dataflow_id must match the data_url path."""
        with pytest.raises(ValueError, match="does not match data_url"):
            FetchRowsInput(data_url=DATA_URL, dataflow_id="WRONG_DATAFLOW")

    @pytest.mark.asyncio
    @respx.mock
    @patch("main_server.get_app_context")
    async def test_data_url_with_a_different_host_is_rejected(
        self, mock_get_app, mock_app_context
    ):
        """SSRF guard: a data_url must share scheme+host with the endpoint's
        base_url, or the fetch must be refused before any request is made."""
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context

        result = await fetch_data_rows_tool(
            data_url="https://evil.example/data/DF", ctx=None
        )

        assert result.status == "error"

    @pytest.mark.asyncio
    @respx.mock
    @patch("main_server.get_app_context")
    async def test_structured_input_success_maps_the_parsed_rows(
        self, mock_get_app, mock_app_context, mock_session_state, fake_client
    ):
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context
        respx.get(url__startswith=fake_client.base_url + "/data/TRADE_FOOD/A.FJ").mock(
            return_value=httpx.Response(200, text=CSV_BODY)
        )

        result = await fetch_data_rows_tool(
            dataflow_id="TRADE_FOOD", key="A.FJ", ctx=None
        )

        assert result.status == "ok"
        assert result.dataflow_id == "TRADE_FOOD"
        assert result.headers == [
            "DATAFLOW", "FREQ", "GEO_PICT", "INDICATOR", "TIME_PERIOD", "OBS_VALUE",
        ]
        assert result.returned_rows == 3
        assert result.truncated is False
        # the new dataflow should have been registered with the default endpoint
        mock_session_state.register_dataflow.assert_called_once_with("SPC", "TRADE_FOOD")

    @pytest.mark.asyncio
    @respx.mock
    @patch("main_server.get_app_context")
    async def test_structured_filters_without_key_success(
        self, mock_get_app, mock_app_context, mock_session_state, fake_client
    ):
        """Structured input path works with filters (without key)."""
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context
        respx.get(url__startswith=fake_client.base_url + "/data/TRADE_FOOD/").mock(
            return_value=httpx.Response(200, text=CSV_BODY)
        )

        result = await fetch_data_rows_tool(
            dataflow_id="TRADE_FOOD",
            filters={"FREQ": "A", "REF_AREA": "FJ"},
            ctx=None,
        )

        assert result.status == "ok"
        assert result.dataflow_id == "TRADE_FOOD"
        assert result.headers == [
            "DATAFLOW", "FREQ", "GEO_PICT", "INDICATOR", "TIME_PERIOD", "OBS_VALUE",
        ]
        assert result.returned_rows == 3
        assert result.truncated is False
        mock_session_state.register_dataflow.assert_called_once_with("SPC", "TRADE_FOOD")

    @pytest.mark.asyncio
    @respx.mock
    @patch("main_server.get_app_context")
    async def test_provider_http_error_reports_status_and_a_mismatch_hint(
        self, mock_get_app, mock_app_context, mock_session_state, fake_client
    ):
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context
        mock_session_state.snapshot_known_dataflows.return_value = {"ECB": {"TRADE_FOOD"}}
        data_url = fake_client.base_url + "/data/TRADE_FOOD/all"
        respx.get(data_url).mock(return_value=httpx.Response(404, text="Not Found"))

        result = await fetch_data_rows_tool(
            data_url=data_url, dataflow_id="TRADE_FOOD", ctx=None
        )

        assert result.status == "error"
        assert "404" in (result.message or "")
        assert "ECB" in (result.message or "")

    @pytest.mark.asyncio
    @respx.mock
    @patch("main_server.get_app_context")
    async def test_truncated_result_is_marked_correctly(
        self, mock_get_app, mock_app_context, fake_client
    ):
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context
        data_url = fake_client.base_url + "/data/TRADE_FOOD/all"
        respx.get(data_url).mock(return_value=httpx.Response(200, text=CSV_BODY))

        result = await fetch_data_rows_tool(
            data_url=data_url, max_rows=1, ctx=None
        )

        assert result.status == "ok"
        assert result.truncated is True
        assert result.returned_rows == 1
        assert result.notes

    @pytest.mark.asyncio
    @patch("main_server.get_app_context")
    async def test_an_unexpected_fetch_failure_is_reported_generically(
        self, mock_get_app, mock_app_context, fake_client
    ):
        from main_server import fetch_data_rows as fetch_data_rows_tool

        mock_get_app.return_value = mock_app_context
        data_url = fake_client.base_url + "/data/TRADE_FOOD/all"
        fake_client._get_session = AsyncMock(side_effect=RuntimeError("network down"))

        result = await fetch_data_rows_tool(data_url=data_url, ctx=None)

        assert result.status == "error"
        assert result.message
