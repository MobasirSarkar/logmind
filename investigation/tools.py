import asyncio
import json
import logging
from typing import Any, cast

from app.constants import ESIndexPrefix
from app.services.elasticsearch import ElasticsearchService
from investigation.client import ToolDefinition, ToolFunctionSpec
from investigation.models import (
    GetRelatedIncidentsArgs,
    GetRelatedIncidentsResult,
    GetServiceDependenciesArgs,
    GetServiceDependenciesResult,
    GetTraceArgs,
    GetTraceResult,
    SearchLogsArgs,
    SearchLogsResult,
    SearchRunbooksArgs,
    SearchRunbooksResult,
    ToolName,
)
from investigation.runbooks import RunbookStore

logger = logging.getLogger("uvicorn.error")

__all__ = [
    "GetRelatedIncidentsArgs",
    "GetRelatedIncidentsResult",
    "GetServiceDependenciesArgs",
    "GetServiceDependenciesResult",
    "GetTraceArgs",
    "GetTraceResult",
    "InvestigationToolbox",
    "SearchLogsArgs",
    "SearchLogsResult",
    "SearchRunbooksArgs",
    "SearchRunbooksResult",
]


# --- Toolbox Implementation ---


def _extract_es_dict(res: Any) -> dict[str, Any]:
    if hasattr(res, "body") and isinstance(res.body, dict):
        return res.body
    if isinstance(res, dict):
        return res
    return {}


