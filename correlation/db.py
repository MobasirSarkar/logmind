from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, Datastore, get_datastore
from correlation.models import (
    DependencyType,
    EventType,
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentStatus,
    ServiceDependency,
)


class ServiceORM(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), default="production")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ServiceDependencyORM(Base):
    __tablename__ = "service_dependencies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), nullable=False)
    dependency_type: Mapped[str] = mapped_column(String(32), default=DependencyType.HTTP.value)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class IncidentORM(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=IncidentStatus.DETECTED.value, index=True)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    trigger_service: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    affected_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    events: Mapped[list["IncidentEventORM"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEventORM.timestamp",
        lazy="selectin",
    )


class IncidentEventORM(Base):
    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    error_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    log_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    incident: Mapped[IncidentORM] = relationship(back_populates="events")
class DatabaseManager:
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
    async def save_dependency(self, dep: ServiceDependency) -> ServiceDependency:
        async with self.session_factory() as session:
            stmt = select(ServiceDependencyORM).where(
                ServiceDependencyORM.tenant_id == dep.tenant_id,
                ServiceDependencyORM.source_service == dep.source_service,
                ServiceDependencyORM.target_service == dep.target_service,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.dependency_type = dep.dependency_type.value
            else:
                orm_obj = ServiceDependencyORM(
                    id=dep.dependency_id,
                    tenant_id=dep.tenant_id,
                    source_service=dep.source_service,
                    target_service=dep.target_service,
                    dependency_type=dep.dependency_type.value,
                )
                session.add(orm_obj)
            await session.commit()
            return dep

    async def get_dependencies(self, tenant_id: str) -> list[ServiceDependency]:
        async with self.session_factory() as session:
            stmt = select(ServiceDependencyORM).where(ServiceDependencyORM.tenant_id == tenant_id)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                ServiceDependency(
                    dependency_id=r.id,
                    tenant_id=r.tenant_id,
                    source_service=r.source_service,
                    target_service=r.target_service,
                    dependency_type=DependencyType(r.dependency_type),
                )
                for r in rows
            ]

    async def save_incident(self, incident: Incident) -> Incident:
        async with self.session_factory() as session:
            stmt = select(IncidentORM).where(IncidentORM.id == incident.incident_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.title = incident.title
                existing.severity = incident.severity.value
                existing.status = incident.status.value
                existing.started_at = incident.started_at
                existing.resolved_at = incident.resolved_at
                existing.trigger_service = incident.trigger_service
                existing.trigger_signature = incident.trigger_signature
                existing.affected_services = incident.affected_services
                existing.metadata_json = incident.metadata
                # Add any new events
                existing_event_ids = {e.id for e in existing.events}
                for ev in incident.events:
                    if ev.event_id not in existing_event_ids:
                        existing.events.append(
                            IncidentEventORM(
                                id=ev.event_id,
                                incident_id=incident.incident_id,
                                timestamp=ev.timestamp,
                                service=ev.service,
                                event_type=ev.event_type.value,
                                error_signature=ev.error_signature,
                                trace_id=ev.trace_id,
                                log_id=ev.log_id,
                                message=ev.message,
                            )
                        )
            else:
                orm_incident = IncidentORM(
                    id=incident.incident_id,
                    tenant_id=incident.tenant_id,
                    title=incident.title,
                    severity=incident.severity.value,
                    status=incident.status.value,
                    started_at=incident.started_at,
                    resolved_at=incident.resolved_at,
                    trigger_service=incident.trigger_service,
                    trigger_signature=incident.trigger_signature,
                    affected_services=incident.affected_services,
                    metadata_json=incident.metadata,
                )
                for ev in incident.events:
                    orm_incident.events.append(
                        IncidentEventORM(
                            id=ev.event_id,
                            incident_id=incident.incident_id,
                            timestamp=ev.timestamp,
                            service=ev.service,
                            event_type=ev.event_type.value,
                            error_signature=ev.error_signature,
                            trace_id=ev.trace_id,
                            log_id=ev.log_id,
                            message=ev.message,
                        )
                    )
                session.add(orm_incident)
            await session.commit()
            return incident

    async def get_incident(self, incident_id: str) -> Incident | None:
        async with self.session_factory() as session:
            stmt = select(IncidentORM).where(IncidentORM.id == incident_id)
            result = await session.execute(stmt)
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return self._to_incident_domain(r)

    async def list_incidents(
        self, tenant_id: str, status: IncidentStatus | None = None
    ) -> list[Incident]:
        async with self.session_factory() as session:
            stmt = select(IncidentORM).where(IncidentORM.tenant_id == tenant_id)
            if status is not None:
                stmt = stmt.where(IncidentORM.status == status.value)
            stmt = stmt.order_by(IncidentORM.started_at.desc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_incident_domain(r) for r in rows]

    async def update_incident_status(
        self, incident_id: str, status: IncidentStatus
    ) -> Incident | None:
        async with self.session_factory() as session:
            stmt = select(IncidentORM).where(IncidentORM.id == incident_id)
            result = await session.execute(stmt)
            r = result.scalar_one_or_none()
            if r is None:
                return None
            r.status = status.value
            if status == IncidentStatus.RESOLVED and r.resolved_at is None:
                r.resolved_at = datetime.now(UTC)
            await session.commit()
            return self._to_incident_domain(r)

    def _to_incident_domain(self, r: IncidentORM) -> Incident:
        events = [
            IncidentEvent(
                event_id=e.id,
                incident_id=e.incident_id,
                timestamp=e.timestamp,
                service=e.service,
                event_type=EventType(e.event_type),
                error_signature=e.error_signature,
                trace_id=e.trace_id,
                log_id=e.log_id,
                message=e.message,
            )
            for e in r.events
        ]
        return Incident(
            incident_id=r.id,
            tenant_id=r.tenant_id,
            title=r.title,
            severity=IncidentSeverity(r.severity),
            status=IncidentStatus(r.status),
            started_at=r.started_at,
            resolved_at=r.resolved_at,
            trigger_service=r.trigger_service,
            trigger_signature=r.trigger_signature,
            affected_services=r.affected_services,
            events=events,
            metadata=r.metadata_json,
        )
