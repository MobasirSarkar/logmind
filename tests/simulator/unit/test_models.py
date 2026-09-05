from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from simulator.models import (
    ScenarioRunRecord,
    ScenarioType,
    ServiceName,
    SimulationStatus,
    SimulationStatusResponse,
    StartSimulationRequest,
    TriggerScenarioRequest,
)


def test_service_name_enum_values():
    assert ServiceName.API_GATEWAY == "api-gateway"
    assert ServiceName.AUTH_SERVICE == "auth-service"
    assert ServiceName.ORDER_SERVICE == "order-service"
    assert ServiceName.PAYMENT_SERVICE == "payment-service"
    assert ServiceName.NOTIFICATION_SERVICE == "notification-service"


def test_scenario_type_enum_values():
    assert ScenarioType.PAYMENT_TIMEOUT == "PAYMENT_TIMEOUT"
    assert ScenarioType.DB_POOL_EXHAUSTION == "DB_POOL_EXHAUSTION"
    assert ScenarioType.AUTH_DEPENDENCY_FAILURE == "AUTH_DEPENDENCY_FAILURE"
    assert ScenarioType.RETRY_STORM == "RETRY_STORM"


def test_simulation_status_enum_values():
    assert SimulationStatus.IDLE == "IDLE"
    assert SimulationStatus.STEADY_STATE == "STEADY_STATE"
    assert SimulationStatus.INJECTING_FAILURE == "INJECTING_FAILURE"
    assert SimulationStatus.DRAINING == "DRAINING"


def test_scenario_run_record_creation():
    now = datetime.now(UTC)
    record = ScenarioRunRecord(
        scenario_type=ScenarioType.PAYMENT_TIMEOUT,
        tenant_id="acme",
        started_at=now,
        root_cause_service=ServiceName.PAYMENT_SERVICE,
        root_cause_error="GatewayTimeoutException: Stripe upstream timed out",
        affected_services=[ServiceName.PAYMENT_SERVICE, ServiceName.ORDER_SERVICE, ServiceName.API_GATEWAY],
        expected_diagnosis="Payment provider timeout in payment-service caused cascading failures",
        scenario_metadata={"upstream": "stripe", "timeout_ms": "8000"},
    )
    assert record.run_id is not None
    assert record.scenario_type == ScenarioType.PAYMENT_TIMEOUT
    assert record.total_logs_emitted == 0
    assert record.scenario_metadata["upstream"] == "stripe"
    assert record.ended_at is None


def test_request_and_status_models():
    start_req = StartSimulationRequest(tenant_id="acme", rate_per_sec=25)
    assert start_req.rate_per_sec == 25

    with pytest.raises(ValidationError):
        StartSimulationRequest(rate_per_sec=0)

    trigger_req = TriggerScenarioRequest(
        scenario_type=ScenarioType.DB_POOL_EXHAUSTION,
        tenant_id="acme",
        duration_seconds=45,
        intensity=1.5,
    )
    assert trigger_req.duration_seconds == 45
    assert trigger_req.intensity == 1.5

    status_resp = SimulationStatusResponse(
        status=SimulationStatus.STEADY_STATE,
        tenant_id="acme",
        current_rate=20,
        active_scenario=None,
    )
    assert status_resp.status == SimulationStatus.STEADY_STATE
