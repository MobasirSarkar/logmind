from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.models.log import RawLogPayload
from simulator.models import ScenarioRunRecord, ScenarioType, ServiceName
from simulator.trace import TraceGenerator

_tracer = TraceGenerator()

type ScenarioResult = tuple[list[RawLogPayload], ScenarioRunRecord]
type ScenarioGeneratorFn = Callable[..., ScenarioResult]


def generate_payment_timeout_scenario(
    tenant_id: str, base_time: datetime | None = None
) -> ScenarioResult:
    t = base_time or datetime.now(UTC)
    started_at = t
    trace_id = _tracer.new_trace_id()

    root_span = _tracer.new_span_id()
    auth_span = _tracer.new_span_id()
    order_span = _tracer.new_span_id()
    payment_span = _tracer.new_span_id()

    logs: list[RawLogPayload] = []

    # 1. Gateway ingress
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="INFO",
            message="Incoming checkout request POST /api/v1/orders",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="POST",
            http_path="/api/v1/orders",
            http_status=200,
        )
    )

    # 2. Auth verifies session
    t += timedelta(milliseconds=10)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.AUTH_SERVICE,
            timestamp=t,
            level="INFO",
            message="User session verified",
            trace_id=trace_id,
            span_id=auth_span,
            parent_span_id=root_span,
            http_method="GET",
            http_path="/auth/verify",
            http_status=200,
        )
    )

    # 3. Order coordinates transaction
    t += timedelta(milliseconds=15)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.ORDER_SERVICE,
            timestamp=t,
            level="INFO",
            message="Order pending payment authorization",
            trace_id=trace_id,
            span_id=order_span,
            parent_span_id=root_span,
            http_method="POST",
            http_path="/orders",
            http_status=200,
        )
    )

    # 4. Payment times out (Root Cause)
    t += timedelta(milliseconds=8000)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.PAYMENT_SERVICE,
            timestamp=t,
            level="ERROR",
            message="Stripe upstream timed out after 8000ms",
            trace_id=trace_id,
            span_id=payment_span,
            parent_span_id=order_span,
            http_method="POST",
            http_path="/charges",
            http_status=504,
            error={
                "error_type": "GatewayTimeoutException",
                "error_message": "Stripe upstream timed out after 8000ms",
                "error_signature": "Stripe upstream timed out after 8000ms",
            },
        )
    )

    # 5. Order catches failure and emits cascading error
    t += timedelta(milliseconds=20)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.ORDER_SERVICE,
            timestamp=t,
            level="ERROR",
            message="Payment authorization failed for order",
            trace_id=trace_id,
            span_id=order_span,
            parent_span_id=root_span,
            http_method="POST",
            http_path="/orders",
            http_status=502,
            error={
                "error_type": "OrderProcessingError",
                "error_message": "Payment authorization failed for order",
                "error_signature": "Payment authorization failed for order",
            },
        )
    )

    # 6. Gateway emits BadGateway 500
    t += timedelta(milliseconds=15)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="ERROR",
            message="Downstream order-service returned 502",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="POST",
            http_path="/api/v1/orders",
            http_status=500,
            error={
                "error_type": "BadGateway",
                "error_message": "Downstream order-service returned 502",
                "error_signature": "Downstream order-service returned 502",
            },
        )
    )

    record = ScenarioRunRecord(
        scenario_type=ScenarioType.PAYMENT_TIMEOUT,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=t,
        root_cause_service=ServiceName.PAYMENT_SERVICE,
        root_cause_error="GatewayTimeoutException: Stripe upstream timed out after 8000ms",
        affected_services=[
            ServiceName.PAYMENT_SERVICE,
            ServiceName.ORDER_SERVICE,
            ServiceName.API_GATEWAY,
        ],
        expected_diagnosis="Payment provider timeout in payment-service caused cascading order creation failures in order-service and HTTP 500 responses at api-gateway.",
        total_logs_emitted=len(logs),
        scenario_metadata={"timeout_ms": 8000, "provider": "Stripe"},
    )
    return logs, record


