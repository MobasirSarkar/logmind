import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.log import RawLogPayload
from correlation.db import DatabaseManager
from correlation.detector import SpikeDetector
from correlation.graph import DependencyGraph
from correlation.log_store import ESLogStore, LogStore
from correlation.models import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
)
from correlation.trace_sequencer import TraceSequencer

logger = logging.getLogger("uvicorn.error")


class CorrelationEngine:
    def __init__(
        self,
        es_service: Any,
        db_manager: DatabaseManager,
        log_store: LogStore | None = None,
        detector: SpikeDetector | None = None,
        sequencer: TraceSequencer | None = None,
        graph: DependencyGraph | None = None,
    ):
        self.es = es_service
        self.db = db_manager
        self.log_store = log_store or ESLogStore(es_service)
        self.detector = detector or SpikeDetector(log_store=self.log_store)
        self.sequencer = sequencer or TraceSequencer()
        self.graph = graph or DependencyGraph()

    async def correlate_logs(
        self, tenant_id: str, logs: list[RawLogPayload]
    ) -> list[Incident]:
        if not logs:
            return []

        # 1. Ensure dependency graph is loaded
        deps = await self.db.get_dependencies(tenant_id)
        self.graph.load_dependencies(deps)

        # 2. Fetch currently active incidents for duplicate suppression
        active_incidents = await self.db.list_incidents(
            tenant_id=tenant_id, status=IncidentStatus.DETECTED
        )
        active_investigating = await self.db.list_incidents(
            tenant_id=tenant_id, status=IncidentStatus.INVESTIGATING
        )
        all_active = active_incidents + active_investigating

        # 3. Group logs by trace_id (or a fallback bucket if trace_id is missing)
        traces: dict[str, list[RawLogPayload]] = {}
        for log in logs:
            trace = log.get("trace")
            trace_id = (
                str(trace.get("trace_id"))
                if isinstance(trace, dict) and trace.get("trace_id")
                else f"untraced-{uuid.uuid4().hex[:8]}"
            )
            traces.setdefault(trace_id, []).append(log)

        resulting_incidents: list[Incident] = []

        for trace_id, trace_logs in traces.items():
            temp_inc_id = str(uuid.uuid4())
            initial_event, cascading_events = self.sequencer.sequence_trace(
                temp_inc_id, trace_logs
            )

            root_service = initial_event.service
            affected_services = list(
                {initial_event.service} | {e.service for e in cascading_events}
            )

            # Check if an active downstream incident exists
            matched_downstream = self.graph.find_active_downstream_incident(
                tenant_id=tenant_id,
                service=root_service,
                active_incidents=all_active,
            )

            if matched_downstream is not None:
                # Merge into existing incident
                for ev in [initial_event, *cascading_events]:
                    ev.incident_id = matched_downstream.incident_id
                matched_downstream.events.extend([initial_event, *cascading_events])
                for s in affected_services:
                    if s not in matched_downstream.affected_services:
                        matched_downstream.affected_services.append(s)

                saved = await self.db.save_incident(matched_downstream)
                resulting_incidents.append(saved)
            else:
                title = f"Outage in {root_service}: {initial_event.error_signature or initial_event.message[:60]}"
                new_incident = Incident(
                    incident_id=temp_inc_id,
                    tenant_id=tenant_id,
                    title=title,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.DETECTED,
                    started_at=initial_event.timestamp,
                    trigger_service=root_service,
                    trigger_signature=initial_event.error_signature,
                    affected_services=affected_services,
                    events=[initial_event, *cascading_events],
                    metadata={"initial_trace_id": trace_id},
                )
                saved = await self.db.save_incident(new_incident)
                all_active.append(saved)
                resulting_incidents.append(saved)

        return resulting_incidents

    async def evaluate_tenant(
        self,
        tenant_id: str,
        lookback_seconds: int = 60,
        min_error_count: int | None = None,
    ) -> list[Incident]:
        now = datetime.now(UTC)
        start_time = now - timedelta(seconds=lookback_seconds)

        services = await self.log_store.get_active_services(tenant_id, start_time, now)
        if not services:
            return []

        spiked_services: list[str] = []
        for s in services:
            alerts = await self.detector.evaluate_service(
                tenant_id,
                s,
                now=now,
                lookback_seconds=lookback_seconds,
                min_error_count=min_error_count,
            )
            if alerts:
                spiked_services.append(s)
        if not spiked_services:
            return []

        raw_logs = await self.log_store.get_error_logs(
            tenant_id, spiked_services, start_time, now
        )
        return await self.correlate_logs(tenant_id, raw_logs)