class InvestigationToolbox:
    def __init__(
        self,
        es_service: Any,
        db_manager: Any,
        tenant_id: str,
        runbook_service: RunbookStore | None = None,
        timeout: float = 5.0,
    ):
        if isinstance(es_service, ElasticsearchService):
            self.es = es_service.es
        else:
            self.es = es_service
        self.db = db_manager
        self.tenant_id = tenant_id
        self.runbooks = runbook_service
        self.timeout = timeout

    def get_tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name=ToolName.SEARCH_LOGS.value,
                    description="Search logs in Elasticsearch using keywords, service filter, and time window.",
                    parameters=SearchLogsArgs.model_json_schema(),
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name=ToolName.GET_TRACE.value,
                    description="Retrieve the complete span execution tree for a distributed trace.",
                    parameters=GetTraceArgs.model_json_schema(),
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name=ToolName.SEARCH_RUNBOOKS.value,
                    description="Search operational runbooks and troubleshooting guides by semantic query.",
                    parameters=SearchRunbooksArgs.model_json_schema(),
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name=ToolName.GET_RELATED_INCIDENTS.value,
                    description="Retrieve historical resolved incidents that share the same error signature hash.",
                    parameters=GetRelatedIncidentsArgs.model_json_schema(),
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name=ToolName.GET_SERVICE_DEPENDENCIES.value,
                    description="Query service topology to find upstream callers and downstream dependencies.",
                    parameters=GetServiceDependenciesArgs.model_json_schema(),
                ),
            ),
        ]

    async def search_logs(self, args: SearchLogsArgs) -> SearchLogsResult:
        index = ESIndexPrefix.LOGS.for_tenant(self.tenant_id)
        must_clauses: list[dict[str, object]] = [
            {
                "multi_match": {
                    "query": args.query,
                    "fields": [
                        "message^3",
                        "error.error_message^3",
                        "error.error_type^2",
                    ],
                }
            }
        ]
        if args.service:
            must_clauses.append({"term": {"context.service": args.service}})

        body = {"query": {"bool": {"must": must_clauses}}, "size": args.limit}

        try:
            async with asyncio.timeout(self.timeout):
                res = await self.es.search(index=index, body=body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_logs error: %s", exc)
            return SearchLogsResult(count=0, logs=[])

        data = _extract_es_dict(res)
        hits = data.get("hits", {}).get("hits", [])
        logs = [
            cast(dict[str, object], h.get("_source", {}))
            for h in hits
            if isinstance(h, dict)
        ]
        return SearchLogsResult(count=len(logs), logs=logs)

    async def get_trace(self, args: GetTraceArgs) -> GetTraceResult:
        index = ESIndexPrefix.LOGS.for_tenant(self.tenant_id)
        body = {
            "query": {"term": {"trace.trace_id": args.trace_id}},
            "sort": [{"timestamp": {"order": "asc"}}],
            "size": 50,
        }

        try:
            async with asyncio.timeout(self.timeout):
                res = await self.es.search(index=index, body=body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_trace error: %s", exc)
            return GetTraceResult(trace_id=args.trace_id, spans=[])

        data = _extract_es_dict(res)
        hits = data.get("hits", {}).get("hits", [])
        spans = [
            cast(dict[str, object], h.get("_source", {}))
            for h in hits
            if isinstance(h, dict)
        ]
        return GetTraceResult(trace_id=args.trace_id, spans=spans)

    async def search_runbooks(self, args: SearchRunbooksArgs) -> SearchRunbooksResult:
        if self.runbooks is None:
            return SearchRunbooksResult(runbooks=[])
        try:
            async with asyncio.timeout(self.timeout):
                results = await self.runbooks.search_runbooks(
                    tenant_id=self.tenant_id, query=args.query, service=args.service
                )
                return SearchRunbooksResult(runbooks=results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_runbooks error: %s", exc)
            return SearchRunbooksResult(runbooks=[])

    async def get_related_incidents(
        self, args: GetRelatedIncidentsArgs
    ) -> GetRelatedIncidentsResult:
        try:
            async with asyncio.timeout(self.timeout):
                # Search database for incidents with matching trigger_signature
                incidents = await self.db.list_incidents(tenant_id=self.tenant_id)
                matched = [
                    {
                        "incident_id": inc.incident_id,
                        "title": inc.title,
                        "trigger_service": inc.trigger_service,
                        "status": inc.status.value,
                        "severity": inc.severity.value,
                    }
                    for inc in incidents
                    if inc.trigger_signature == args.signature_hash
                ]
                return GetRelatedIncidentsResult(
                    incidents=cast(list[dict[str, object]], matched)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_related_incidents error: %s", exc)
            return GetRelatedIncidentsResult(incidents=[])

    async def get_service_dependencies(
        self, args: GetServiceDependenciesArgs
    ) -> GetServiceDependenciesResult:
        try:
            async with asyncio.timeout(self.timeout):
                deps = await self.db.get_dependencies(self.tenant_id)
                downstream = [
                    d.target_service for d in deps if d.source_service == args.service
                ]
                upstream = [
                    d.source_service for d in deps if d.target_service == args.service
                ]
                return GetServiceDependenciesResult(
                    service=args.service,
                    upstream_callers=upstream,
                    downstream_dependencies=downstream,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_service_dependencies error: %s", exc)
            return GetServiceDependenciesResult(
                service=args.service,
                upstream_callers=[],
                downstream_dependencies=[],
            )

    async def execute_tool_by_name(
        self, name: str, arguments_json: str
    ) -> dict[str, object]:
        try:
            parsed_args = json.loads(arguments_json) if arguments_json else {}
        except (json.JSONDecodeError, TypeError):
            parsed_args = {}

        try:
            tool_name = ToolName(name)
        except ValueError:
            return {"error": f"Unknown tool '{name}'"}

        if tool_name == ToolName.SEARCH_LOGS:
            res = await self.search_logs(SearchLogsArgs.model_validate(parsed_args))
            return res.model_dump()
        if tool_name == ToolName.GET_TRACE:
            res = await self.get_trace(GetTraceArgs.model_validate(parsed_args))
            return res.model_dump()
        if tool_name == ToolName.SEARCH_RUNBOOKS:
            res = await self.search_runbooks(
                SearchRunbooksArgs.model_validate(parsed_args)
            )
            return res.model_dump()
        if tool_name == ToolName.GET_RELATED_INCIDENTS:
            res = await self.get_related_incidents(
                GetRelatedIncidentsArgs.model_validate(parsed_args)
            )
            return res.model_dump()
        if tool_name == ToolName.GET_SERVICE_DEPENDENCIES:
            res = await self.get_service_dependencies(
                GetServiceDependenciesArgs.model_validate(parsed_args)
            )
            return res.model_dump()

        return {"error": f"Unknown tool '{name}'"}
