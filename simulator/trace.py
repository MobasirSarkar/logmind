import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.log import RawLogPayload
from simulator.models import ServiceName


class TraceGenerator:
    def new_trace_id(self) -> str:
        return str(uuid.uuid4())

    def new_span_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def create_log_entry(
        self,
        tenant_id: str,
        service: ServiceName,
        timestamp: datetime,
        level: str,
        message: str,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        http_method: str | None = None,
        http_path: str | None = None,
        http_status: int | None = None,
        error: dict[str, Any] | None = None,
    ) -> RawLogPayload:
        log: RawLogPayload = {
            "timestamp": timestamp.isoformat(),
            "level": level,
            "message": message,
            "context": {
                "tenant_id": tenant_id,
                "service": service.value,
                "environment": "production",
            },
            "trace": {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            },
        }
        if http_method and http_path and http_status:
            log["http"] = {
                "method": http_method,
                "path": http_path,
                "status_code": http_status,
            }
        if error:
            log["error"] = error
        return log

    def generate_steady_state_trace(
        self, tenant_id: str, base_time: datetime | None = None
    ) -> list[RawLogPayload]:
        t = base_time or datetime.now(UTC)
        trace_id = self.new_trace_id()

        root_span_id = self.new_span_id()
        auth_span_id = self.new_span_id()
        order_span_id = self.new_span_id()
        payment_span_id = self.new_span_id()
        notify_span_id = self.new_span_id()

        logs: list[RawLogPayload] = []

        # 1. API Gateway ingress
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.API_GATEWAY,
                timestamp=t,
                level="INFO",
                message="Incoming request POST /api/v1/orders",
                trace_id=trace_id,
                span_id=root_span_id,
                parent_span_id=None,
                http_method="POST",
                http_path="/api/v1/orders",
                http_status=200,
            )
        )

        # 2. Auth Service session verification
        t += timedelta(milliseconds=8)
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.AUTH_SERVICE,
                timestamp=t,
                level="INFO",
                message="Session token validated successfully",
                trace_id=trace_id,
                span_id=auth_span_id,
                parent_span_id=root_span_id,
                http_method="GET",
                http_path="/auth/verify",
                http_status=200,
            )
        )

        # 3. Order Service processing
        t += timedelta(milliseconds=12)
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.ORDER_SERVICE,
                timestamp=t,
                level="INFO",
                message="Order entity initialized",
                trace_id=trace_id,
                span_id=order_span_id,
                parent_span_id=root_span_id,
                http_method="POST",
                http_path="/orders",
                http_status=200,
            )
        )

        # 4. Payment Service charge
        t += timedelta(milliseconds=25)
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.PAYMENT_SERVICE,
                timestamp=t,
                level="INFO",
                message="Payment charge approved by upstream gateway",
                trace_id=trace_id,
                span_id=payment_span_id,
                parent_span_id=order_span_id,
                http_method="POST",
                http_path="/charges",
                http_status=200,
            )
        )

        # 5. Notification Service dispatch
        t += timedelta(milliseconds=15)
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.NOTIFICATION_SERVICE,
                timestamp=t,
                level="INFO",
                message="Order confirmation notification sent",
                trace_id=trace_id,
                span_id=notify_span_id,
                parent_span_id=order_span_id,
                http_method="POST",
                http_path="/notifications",
                http_status=200,
            )
        )

        # 6. API Gateway egress completion
        t += timedelta(milliseconds=10)
        logs.append(
            self.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.API_GATEWAY,
                timestamp=t,
                level="INFO",
                message="Request completed with status 200 OK",
                trace_id=trace_id,
                span_id=root_span_id,
                parent_span_id=None,
                http_method="POST",
                http_path="/api/v1/orders",
                http_status=200,
            )
        )

        return logs
