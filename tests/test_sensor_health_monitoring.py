"""Comprehensive test suite for Sensor Health Monitoring architecture.

Tests:
1. Long-term sensor health index calculation across configurable indicators:
   - anomaly frequency
   - missing data frequency
   - flatline frequency
   - repeated QC violations
   - recent anomaly trend momentum
2. Core Invariant: Health score describes long-term reliability without overriding observation classification.
3. SQLite schema and persistence layer (`sensor_health_db.py`).
4. Historical health chart generation service (`health_chart_service.py`).
5. Station Health REST API endpoints (`health_router.py`) via FastAPI TestClient.
"""

from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

from backend.app.main import app
from backend.app.db.sensor_health_db import SensorHealthDatabase, SensorHealthEntry, StationHealthSnapshot
from backend.app.services.sensor_health_service import SensorHealthCalculationService, HealthIndicatorConfig
from backend.app.services.health_chart_service import HealthChartService


@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_sensor_health.db"


@pytest.fixture
def health_db(temp_db_path):
    return SensorHealthDatabase(db_path=temp_db_path)


@pytest.fixture
def health_service(health_db):
    return SensorHealthCalculationService(db=health_db)


@pytest.fixture
def api_client():
    return TestClient(app)


def test_sensor_health_db_schema_and_crud(health_db):
    """Verifies SQLite tables creation, parameter insertion, and fetching."""
    entry = SensorHealthEntry(
        id=None,
        timestamp="2016-09-20 12:00:00",
        station_id="AWS-MAITRI-89514",
        parameter_name="temperature",
        health_index=92.5,
        status="HEALTHY",
        anomaly_frequency=0.02,
        missing_frequency=0.01,
        flatline_frequency=0.00,
        qc_violation_rate=0.03,
        recent_anomaly_trend=0.01,
        evaluation_window_hours=720,
    )

    row_id = health_db.insert_parameter_health(entry)
    assert row_id is not None and row_id > 0

    history = health_db.fetch_parameter_health_history("AWS-MAITRI-89514", "temperature")
    assert len(history) == 1
    assert history[0].health_index == 92.5
    assert history[0].status == "HEALTHY"


def test_station_snapshot_crud(health_db):
    """Verifies station snapshot insertion and retrieval."""
    snapshot = StationHealthSnapshot(
        id=None,
        timestamp="2016-09-20 12:00:00",
        station_id="AWS-MAITRI-89514",
        overall_health_index=88.0,
        overall_status="OPERATIONAL",
        parameter_scores={"temperature": 85.0, "pressure": 95.0, "humidity": 84.0},
        active_alerts=["Sensor [temperature] health degrading"],
    )

    row_id = health_db.insert_station_snapshot(snapshot)
    assert row_id is not None and row_id > 0

    fetched = health_db.fetch_latest_station_snapshot("AWS-MAITRI-89514")
    assert fetched is not None
    assert fetched.overall_health_index == 88.0
    assert fetched.overall_status == "OPERATIONAL"
    assert "temperature" in fetched.parameter_scores


def test_health_calculation_pristine_sensor(health_service):
    """Pristine sensor with 0 anomalies and 0 missing data scores ~100% health."""
    df = pd.DataFrame({
        "temperature": [-15.0] * 100,
        "temperature_qc_flag": ["PASSED"] * 100,
        "temperature_anomaly": [False] * 100,
        "temperature_flatline": [False] * 100,
    })

    entry = health_service.calculate_parameter_health("AWS-MAITRI-89514", "temperature", df, "2016-09-20 12:00:00")
    assert entry.health_index == 100.0
    assert entry.status == "HEALTHY"
    assert entry.anomaly_frequency == 0.0
    assert entry.missing_frequency == 0.0
    assert entry.recent_anomaly_trend == 0.0


