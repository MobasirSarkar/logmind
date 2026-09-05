from datetime import UTC, datetime, timedelta

from correlation.models import EventType
from correlation.trace_sequencer import TraceSequencer


def test_trace_sequencer_isolates_initial_trigger():
    t0 = datetime.now(UTC)
    logs = [
        {
            "timestamp": (t0 + timedelta(milliseconds=10)).isoformat(),
            "level": "ERROR",
            "message": "GatewayTimeoutException: Stripe timed out",
            "context": {"service": "payment-service", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-3", "parent_span_id": "sp-2"},
        },
        {
            "timestamp": (t0 + timedelta(milliseconds=20)).isoformat(),
            "level": "ERROR",
            "message": "OrderProcessingError: payment failed",
            "context": {"service": "order-service", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-2", "parent_span_id": "sp-1"},
        },
        {
            "timestamp": (t0 + timedelta(milliseconds=30)).isoformat(),
            "level": "ERROR",
            "message": "BadGateway: downstream error",
            "context": {"service": "api-gateway", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-1", "parent_span_id": None},
        },
    ]

    sequencer = TraceSequencer()
    initial_event, cascading_events = sequencer.sequence_trace("inc-1", logs)

    assert initial_event.service == "payment-service"
    assert initial_event.event_type == EventType.INITIAL_ERROR
    assert len(cascading_events) == 2
    assert cascading_events[0].service == "order-service"
    assert cascading_events[0].event_type == EventType.CASCADING_ERROR
    assert cascading_events[1].service == "api-gateway"
    assert cascading_events[1].event_type == EventType.CASCADING_ERROR
