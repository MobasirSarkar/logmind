import asyncio
import json
import logging
from typing import Any, cast

from pydantic import BaseModel, Field

from app.constants import ESIndexPrefix
from investigation.client import ToolDefinition, ToolFunctionSpec

logger = logging.getLogger("uvicorn.error")


# --- Typed Input & Output Models for All Tools ---

class SearchLogsArgs(BaseModel):
    query: str
    service: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchLogsResult(BaseModel):
    count: int
    logs: list[dict[str, object]] = Field(default_factory=list)


class GetTraceArgs(BaseModel):
    trace_id: str


class GetTraceResult(BaseModel):
    trace_id: str
    spans: list[dict[str, object]] = Field(default_factory=list)


class SearchRunbooksArgs(BaseModel):
    query: str
    service: str | None = None


class SearchRunbooksResult(BaseModel):
    runbooks: list[dict[str, object]] = Field(default_factory=list)


class GetRelatedIncidentsArgs(BaseModel):
    signature_hash: str


class GetRelatedIncidentsResult(BaseModel):
    incidents: list[dict[str, object]] = Field(default_factory=list)


class GetServiceDependenciesArgs(BaseModel):
    service: str


class GetServiceDependenciesResult(BaseModel):
    service: str
    upstream_callers: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)


# --- Toolbox Implementation ---

class InvestigationToolbox:
    def __init__(
        self,
        es_service: Any,
        db_manager: Any,
        tenant_id: str,
        runbook_service: Any | None = None,
        timeout: float = 5.0,
    ):
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
                    name="search_logs",
                    description="Search logs in Elasticsearch using keywords, service filter, and time window.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query or error message"},
                            "service": {"type": "string", "description": "Optional service name to filter by"},
                            "limit": {"type": "integer", "description": "Maximum number of logs (1-50)", "default": 10},
                        },
                        "required": ["query"],
                    },
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name="get_trace",
                    description="Retrieve the complete span execution tree for a distributed trace.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "trace_id": {"type": "string", "description": "Trace UUID"},
                        },
                        "required": ["trace_id"],
                    },
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name="search_runbooks",
                    description="Search operational runbooks and troubleshooting guides by semantic query.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Error or symptom to look up"},
                            "service": {"type": "string", "description": "Optional service name"},
                        },
                        "required": ["query"],
                    },
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name="get_related_incidents",
                    description="Retrieve historical resolved incidents that share the same error signature hash.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "signature_hash": {"type": "string", "description": "Error signature hash"},
                        },
                        "required": ["signature_hash"],
                    },
                ),
            ),
            ToolDefinition(
                type="function",
                function=ToolFunctionSpec(
                    name="get_service_dependencies",
                    description="Query service topology to find upstream callers and downstream dependencies.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "service": {"type": "string", "description": "Service name"},
                        },
                        "required": ["service"],
                    },
                ),
            ),
        ]

    async def search_logs(self, args: SearchLogsArgs) -> SearchLogsResult:
        index = ESIndexPrefix.LOGS.for_tenant(self.tenant_id)
        must_clauses: list[dict[str, object]] = [
            {"multi_match": {"query": args.query, "fields": ["message^3", "error.error_message^3", "error.error_type^2"]}}
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

        hits = res.get("hits", {}).get("hits", []) if isinstance(res, dict) else []
        logs = [cast(dict[str, object], h.get("_source", {})) for h in hits if isinstance(h, dict)]
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

        hits = res.get("hits", {}).get("hits", []) if isinstance(res, dict) else []
        spans = [cast(dict[str, object], h.get("_source", {})) for h in hits if isinstance(h, dict)]
        return GetTraceResult(trace_id=args.trace_id, spans=spans)

    async def search_runbooks(self, args: SearchRunbooksArgs) -> SearchRunbooksResult:
        if self.runbooks is None:
            return SearchRunbooksResult(runbooks=[])
        try:
            async with asyncio.timeout(self.timeout):
                results = await self.runbooks.search_runbooks(
                    query=args.query, service=args.service
                )
                return SearchRunbooksResult(runbooks=results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_runbooks error: %s", exc)
            return SearchRunbooksResult(runbooks=[])

    async def get_related_incidents(self, args: GetRelatedIncidentsArgs) -> GetRelatedIncidentsResult:
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
                return GetRelatedIncidentsResult(incidents=cast(list[dict[str, object]], matched))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_related_incidents error: %s", exc)
            return GetRelatedIncidentsResult(incidents=[])

    async def get_service_dependencies(self, args: GetServiceDependenciesArgs) -> GetServiceDependenciesResult:
        try:
            async with asyncio.timeout(self.timeout):
                deps = await self.db.get_dependencies(self.tenant_id)
                downstream = [d.target_service for d in deps if d.source_service == args.service]
                upstream = [d.source_service for d in deps if d.target_service == args.service]
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

    async def execute_tool_by_name(self, name: str, arguments_json: str) -> dict[str, object]:
        try:
            parsed_args = json.loads(arguments_json) if arguments_json else {}
        except (json.JSONDecodeError, TypeError):
            parsed_args = {}

        if name == "search_logs":
            res = await self.search_logs(SearchLogsArgs.model_validate(parsed_args))
            return res.model_dump()
        if name == "get_trace":
            res = await self.get_trace(GetTraceArgs.model_validate(parsed_args))
            return res.model_dump()
        if name == "search_runbooks":
            res = await self.search_runbooks(SearchRunbooksArgs.model_validate(parsed_args))
            return res.model_dump()
        if name == "get_related_incidents":
            res = await self.get_related_incidents(GetRelatedIncidentsArgs.model_validate(parsed_args))
            return res.model_dump()
        if name == "get_service_dependencies":
            res = await self.get_service_dependencies(GetServiceDependenciesArgs.model_validate(parsed_args))
            return res.model_dump()

        return {"error": f"Unknown tool '{name}'"}
