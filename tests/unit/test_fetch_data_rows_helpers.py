"""Unit tests for the fetch_data_rows helpers in tools/sdmx_tools.py."""

import pytest

from httpx import Response

from tools.sdmx_tools import parse_rows_from_response

pytestmark = pytest.mark.unit


class TestParseStreamedRows:
    @pytest.mark.asyncio
    async def test_header_and_rows_under_max_rows(self):
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO,OBS_VALUE\nA,FJ,123\nA,TO,456"),
            max_rows=10
        )
        assert result.headers == ["FREQ", "GEO", "OBS_VALUE"]
        assert result.rows == [
            {"FREQ": "A", "GEO": "FJ", "OBS_VALUE": "123"},
            {"FREQ": "A", "GEO": "TO", "OBS_VALUE": "456"},
        ]
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_more_rows_than_max_rows_are_truncated(self):
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO\nA,FJ\nA,TO\nA,VU"),
            max_rows=2
        )
        assert len(result.rows) == 2
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_exactly_max_rows_with_no_more_data_is_not_truncated(self):
        """The stream ends right at max_rows: there is no extra row to reveal
        truncation, so this must not be confused with actually having more
        data than max_rows (which would need to be signalled to the caller)."""
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO\nA,FJ\nA,TO"),
            max_rows=2
        )
        assert len(result.rows) == 2
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_header_only_stream_keeps_headers_with_zero_rows(self):
        """A header-only response is a valid empty result; the caller still
        needs the column names even though no data rows exist."""
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO,OBS_VALUE"),
            max_rows=10
        )
        assert result.headers == ["FREQ", "GEO", "OBS_VALUE"]
        assert result.rows == []
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_empty_stream_returns_empty_result(self):
        result = await parse_rows_from_response(Response(200), max_rows=10)
        assert result.headers == []
        assert result.rows == []
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_blank_lines_are_skipped(self):
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO\n\nA,FJ\n\nA,TO"),
            max_rows=10
        )
        assert len(result.rows) == 2

    @pytest.mark.asyncio
    async def test_a_ragged_row_shorter_than_the_header_drops_trailing_columns(self):
        """zip() stops at the shorter iterable: a row with fewer fields than
        the header omits the trailing header keys rather than filling them
        with an empty string."""
        result = await parse_rows_from_response(
            Response(200, content=b"FREQ,GEO,OBS_VALUE\nA,FJ"),
            max_rows=10
        )
        assert result.rows == [{"FREQ": "A", "GEO": "FJ"}]