def generate_db_pool_scenario(
    tenant_id: str, base_time: datetime | None = None
) -> ScenarioResult:
    t = base_time or datetime.now(UTC)
    started_at = t
    trace_id = _tracer.new_trace_id()

    root_span = _tracer.new_span_id()
    order_span = _tracer.new_span_id()

    logs: list[RawLogPayload] = []

    # 1. Gateway ingress
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="INFO",
            message="Incoming order request POST /api/v1/orders",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="POST",
            http_path="/api/v1/orders",
            http_status=200,
        )
    )

    # 2. Order service hits connection pool threshold
    t += timedelta(milliseconds=25)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.ORDER_SERVICE,
            timestamp=t,
            level="ERROR",
            message="ConnectionPoolExhausted: HikariPool-1 - Connection is not available, request timed out after 30000ms",
            trace_id=trace_id,
            span_id=order_span,
            parent_span_id=root_span,
            http_method="POST",
            http_path="/orders",
            http_status=503,
            error={
                "error_type": "ConnectionPoolExhausted",
                "error_message": "HikariPool-1 - Connection is not available, request timed out after 30000ms",
                "error_signature": "HikariPool-1 - Connection is not available, request timed out after 30000ms",
            },
        )
    )

    # 3. Gateway logs 503 service unavailable
    t += timedelta(milliseconds=10)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="ERROR",
            message="ServiceUnavailable: Downstream order-service returned 503",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="POST",
            http_path="/api/v1/orders",
            http_status=503,
            error={
                "error_type": "ServiceUnavailable",
                "error_message": "Downstream order-service returned 503",
                "error_signature": "Downstream order-service returned 503",
            },
        )
    )

    record = ScenarioRunRecord(
        scenario_type=ScenarioType.DB_POOL_EXHAUSTION,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=t,
        root_cause_service=ServiceName.ORDER_SERVICE,
        root_cause_error="ConnectionPoolExhausted: HikariPool-1 - Connection is not available, request timed out after 30000ms",
        affected_services=[ServiceName.ORDER_SERVICE, ServiceName.API_GATEWAY],
        expected_diagnosis="Database connection pool exhaustion in order-service caused connection timeouts and downstream request drops.",
        total_logs_emitted=len(logs),
        scenario_metadata={"pool_name": "HikariPool-1", "timeout_ms": 30000},
    )
    return logs, record


def generate_auth_failure_scenario(
    tenant_id: str, base_time: datetime | None = None
) -> ScenarioResult:
    t = base_time or datetime.now(UTC)
    started_at = t
    trace_id = _tracer.new_trace_id()

    root_span = _tracer.new_span_id()
    auth_span = _tracer.new_span_id()

    logs: list[RawLogPayload] = []

    # 1. Gateway receives request
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="INFO",
            message="Incoming request GET /api/v1/user/profile",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="GET",
            http_path="/api/v1/user/profile",
            http_status=200,
        )
    )

    # 2. Auth service Redis session cache crashed
    t += timedelta(milliseconds=15)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.AUTH_SERVICE,
            timestamp=t,
            level="FATAL",
            message="RedisConnectionRefused: Error connecting to session cache at redis:6379",
            trace_id=trace_id,
            span_id=auth_span,
            parent_span_id=root_span,
            http_method="GET",
            http_path="/auth/verify",
            http_status=500,
            error={
                "error_type": "RedisConnectionRefused",
                "error_message": "Error connecting to session cache at redis:6379",
                "error_signature": "Error connecting to session cache at redis:6379",
            },
        )
    )

    # 3. Gateway rejects traffic with 401
    t += timedelta(milliseconds=8)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="ERROR",
            message="Unauthorized: Session verification failed due to auth-service outage",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="GET",
            http_path="/api/v1/user/profile",
            http_status=401,
            error={
                "error_type": "Unauthorized",
                "error_message": "Session verification failed due to auth-service outage",
                "error_signature": "Session verification failed due to auth-service outage",
            },
        )
    )

    record = ScenarioRunRecord(
        scenario_type=ScenarioType.AUTH_DEPENDENCY_FAILURE,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=t,
        root_cause_service=ServiceName.AUTH_SERVICE,
        root_cause_error="RedisConnectionRefused: Error connecting to session cache at redis:6379",
        affected_services=[ServiceName.AUTH_SERVICE, ServiceName.API_GATEWAY],
        expected_diagnosis="Session cache connectivity failure in auth-service prevented authentication token verification, causing gateway request rejections.",
        total_logs_emitted=len(logs),
        scenario_metadata={"target": "redis:6379", "subsystem": "session-cache"},
    )
    return logs, record


