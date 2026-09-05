import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.pool import StaticPool

from app.config import settings
from investigation.models import (
    EvidenceItem,
    EvidenceType,
    InvestigationReport,
    InvestigationStatus,
    InvestigationStep,
    ToolName,
)


class Base(DeclarativeBase):
    pass


class InvestigationReportORM(Base):
    __tablename__ = "investigation_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suspected_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    affected_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime] = mapped_column(nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    evidence: Mapped[list["EvidenceItemORM"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    steps: Mapped[list["InvestigationStepORM"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="InvestigationStepORM.step_number",
        lazy="selectin",
    )


class EvidenceItemORM(Base):
    __tablename__ = "investigation_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)

    report: Mapped[InvestigationReportORM] = relationship(back_populates="evidence")


class InvestigationStepORM(Base):
    __tablename__ = "investigation_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_input: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    tool_output: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    report: Mapped[InvestigationReportORM] = relationship(back_populates="steps")


class InvestigationDatabaseManager:
    def __init__(self, database_url: str | None = None):
        self.url = database_url or settings.DATABASE_URL
        if ":memory:" in self.url:
            self.engine: AsyncEngine = create_async_engine(
                self.url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine: AsyncEngine = create_async_engine(self.url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def ensure_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def save_report(self, report: InvestigationReport) -> InvestigationReport:
        async with self.session_factory() as session:
            stmt = select(InvestigationReportORM).where(InvestigationReportORM.id == report.investigation_id)
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

    async def get_report_by_incident(self, incident_id: str) -> InvestigationReport | None:
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
            stmt = select(InvestigationReportORM).where(InvestigationReportORM.id == investigation_id)
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
