from datetime import UTC, datetime

from correlation.models import EventType, Incident
from investigation.models import (
    EvidenceItem,
    EvidenceType,
    InvestigationReport,
    InvestigationStatus,
)


class DeterministicFallbackEngine:
    def generate_report(
        self, incident: Incident, error_reason: str = "LLM provider timeout"
    ) -> InvestigationReport:
        now = datetime.now(UTC)

        evidence_items: list[EvidenceItem] = []
        for ev in incident.events:
            if ev.event_type == EventType.INITIAL_ERROR:
                ref_id = ev.log_id or ev.event_id
                evidence_items.append(
                    EvidenceItem(
                        evidence_type=EvidenceType.LOG,
                        reference_id=ref_id,
                        service=ev.service,
                        timestamp=ev.timestamp,
                        excerpt=ev.message,
                    )
                )
                if ev.trace_id:
                    evidence_items.append(
                        EvidenceItem(
                            evidence_type=EvidenceType.TRACE,
                            reference_id=ev.trace_id,
                            service=ev.service,
                            timestamp=ev.timestamp,
                            excerpt=f"Distributed trace across {', '.join(incident.affected_services)}",
                        )
                    )
                break

        if not evidence_items and incident.events:
            first_ev = incident.events[0]
            evidence_items.append(
                EvidenceItem(
                    evidence_type=EvidenceType.LOG,
                    reference_id=first_ev.log_id or first_ev.event_id,
                    service=first_ev.service,
                    timestamp=first_ev.timestamp,
                    excerpt=first_ev.message,
                )
            )

        summary = (
            f"Deterministic engine isolated earliest abnormal event in {incident.trigger_service}."
        )
        suspected_root_cause = (
            f"Initial error occurred in {incident.trigger_service} with "
            f"{incident.trigger_signature or 'abnormal error cascade'}, "
            f"causing cascading failures in {', '.join(incident.affected_services)}."
        )

        recommended_actions = [
            f"Inspect {incident.trigger_service} logs and application telemetry around {incident.started_at.isoformat()}.",
            f"Verify network connectivity and dependency health for {incident.trigger_service}.",
            "Retry AI-assisted root cause analysis once LLM provider connectivity is restored.",
        ]

        return InvestigationReport(
            incident_id=incident.incident_id,
            status=InvestigationStatus.DEGRADED_FALLBACK,
            summary=summary,
            suspected_root_cause=suspected_root_cause,
            confidence_score=0.50,
            affected_services=incident.affected_services,
            evidence=evidence_items,
            recommended_actions=recommended_actions,
            steps=[],
            started_at=now,
            completed_at=now,
            is_fallback=True,
            metadata={"fallback_reason": error_reason},
        )
