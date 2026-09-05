from collections import deque
from datetime import UTC, datetime

from correlation.models import Incident, IncidentStatus, ServiceDependency


class DependencyGraph:
    def __init__(self) -> None:
        # tenant_id -> source_service -> set of target_services
        self._adj: dict[str, dict[str, set[str]]] = {}

    def add_dependency(self, dep: ServiceDependency) -> None:
        tenant_adj = self._adj.setdefault(dep.tenant_id, {})
        targets = tenant_adj.setdefault(dep.source_service, set())
        targets.add(dep.target_service)

    def load_dependencies(self, deps: list[ServiceDependency]) -> None:
        for dep in deps:
            self.add_dependency(dep)

    def get_downstream_services(self, tenant_id: str, service: str) -> set[str]:
        tenant_adj = self._adj.get(tenant_id, {})
        visited: set[str] = set()
        queue: deque[str] = deque([service])

        while queue:
            curr = queue.popleft()
            for target in tenant_adj.get(curr, set()):
                if target not in visited:
                    visited.add(target)
                    queue.append(target)

        return visited

    def find_active_downstream_incident(
        self,
        tenant_id: str,
        service: str,
        active_incidents: list[Incident],
        max_time_diff_seconds: int = 120,
        now: datetime | None = None,
    ) -> Incident | None:
        downstream = self.get_downstream_services(tenant_id, service)
        if not downstream:
            return None

        t = now or datetime.now(UTC)

        for inc in active_incidents:
            if inc.tenant_id != tenant_id:
                continue
            if inc.status not in (IncidentStatus.DETECTED, IncidentStatus.INVESTIGATING):
                continue

            # Check if root cause / trigger of the incident is in downstream services
            if inc.trigger_service in downstream:
                diff = abs((t - inc.started_at).total_seconds())
                if diff <= max_time_diff_seconds:
                    return inc

        return None
