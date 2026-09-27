"""Backend Test Suite for SkyGuard AI FastAPI Application.

Tests:
1. GET /health — System health & model status
2. GET /stations & GET /stations/{station_id} — Monitored AWS station metadata
3. GET /sensor-health — Sensor reliability indices
4. POST /process-observation — Single observation ingestion through full 7-stage pipeline
5. GET /observations & GET /anomalies & GET /statistics — Telemetry querying & filter breakdown
6. POST /replay/start, POST /replay/stop, GET /replay/status — Historical CSV replay worker
7. WebSocket /ws/observations — Real-time telemetry broadcasting
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.db.alert_db import AlertDatabase
from backend.app.services.replay_service import replay_runner


@pytest.fixture
def client():
    return TestClient(app)


def test_get_health(client):
    """Verifies /health endpoint returns operational status and model readiness."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "OPERATIONAL"
    assert data["system"] == "SkyGuard AI"
    assert "models" in data
    assert "isolation_forest_loaded" in data["models"]
    assert "lstm_autoencoder_loaded" in data["models"]


def test_get_stations(client):
    """Verifies /stations endpoint returns Antarctic station network."""
    res = client.get("/stations")
    assert res.status_code == 200
    stations = res.json()
    assert len(stations) >= 2
    primary = next((s for s in stations if s["is_primary"]), None)
    assert primary is not None
    assert primary["station_id"] == settings.DEFAULT_STATION_ID


def test_get_station_details_success_and_404(client):
    """Verifies /stations/{station_id} returns details or 404 for invalid ID."""
    res = client.get(f"/stations/{settings.DEFAULT_STATION_ID}")
    assert res.status_code == 200
    data = res.json()
    assert data["station_id"] == settings.DEFAULT_STATION_ID

    res_404 = client.get("/stations/NON_EXISTENT_STATION")
    assert res_404.status_code == 404


def test_get_sensor_health(client):
    """Verifies /sensor-health endpoint returns reliability indices."""
    res = client.get("/sensor-health")
    assert res.status_code == 200
    data = res.json()
    assert "station_id" in data
    assert "parameter_history" in data


def test_process_single_observation_normal(client):
    """Ingests a normal observation via POST /process-observation."""
    payload = {
        "timestamp": "2016-01-15 12:00:00",
        "temperature": -10.5,
        "pressure": 985.0,
        "relative_humidity": 65.0,
        "station_id": settings.DEFAULT_STATION_ID,
    }
    res = client.post("/process-observation", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["timestamp"] is not None
    assert data["temperature"] == -10.5
    assert "decision" in data
    assert data["decision"]["classification"] == "NORMAL"


def test_process_single_observation_known_fault_spike(client):
    """Ingests real Antarctic spike (+41.6°C jump) via POST /process-observation -> must classify as LIKELY_SENSOR_DATA_FAULT."""
    payload = {
        "timestamp": "2016-09-09 17:00:00",
        "temperature": 41.6,
        "pressure": 946.0,
        "relative_humidity": 100.0,
        "station_id": settings.DEFAULT_STATION_ID,
    }
    res = client.post("/process-observation", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["temperature"] == 41.6
    assert data["decision"]["classification"] == "LIKELY_SENSOR_DATA_FAULT"
    assert data["decision"]["severity"] == "CRITICAL"
    assert "transducer" in data["decision"]["recommended_operator_action"].lower()


def test_get_observations_and_anomalies_query(client):
    """Verifies /observations and /anomalies querying."""
    # Process one fault and one normal
    client.post("/process-observation", json={"timestamp": "2016-01-01 00:00:00", "temperature": -15.0, "pressure": 980.0, "relative_humidity": 60.0})
    client.post("/process-observation", json={"timestamp": "2016-09-09 17:00:00", "temperature": 41.6, "pressure": 946.0, "relative_humidity": 100.0})

    res_obs = client.get("/observations")
    assert res_obs.status_code == 200
    assert "observations" in res_obs.json()

    res_anom = client.get("/anomalies?classification=LIKELY_SENSOR_DATA_FAULT")
    assert res_anom.status_code == 200
    data_anom = res_anom.json()
    assert "anomalies" in data_anom


def test_get_statistics(client):
    """Verifies /statistics endpoint."""
    res = client.get("/statistics")
    assert res.status_code == 200
    data = res.json()
    assert "classification_breakdown" in data
    assert "replay_status" in data


def test_historical_csv_replay_controls(client):
    """Tests /replay/start, /replay/status, and /replay/stop endpoints."""
    # 1. Start replay
    res_start = client.post("/replay/start", json={"speed_multiplier": 50.0, "start_index": 0})
    assert res_start.status_code == 200
    assert res_start.json()["message"] == "Historical CSV replay started"

    # 2. Check status
    res_status = client.get("/replay/status")
    assert res_status.status_code == 200

    # 3. Stop replay
    res_stop = client.post("/replay/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["message"] == "Historical CSV replay stopped"


def test_websocket_observations_connection(client):
    """Tests WebSocket endpoint /ws/observations for live stream broadcasting."""
    with client.websocket_connect("/ws/observations") as websocket:
        welcome = websocket.receive_json()
        assert welcome["event_type"] == "CONNECTED"
        assert "SkyGuard AI" in welcome["message"]

        # Send test message
        websocket.send_text("PING")
        ack = websocket.receive_json()
        assert ack["event_type"] == "ACK"


def test_alert_database_reuses_duplicate_and_paginates(tmp_path):
    """Repeated processing of one alert identity must not create another history row."""
    database = AlertDatabase(tmp_path / "alerts.db")

    def result(timestamp):
        return {
            "timestamp": timestamp,
            "station_id": "AWS-MAITRI-89514",
            "temperature": 41.6,
            "pressure": 946.7,
            "humidity": 100.0,
            "decision": {
                "classification": "LIKELY_SENSOR_DATA_FAULT",
                "severity": "CRITICAL",
                "primary_parameter": "temperature",
                "primary_root_cause": "rapid_temperature_change",
            },
            "qc_result": {"temperature_spike": True},
        }

    first_id = database.insert_observation(result("2016-09-09T17:00:00+00:00"))
    duplicate_id = database.insert_observation(result("2016-09-09T17:00:00+00:00"))
    assert duplicate_id == first_id

    for hour in range(1, 13):
        database.insert_observation(result(f"2016-09-09T{17 + hour:02d}:00:00+00:00"))

    first_page = database.fetch_anomalies_page(page=1, page_size=10)
    second_page = database.fetch_anomalies_page(page=2, page_size=10)
    assert first_page["total"] == 13
    assert first_page["total_pages"] == 2
    assert len(first_page["items"]) == 10
    assert len(second_page["items"]) == 3
    assert first_page["items"][0]["timestamp"] > first_page["items"][-1]["timestamp"]
    assert first_page["items"][0]["maintenance_status"] == "Inspection Recommended"
    assert first_page["items"][0]["decision"]["maintenance_status"] == "Inspection Recommended"
    assert "temperature sensor/transducer" in first_page["items"][0]["maintenance_action"]