def test_health_calculation_degrading_sensor_indicators(health_service):
    """Sensor with high missing frequency, flatline rate, and worsening recent trend gets degraded health score."""
    # 100 observations: 30 missing, 20 QC violations, 20 anomalies
    df = pd.DataFrame({
        "temperature": [-15.0] * 70 + [np.nan] * 30,
        "temperature_qc_flag": ["PASSED"] * 80 + ["SUSPECT"] * 20,
        "temperature_anomaly": [False] * 70 + [True] * 30,
        "temperature_flatline": [False] * 80 + [True] * 20,
    })

    entry = health_service.calculate_parameter_health("AWS-MAITRI-89514", "temperature", df, "2016-09-20 12:00:00")
    assert entry.health_index < 70.0
    assert entry.status in ["DEGRADING", "MAINTENANCE_REQUIRED", "FAILED"]
    assert entry.missing_frequency == pytest.approx(0.30, rel=1e-2)
    assert entry.qc_violation_rate == pytest.approx(0.20, rel=1e-2)


def test_recent_anomaly_trend_momentum(health_service):
    """Worsening recent 24h anomaly momentum increases penalty relative to baseline."""
    # Baseline 100 hours: 5% anomaly rate
    anom_flags = [False] * 95 + [True] * 5
    # Recent 24 hours: 50% anomaly rate (sharp worsening trend)
    anom_flags.extend([True] * 12 + [False] * 12)

    df = pd.DataFrame({
        "temperature": [-15.0] * len(anom_flags),
        "temperature_anomaly": anom_flags,
    })

    entry = health_service.calculate_parameter_health("AWS-MAITRI-89514", "temperature", df, "2016-09-20 12:00:00")
    assert entry.recent_anomaly_trend > 0.10  # Positive trend indicates worsening reliability


def test_health_score_invariant_does_not_determine_observation_fault(health_service):
    """CORE INVARIANT TEST: Health score evaluates long-term reliability and returns structured record.
    It does not dictate single-observation classification."""
    df = pd.DataFrame({
        "temperature": [-15.0] * 50,
        "temperature_anomaly": [False] * 50,
    })
    entry = health_service.calculate_parameter_health("AWS-MAITRI-89514", "temperature", df, "2016-09-20 12:00:00")
    # Health entry describes long-term state
    assert hasattr(entry, "health_index")
    assert hasattr(entry, "status")
    # Must not contain single-observation classification labels like LIKELY_SENSOR_DATA_FAULT
    assert not hasattr(entry, "classification")


def test_historical_health_chart_generation(health_db, tmp_path):
    """Verifies HealthChartService generates a png file figure."""
    chart_service = HealthChartService(db=health_db)
    chart_file = tmp_path / "test_sensor_health_chart.png"
    result_path = chart_service.generate_health_chart(station_id="AWS-MAITRI-89514", output_path=chart_file)

    assert result_path.exists()
    assert result_path.stat().st_size > 0


def test_fastapi_station_health_endpoints(api_client):
    """Tests FastAPI station health API endpoints."""
    # 1. Root endpoint
    res = api_client.get("/")
    assert res.status_code == 200
    assert res.json()["system"] == "SkyGuard AI"

    # 2. Station health summary endpoint
    res = api_client.get("/api/v1/health/station/AWS-MAITRI-89514")
    assert res.status_code == 200
    data = res.json()
    assert data["station_id"] == "AWS-MAITRI-89514"
    assert "overall_health_index" in data

    # 3. Parameter health breakdown endpoint
    res = api_client.get("/api/v1/health/parameter/AWS-MAITRI-89514/temperature")
    assert res.status_code == 200
    pdata = res.json()
    assert pdata["parameter_name"] == "temperature"
    assert "indicators" in pdata

    # 4. History endpoint
    res = api_client.get("/api/v1/health/history/AWS-MAITRI-89514")
    assert res.status_code == 200
    hdata = res.json()
    assert "history" in hdata

    # 5. Active alerts endpoint
    res = api_client.get("/api/v1/health/alerts/AWS-MAITRI-89514")
    assert res.status_code == 200
    adata = res.json()
    assert "active_alerts" in adata

    # 6. Recalculate endpoint
    res = api_client.post("/api/v1/health/recalculate", json={"station_id": "AWS-MAITRI-89514", "anomaly_weight": 25.0})
    assert res.status_code == 200
    rdata = res.json()
    assert rdata["message"] == "Health metrics successfully recalculated"
