from datetime import UTC, datetime

from simulator.models import ServiceName
from simulator.trace import TraceGenerator


def test_trace_id_generation():
    generator = TraceGenerator()
    trace_id_1 = generator.new_trace_id()
    trace_id_2 = generator.new_trace_id()
    assert trace_id_1 != trace_id_2
    assert len(trace_id_1) == 36


def test_steady_state_trace_generation():
    generator = TraceGenerator()
    tenant_id = "acme"
    start_time = datetime.now(UTC)

    logs = generator.generate_steady_state_trace(tenant_id=tenant_id, base_time=start_time)

    # 1. Check count and topology coverage
    assert len(logs) >= 5
    services_present = {log["context"]["service"] for log in logs}
    expected_services = {
        ServiceName.API_GATEWAY.value,
        ServiceName.AUTH_SERVICE.value,
        ServiceName.ORDER_SERVICE.value,
        ServiceName.PAYMENT_SERVICE.value,
        ServiceName.NOTIFICATION_SERVICE.value,
    }
    assert expected_services.issubset(services_present)

    # 2. Assert shared trace_id across the whole trace
    trace_ids = {log["trace"]["trace_id"] for log in logs}
    assert len(trace_ids) == 1

    # 3. Assert parent-child hierarchy
    gateway_log = next(log for log in logs if log["context"]["service"] == ServiceName.API_GATEWAY.value)
    root_span_id = gateway_log["trace"]["span_id"]
    assert root_span_id is not None

    downstream_logs = [log for log in logs if log["context"]["service"] != ServiceName.API_GATEWAY.value]
    for child in downstream_logs:
        # Downstream spans must have a parent span id
        assert child["trace"]["parent_span_id"] is not None

    # 4. Check sequential timestamps
    timestamps = [datetime.fromisoformat(log["timestamp"]) for log in logs]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1]
