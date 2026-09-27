"""Tests for SkyGuard AI Demo Mode endpoints and real pipeline execution."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_get_demo_preset_cases():
    """Test retrieving demo preset benchmark cases."""
    response = client.get("/demo/preset-cases")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4

    # Locate mandatory 2016-09-09 17:00 spike preset
    spike_preset = next((p for p in data if "2016-09-09" in p["timestamp"]), None)
    assert spike_preset is not None
    assert spike_preset["temperature"] == 41.6
    assert spike_preset["case_id"] == "temp_spike_2016_09_09"


def test_evaluate_demo_step_real_pipeline_temp_spike():
    """Test evaluating the 2016-09-09 17:00 (+41.6°C jump) observation through real pipeline."""
    payload = {
        "timestamp": "2016-09-09 17:00:00+00:00",
        "prewarm_hours": 48
    }
    response = client.post("/demo/evaluate-step", json=payload)
    assert response.status_code == 200
    res = response.json()

    # Stage 1: Raw Observation (unchanged)
    s1 = res["stage_1_incoming"]
    assert s1["temperature"] == 41.6
    assert s1["pressure"] == 946.7


    # Stage 2: Rule QC
    s2 = res["stage_2_qc"]
    assert s2["qc_flag"] == "SUSPECT"
    assert s2["temperature_spike"] is True


    # Stage 3: Isolation Forest
    s3 = res["stage_3_iforest"]
    assert "anomaly_score" in s3
    assert s3["anomaly_score"] is not None

    # Stage 4: TensorFlow/Keras LSTM Autoencoder
    s4 = res["stage_4_lstm"]
    assert "reconstruction_error_mse" in s4
    assert s4["reconstruction_error_mse"] is not None

    # Stage 5: Evidence Validation
    s5 = res["stage_5_evidence_validation"]
    assert s5["spatial_status"] == "UNAVAILABLE"

    # Stage 6: Final Classification (evaluated by actual pipeline decision engine)
    s6 = res["stage_6_classification"]
    assert s6["primary_classification"] == "LIKELY_SENSOR_DATA_FAULT"
    assert s6["severity"] in ["HIGH", "CRITICAL"]

    # Stage 7: Explanation & Operator Action
    s7 = res["stage_7_explanation"]
    assert "probable_cause" in s7
    assert "recommended_operator_action" in s7

    # Stage 8: Sensor Health Update
    s8 = res["stage_8_sensor_health_update"]
    assert "overall_status" in s8
    assert "parameter_scores" in s8
