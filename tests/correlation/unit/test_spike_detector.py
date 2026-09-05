from unittest.mock import AsyncMock

import pytest

from correlation.detector import SpikeAlert, SpikeDetector


@pytest.mark.asyncio
async def test_spike_detector_triggers_on_surge():
    mock_es = AsyncMock()
    detector = SpikeDetector(es_client=mock_es)

    # Return error counts:
    # 1. current errors (15)
    # 2. current total requests (50) -> error_rate = 15/50 = 0.30
    # 3. baseline errors (1)
    # 4. baseline total requests (100) -> baseline_rate = 1/100 = 0.01
    mock_es.count.side_effect = [
        {"count": 15},
        {"count": 50},
        {"count": 1},
        {"count": 100},
    ]

    spikes = await detector.evaluate_service(tenant_id="t-1", service="payment-service")
    assert len(spikes) == 1
    alert = spikes[0]
    assert isinstance(alert, SpikeAlert)
    assert alert.service == "payment-service"
    assert alert.error_count == 15
    assert alert.error_rate == pytest.approx(0.30)
    assert alert.baseline_rate == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_spike_detector_ignores_sub_threshold():
    mock_es = AsyncMock()
    detector = SpikeDetector(es_client=mock_es)

    # Error count = 3 (< 10 threshold)
    mock_es.count.side_effect = [
        {"count": 3},
        {"count": 10},
        {"count": 0},
        {"count": 100},
    ]

    spikes = await detector.evaluate_service(tenant_id="t-1", service="payment-service")
    assert len(spikes) == 0
