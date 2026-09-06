import uuid

from sqlalchemy import select

from app.db import Datastore, get_datastore
from investigation.models import (
    EvidenceItem,
    EvidenceItemORM,
    EvidenceType,
    InvestigationReport,
    InvestigationReportORM,
    InvestigationStatus,
    InvestigationStep,
    InvestigationStepORM,
    ToolName,
)

__all__ = [
    "EvidenceItemORM",
    "InvestigationDatabaseManager",
    "InvestigationReportORM",
    "InvestigationStepORM",
]


class InvestigationDatabaseManager:
    def __init__(
        self, database_url: str | None = None, datastore: Datastore | None = None
    ):
        if datastore is not None:
            self.datastore = datastore
        elif database_url is not None:
            self.datastore = Datastore(database_url)
        else:
            self.datastore = get_datastore()
        self.engine = self.datastore.engine
        self.session_factory = self.datastore.session_factory

    async def ensure_tables(self) -> None:
        await self.datastore.ensure_tables()

    async def close(self) -> None:
        await self.datastore.close()

    async def save_report(self, report: InvestigationReport) -> InvestigationReport:
        async with self.session_factory() as session:
            stmt = select(InvestigationReportORM).where(
                InvestigationReportORM.id == report.investigation_id
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.status = report.status.value
                existing.summary = report.summary
                existing.suspected_root_cause = report.suspected_root_cause
                existing.confidence_score = report.confidence_score
                existing.affected_services = report.affected_services
                existing.recommended_actions = report.recommended_actions
                existing.started_at = report.started_at
                existing.completed_at = report.completed_at
                existing.is_fallback = report.is_fallback
                existing.metadata_json = report.metadata
            else:
                orm_report = InvestigationReportORM(
                    id=report.investigation_id,
                    incident_id=report.incident_id,
                    status=report.status.value,
                    summary=report.summary,
                    suspected_root_cause=report.suspected_root_cause,
                    confidence_score=report.confidence_score,
                    affected_services=report.affected_services,
                    recommended_actions=report.recommended_actions,
                    started_at=report.started_at,
                    completed_at=report.completed_at,
                    is_fallback=report.is_fallback,
                    metadata_json=report.metadata,
                )
                for ev in report.evidence:
                    orm_report.evidence.append(
                        EvidenceItemORM(
                            id=str(uuid.uuid4()),
                            report_id=report.investigation_id,
                            evidence_type=ev.evidence_type.value,
                            reference_id=ev.reference_id,
                            service=ev.service,
                            timestamp=ev.timestamp,
                            excerpt=ev.excerpt,
                        )
                    )
                for st in report.steps:
                    orm_report.steps.append(
                        InvestigationStepORM(
                            id=str(uuid.uuid4()),
                            report_id=report.investigation_id,
                            step_number=st.step_number,
                            tool_name=st.tool_name.value,
                            tool_input=st.tool_input,
                            tool_output=st.tool_output,
                            duration_ms=st.duration_ms,
                        )
                    )
                session.add(orm_report)
            await session.commit()
            return report

    async def get_report_by_incident(
        self, incident_id: str
    ) -> InvestigationReport | None:
        async with self.session_factory() as session:
            stmt = (
                select(InvestigationReportORM)
                .where(InvestigationReportORM.incident_id == incident_id)
                .order_by(InvestigationReportORM.completed_at.desc())
            )
            result = await session.execute(stmt)
            r = result.scalars().first()
            if r is None:
                return None
            return self._to_domain(r)

    async def get_report(self, investigation_id: str) -> InvestigationReport | None:
        async with self.session_factory() as session:
            stmt = select(InvestigationReportORM).where(
                InvestigationReportORM.id == investigation_id
            )
            result = await session.execute(stmt)
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return self._to_domain(r)

    def _to_domain(self, r: InvestigationReportORM) -> InvestigationReport:
        evidence = [
            EvidenceItem(
                evidence_type=EvidenceType(e.evidence_type),
                reference_id=e.reference_id,
                service=e.service,
                timestamp=e.timestamp,
                excerpt=e.excerpt,
            )
            for e in r.evidence
        ]
        steps = [
            InvestigationStep(
                step_number=s.step_number,
                tool_name=ToolName(s.tool_name),
                tool_input=s.tool_input,
                tool_output=s.tool_output,
                duration_ms=s.duration_ms,
            )
            for s in r.steps
        ]
        return InvestigationReport(
            investigation_id=r.id,
            incident_id=r.incident_id,
            status=InvestigationStatus(r.status),
            summary=r.summary,
            suspected_root_cause=r.suspected_root_cause,
            confidence_score=r.confidence_score,
            affected_services=r.affected_services,
            evidence=evidence,
            recommended_actions=r.recommended_actions,
            steps=steps,
            started_at=r.started_at,
            completed_at=r.completed_at,
            is_fallback=r.is_fallback,
            metadata=r.metadata_json,
        )
