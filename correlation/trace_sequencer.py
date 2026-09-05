import uuid
from datetime import UTC, datetime

from app.models.log import RawLogPayload
from correlation.models import EventType, IncidentEvent


class TraceSequencer:
    def _parse_timestamp(self, ts_raw: object) -> datetime:
        if isinstance(ts_raw, datetime):
            return ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
        if isinstance(ts_raw, str):
            try:
                dt = datetime.fromisoformat(ts_raw)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                pass
        return datetime.now(UTC)

    def sequence_trace(
        self, incident_id: str, logs: list[RawLogPayload]
    ) -> tuple[IncidentEvent, list[IncidentEvent]]:
        if not logs:
            now = datetime.now(UTC)
            dummy = IncidentEvent(
                incident_id=incident_id,
                timestamp=now,
                service="unknown",
                event_type=EventType.INITIAL_ERROR,
                message="No logs provided",
            )
            return dummy, []

        # Filter to error logs
        error_logs: list[RawLogPayload] = []
        for log in logs:
            level = str(log.get("level", "")).upper()
            http = log.get("http")
            status_code = 0
            if isinstance(http, dict):
                try:
                    status_code = int(str(http.get("status_code", 0)))
                except (ValueError, TypeError):
                    pass
            if level in ("ERROR", "FATAL") or status_code >= 500:
                error_logs.append(log)

        if not error_logs:
            error_logs = logs

        # Sort chronologically
        sorted_logs = sorted(
            error_logs,
            key=lambda l: self._parse_timestamp(l.get("timestamp")),
        )

        first = sorted_logs[0]
        first_ctx = first.get("context")
        first_service = (
            str(first_ctx.get("service", "unknown"))
            if isinstance(first_ctx, dict)
            else "unknown"
        )
        first_trace = first.get("trace")
        first_trace_id = (
            str(first_trace.get("trace_id"))
            if isinstance(first_trace, dict) and first_trace.get("trace_id")
            else None
        )
        first_error = first.get("error")
        first_sig = (
            str(first_error.get("error_signature") or first_error.get("error_type"))
            if isinstance(first_error, dict)
            else None
        )

        initial_event = IncidentEvent(
            event_id=str(uuid.uuid4()),
            incident_id=incident_id,
            timestamp=self._parse_timestamp(first.get("timestamp")),
            service=first_service,
            event_type=EventType.INITIAL_ERROR,
            error_signature=first_sig,
            trace_id=first_trace_id,
            log_id=str(first.get("id")) if first.get("id") else None,
            message=str(first.get("message", "")),
        )

        cascading_events: list[IncidentEvent] = []
        for l in sorted_logs[1:]:
            ctx = l.get("context")
            service = (
                str(ctx.get("service", "unknown"))
                if isinstance(ctx, dict)
                else "unknown"
            )
            trace = l.get("trace")
            trace_id = (
                str(trace.get("trace_id"))
                if isinstance(trace, dict) and trace.get("trace_id")
                else None
            )
            err = l.get("error")
            sig = (
                str(err.get("error_signature") or err.get("error_type"))
                if isinstance(err, dict)
                else None
            )

            cascading_events.append(
                IncidentEvent(
                    event_id=str(uuid.uuid4()),
                    incident_id=incident_id,
                    timestamp=self._parse_timestamp(l.get("timestamp")),
                    service=service,
                    event_type=EventType.CASCADING_ERROR,
                    error_signature=sig,
                    trace_id=trace_id,
                    log_id=str(l.get("id")) if l.get("id") else None,
                    message=str(l.get("message", "")),
                )
            )

        return initial_event, cascading_events
