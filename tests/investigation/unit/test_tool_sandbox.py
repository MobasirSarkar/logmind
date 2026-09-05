from unittest.mock import AsyncMock

import pytest

from investigation.tools import (
    GetTraceArgs,
    GetTraceResult,
    InvestigationToolbox,
    SearchLogsArgs,
    SearchLogsResult,
)


@pytest.mark.asyncio
async def test_tool_definitions_and_execution():
    mock_es = AsyncMock()
    mock_db = AsyncMock()
    toolbox = InvestigationToolbox(es_service=mock_es, db_manager=mock_db, tenant_id="acme")

    # 1. Verify schema definitions
    tool_defs = toolbox.get_tool_definitions()
    assert len(tool_defs) == 5
    tool_names = {t.function.name for t in tool_defs}
    assert "search_logs" in tool_names
    assert "get_trace" in tool_names
    assert "search_runbooks" in tool_names
    assert "get_related_incidents" in tool_names
    assert "get_service_dependencies" in tool_names

    # 2. Test search_logs execution with strong typing
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [{"_source": {"message": "GatewayTimeout", "level": "ERROR"}}],
        }
    }
    args = SearchLogsArgs(query="timeout", limit=5)
    res = await toolbox.search_logs(args)
    assert isinstance(res, SearchLogsResult)
    assert res.count == 1
    assert len(res.logs) == 1

    # 3. Test get_trace execution
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": 2},
            "hits": [
                {"_source": {"trace": {"span_id": "sp-1"}, "message": "Req 1"}},
                {"_source": {"trace": {"span_id": "sp-2"}, "message": "Req 2"}},
            ],
        }
    }
    trace_args = GetTraceArgs(trace_id="tr-100")
    trace_res = await toolbox.get_trace(trace_args)
    assert isinstance(trace_res, GetTraceResult)
    assert trace_res.trace_id == "tr-100"
    assert len(trace_res.spans) == 2
