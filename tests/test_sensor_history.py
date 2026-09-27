"""Unit and integration tests for Sensor Historical Health tracking."""

import pytest
from backend.app.core.sensor_history import ParameterHistoryTracker, SensorHealthTracker


def test_parameter_health_tracker_healthy():
    tracker = ParameterHistoryTracker("temperature")
    for val in [-15.0, -15.2, -14.9, -15.1, -15.0]:
        rec = tracker.update(value=val, is_suspect=False, is_missing=False)
    assert rec.status == "HEALTHY"
    assert rec.health_index >= 95.0
    assert rec.error_rate_24h == 0.0


def test_parameter_health_tracker_degradation():
    tracker = ParameterHistoryTracker("temperature")
    # Feed 20 suspect observations
    for i in range(20):
        rec = tracker.update(value=0.0, is_suspect=True, is_missing=False)
    assert rec.status in ["DEGRADING", "MAINTENANCE_REQUIRED", "FAILED"]
    assert rec.health_index < 60.0
    assert rec.error_rate_24h > 0.8


def test_sensor_health_tracker_composite_station_status():
    station_tracker = SensorHealthTracker("AWS-MAITRI-89514")
    # All sensors operating well
    summary = station_tracker.update_observation(
        temperature=-20.0,
        pressure=980.0,
        humidity=70.0,
        qc_reasons=[],
    )
    assert summary.overall_status == "OPERATIONAL"
    assert summary.overall_health_index >= 90.0

    # Temperature sensor exhibits repeated flatline and spikes
    for _ in range(10):
        summary = station_tracker.update_observation(
            temperature=41.6,
            pressure=980.0,
            humidity=70.0,
            qc_reasons=["Temperature rate of change spike", "Temperature plausibility failure"],
        )
    assert summary.parameters["temperature"].health_index < 60.0
    assert summary.overall_status in ["DEGRADED", "CRITICAL_ATTENTION"]
    assert len(summary.active_alerts) > 0
