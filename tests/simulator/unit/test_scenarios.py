from datetime import UTC, datetime
from typing import Any

from simulator.models import ScenarioType, ServiceName
from simulator.scenarios import (
    SCENARIO_GENERATORS,
    generate_auth_failure_scenario,
    generate_db_pool_scenario,
    generate_payment_timeout_scenario,
    generate_retry_storm_scenario,
)


def test_payment_timeout_scenario():
    now = datetime.now(UTC)
    logs, record = generate_payment_timeout_scenario(tenant_id="acme", base_time=now)

    assert record.scenario_type == ScenarioType.PAYMENT_TIMEOUT
    assert record.root_cause_service == ServiceName.PAYMENT_SERVICE
    assert "Stripe upstream timed out" in record.root_cause_error
    assert record.total_logs_emitted == len(logs)
    assert record.affected_services == [
        ServiceName.PAYMENT_SERVICE,
        ServiceName.ORDER_SERVICE,
        ServiceName.API_GATEWAY,
    ]

    # Verify trace consistency
    trace_ids = {log["trace"]["trace_id"] for log in logs}
    assert len(trace_ids) == 1

    # Verify cascading errors
    levels = [log["level"] for log in logs]
    assert "ERROR" in levels
    errors: list[dict[str, Any]] = [
        log["error"] for log in logs if isinstance(log.get("error"), dict)
    ]
    assert any(e["error_type"] == "GatewayTimeoutException" for e in errors)
    assert any(e["error_type"] == "OrderProcessingError" for e in errors)
    assert any(e["error_type"] == "BadGateway" for e in errors)


def test_db_pool_exhaustion_scenario():
    now = datetime.now(UTC)
    logs, record = generate_db_pool_scenario(tenant_id="acme", base_time=now)

    assert record.scenario_type == ScenarioType.DB_POOL_EXHAUSTION
    assert record.root_cause_service == ServiceName.ORDER_SERVICE
    assert "ConnectionPoolExhausted" in record.root_cause_error
    assert record.total_logs_emitted == len(logs)

    errors: list[dict[str, Any]] = [
        log["error"] for log in logs if isinstance(log.get("error"), dict)
    ]
    assert any(e["error_type"] == "ConnectionPoolExhausted" for e in errors)
    assert any(e["error_type"] == "ServiceUnavailable" for e in errors)


def test_auth_dependency_failure_scenario():
    now = datetime.now(UTC)
    logs, record = generate_auth_failure_scenario(tenant_id="acme", base_time=now)

    assert record.scenario_type == ScenarioType.AUTH_DEPENDENCY_FAILURE
    assert record.root_cause_service == ServiceName.AUTH_SERVICE
    assert "RedisConnectionRefused" in record.root_cause_error
    assert record.total_logs_emitted == len(logs)

    levels = [log["level"] for log in logs]
    assert "FATAL" in levels or "ERROR" in levels
    errors: list[dict[str, Any]] = [
        log["error"] for log in logs if isinstance(log.get("error"), dict)
    ]
    assert any(e["error_type"] == "RedisConnectionRefused" for e in errors)
    assert any(e["error_type"] == "Unauthorized" for e in errors)


def test_retry_storm_scenario():
    now = datetime.now(UTC)
    logs, record = generate_retry_storm_scenario(tenant_id="acme", base_time=now)

    assert record.scenario_type == ScenarioType.RETRY_STORM
    assert record.root_cause_service == ServiceName.NOTIFICATION_SERVICE
    assert "WebhookTimeoutException" in record.root_cause_error
    assert record.total_logs_emitted == len(logs)

    # Verify 5 retry logs
    retry_logs = [log for log in logs if "RetryAttempt" in log["message"]]
    assert len(retry_logs) == 5

    errors: list[dict[str, Any]] = [
        log["error"] for log in logs if isinstance(log.get("error"), dict)
    ]
    assert any(e["error_type"] == "ThreadSaturationError" for e in errors)


def test_scenario_generators_registry():
    for scenario_type in ScenarioType:
        assert scenario_type in SCENARIO_GENERATORS
        gen_fn = SCENARIO_GENERATORS[scenario_type]
        logs, record = gen_fn(tenant_id="acme")
        assert len(logs) > 0
        assert record.scenario_type == scenario_type