def generate_retry_storm_scenario(
    tenant_id: str, base_time: datetime | None = None
) -> ScenarioResult:
    t = base_time or datetime.now(UTC)
    started_at = t
    trace_id = _tracer.new_trace_id()

    root_span = _tracer.new_span_id()
    order_span = _tracer.new_span_id()
    notify_span = _tracer.new_span_id()

    logs: list[RawLogPayload] = []

    # 1. Gateway & Order initial dispatch
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.API_GATEWAY,
            timestamp=t,
            level="INFO",
            message="Checkout completed, dispatching notification",
            trace_id=trace_id,
            span_id=root_span,
            parent_span_id=None,
            http_method="POST",
            http_path="/api/v1/orders",
            http_status=200,
        )
    )

    # 2. Notification webhook transient timeout
    t += timedelta(milliseconds=20)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.NOTIFICATION_SERVICE,
            timestamp=t,
            level="ERROR",
            message="WebhookTimeoutException: Webhook delivery timed out after 500ms",
            trace_id=trace_id,
            span_id=notify_span,
            parent_span_id=order_span,
            http_method="POST",
            http_path="/notifications",
            http_status=504,
            error={
                "error_type": "WebhookTimeoutException",
                "error_message": "Webhook delivery timed out after 500ms",
                "error_signature": "Webhook delivery timed out after 500ms",
            },
        )
    )

    # 3. Order executes 5 aggressive unjittered retries
    for attempt in range(1, 6):
        t += timedelta(milliseconds=10)
        logs.append(
            _tracer.create_log_entry(
                tenant_id=tenant_id,
                service=ServiceName.ORDER_SERVICE,
                timestamp=t,
                level="WARN",
                message=f"RetryAttempt: Notification delivery retry {attempt}/5 for order",
                trace_id=trace_id,
                span_id=order_span,
                parent_span_id=root_span,
                http_method="POST",
                http_path="/notifications/retry",
                http_status=504,
            )
        )

    # 4. Notification thread pool saturated
    t += timedelta(milliseconds=30)
    logs.append(
        _tracer.create_log_entry(
            tenant_id=tenant_id,
            service=ServiceName.NOTIFICATION_SERVICE,
            timestamp=t,
            level="ERROR",
            message="ThreadSaturationError: Thread pool exhausted (500/500 active workers)",
            trace_id=trace_id,
            span_id=notify_span,
            parent_span_id=order_span,
            http_method="POST",
            http_path="/notifications",
            http_status=503,
            error={
                "error_type": "ThreadSaturationError",
                "error_message": "Thread pool exhausted (500/500 active workers)",
                "error_signature": "Thread pool exhausted (500/500 active workers)",
            },
        )
    )

    record = ScenarioRunRecord(
        scenario_type=ScenarioType.RETRY_STORM,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=t,
        root_cause_service=ServiceName.NOTIFICATION_SERVICE,
        root_cause_error="WebhookTimeoutException: Webhook delivery timed out after 500ms",
        affected_services=[ServiceName.NOTIFICATION_SERVICE, ServiceName.ORDER_SERVICE],
        expected_diagnosis="Aggressive unjittered retries from order-service caused request amplification and thread saturation in notification-service following a transient timeout.",
        total_logs_emitted=len(logs),
        scenario_metadata={"max_retries": 5, "backoff": "none", "jitter": False},
    )
    return logs, record

SCENARIO_GENERATORS: dict[ScenarioType, ScenarioGeneratorFn] = {
    ScenarioType.PAYMENT_TIMEOUT: generate_payment_timeout_scenario,
    ScenarioType.DB_POOL_EXHAUSTION: generate_db_pool_scenario,
    ScenarioType.AUTH_DEPENDENCY_FAILURE: generate_auth_failure_scenario,
    ScenarioType.RETRY_STORM: generate_retry_storm_scenario,
}
