"""Unit and integration tests for Evidence Fusion and Decision Engine."""

import pytest
from backend.app.core.baseline_qc import QCResult
from backend.app.core.spatial import SpatialCheckResult
from backend.app.core.sensor_history import StationHealthSummary, ParameterHealthRecord
from backend.app.core.evidence_fusion import (
    EvidenceFusionEngine,
    DecisionClassification,
    AnomalySeverity,
    get_maintenance_action,
    get_maintenance_status,
)


@pytest.fixture
def fusion_engine():
    return EvidenceFusionEngine()


def test_maintenance_status_policy_and_root_cause_actions():
    assert get_maintenance_status("CRITICAL") == "Inspection Recommended"
    assert get_maintenance_status("HIGH") == "Inspection Recommended"
    assert get_maintenance_status("MEDIUM") == "Monitor Closely"
    assert get_maintenance_status("LOW") == "Monitor"
    assert get_maintenance_status("NORMAL") == "Normal"
    assert get_maintenance_status("CRITICAL", "Likely Sensor/Data Fault") == "Inspection Recommended"
    assert get_maintenance_status("HIGH", "Likely Sensor/Data Fault") != "Normal"

    assert get_maintenance_action("Pressure Plausibility Violation") == (
        "Flag observation as invalid and inspect the pressure sensor/transducer, signal cable, and A/D converter."
    )
    assert get_maintenance_action("Rapid Temperature Change") == (
        "Flag observation as invalid and inspect the temperature sensor/transducer, signal cable, and A/D converter."
    )


def test_fusion_normal_observation(fusion_engine):
    """Clean observation with low ML scores and passed QC yields NORMAL."""
    decision = fusion_engine.fuse(
        timestamp="2016-01-15 12:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=-10.5,
        pressure=985.0,
        humidity=65.0,
        qc_result=QCResult(
            timestamp="2016-01-15 12:00:00",
            station_id="AWS-MAITRI-89514",
            temperature=-10.5,
            pressure=985.0,
            humidity=65.0,
            qc_flag="PASSED",
        ),
        iforest_score=0.25,
        iforest_flag=False,
        lstm_mse=0.08,
        lstm_flag=False,
        spatial_result=SpatialCheckResult(
            target_station_id="AWS-MAITRI-89514",
            timestamp="2016-01-15 12:00:00",
            buddy_station_id="AWS-NOVO-89512",
            buddy_distance_km=11.2,
            buddy_temperature=-10.2,
            buddy_pressure=985.2,
            buddy_humidity=64.0,
            temp_difference=-0.3,
            pressure_difference_adjusted=0.2,
            humidity_difference=1.0,
            spatial_agreement=True,
            spatial_evidence_score=0.8,
            spatial_status="NORMAL_CONSISTENT",
        ),
        dew_point=-15.0,
    )
    assert decision.classification == DecisionClassification.NORMAL
    assert decision.severity == AnomalySeverity.NONE
    assert decision.calibrated_confidence is not None
    assert decision.calibrated_confidence > 0.8


def test_fusion_known_anomaly_2016_09_09_17_00_is_sensor_fault(fusion_engine):
    """Real Antarctica anomaly (+41.6°C jump) with companion buddy data must classify as LIKELY_SENSOR_DATA_FAULT with CRITICAL severity."""
    qc = QCResult(
        timestamp="2016-09-09 17:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=41.6,
        pressure=946.0,
        humidity=100.0,
        qc_flag="SUSPECT",
        qc_reasons=[
            "Temperature (41.6°C) exceeds plausibility upper bound (35.0°C)",
            "Temperature step change (63.8°C/h) exceeds threshold (12.0°C/h)",
        ],
        temperature_spike=True,
        humidity_spike=True,
    )
    spatial = SpatialCheckResult(
        target_station_id="AWS-MAITRI-89514",
        timestamp="2016-09-09 17:00:00",
        buddy_station_id="AWS-NOVO-89512",
        buddy_distance_km=11.2,
        buddy_temperature=-22.0,
        buddy_pressure=946.5,
        buddy_humidity=40.0,
        temp_difference=63.6,
        pressure_difference_adjusted=-0.5,
        humidity_difference=60.0,
        spatial_agreement=False,
        spatial_evidence_score=-1.0,
        spatial_status="ISOLATED_DISCORDANCE",
        reasons=["Spatial discordance: Target temp 41.6°C diverges from Novolazarevskaya (-22.0°C)"],
    )

    decision = fusion_engine.fuse(
        timestamp="2016-09-09 17:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=41.6,
        pressure=946.0,
        humidity=100.0,
        qc_result=qc,
        iforest_score=1.00,
        iforest_flag=True,
        lstm_mse=1.3869,
        lstm_flag=True,
        spatial_result=spatial,
        dew_point=41.6,
    )

    assert decision.classification == DecisionClassification.LIKELY_SENSOR_DATA_FAULT
    assert decision.severity == AnomalySeverity.CRITICAL
    assert decision.primary_parameter == "temperature"
    assert decision.calibrated_confidence is not None
    assert decision.calibrated_confidence >= 0.85
    assert "transducer" in decision.recommended_operator_action.lower()


def test_fusion_known_anomaly_without_spatial_data(fusion_engine):
    """When no spatial data exists (single station), real anomaly (+41.6°C jump) still classifies as LIKELY_SENSOR_DATA_FAULT due to physical limit violation and thermodynamic inconsistency."""
    qc = QCResult(
        timestamp="2016-09-09 17:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=41.6,
        pressure=946.0,
        humidity=100.0,
        qc_flag="SUSPECT",
        qc_reasons=[
            "Temperature (41.6°C) exceeds plausibility upper bound (35.0°C)",
            "Temperature step change (63.8°C/h) exceeds threshold (12.0°C/h)",
        ],
        temperature_spike=True,
        humidity_spike=True,
    )
    spatial = SpatialCheckResult(
        target_station_id="AWS-MAITRI-89514",
        timestamp="2016-09-09 17:00:00",
        buddy_station_id=None,
        buddy_distance_km=None,
        buddy_temperature=None,
        buddy_pressure=None,
        buddy_humidity=None,
        temp_difference=None,
        pressure_difference_adjusted=None,
        humidity_difference=None,
        spatial_agreement=None,
        spatial_evidence_score=0.0,
        spatial_status="UNAVAILABLE",
        reasons=["Spatial validation unavailable: No neighboring station observations provided."],
    )

    decision = fusion_engine.fuse(
        timestamp="2016-09-09 17:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=41.6,
        pressure=946.0,
        humidity=100.0,
        qc_result=qc,
        iforest_score=1.00,
        iforest_flag=True,
        lstm_mse=1.3869,
        lstm_flag=True,
        spatial_result=spatial,
        dew_point=41.6,
    )

    assert decision.classification == DecisionClassification.LIKELY_SENSOR_DATA_FAULT
    assert decision.severity == AnomalySeverity.CRITICAL
    assert decision.primary_parameter == "temperature"
    assert decision.calibrated_confidence is not None


def test_fusion_genuine_weather_event(fusion_engine):
    """Rapid regional pressure fall & wind drop corroborated by buddy station classifies as LIKELY_GENUINE_WEATHER_EVENT."""
    qc = QCResult(
        timestamp="2016-07-20 04:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=-24.0,
        pressure=935.0,
        humidity=85.0,
        qc_flag="SUSPECT",
        qc_reasons=["Pressure rate of change (-8.5 hPa/h) exceeds normal limit"],
        pressure_spike=True,
    )
    spatial = SpatialCheckResult(
        target_station_id="AWS-MAITRI-89514",
        timestamp="2016-07-20 04:00:00",
        buddy_station_id="AWS-NOVO-89512",
        buddy_distance_km=11.2,
        buddy_temperature=-23.5,
        buddy_pressure=935.5,
        buddy_humidity=84.0,
        temp_difference=-0.5,
        pressure_difference_adjusted=-0.5,
        humidity_difference=1.0,
        spatial_agreement=True,
        spatial_evidence_score=0.9,
        spatial_status="CORROBORATED_EVENT",
        reasons=["Regional cyclonic depression matches Novolazarevskaya reading."],
    )

    decision = fusion_engine.fuse(
        timestamp="2016-07-20 04:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=-24.0,
        pressure=935.0,
        humidity=85.0,
        qc_result=qc,
        iforest_score=0.72,
        iforest_flag=True,
        lstm_mse=0.45,
        lstm_flag=True,
        spatial_result=spatial,
        dew_point=-26.0,
    )

    assert decision.classification == DecisionClassification.LIKELY_GENUINE_WEATHER_EVENT
    assert decision.severity == AnomalySeverity.MEDIUM
    assert decision.calibrated_confidence is not None
    assert decision.calibrated_confidence >= 0.75
    assert "cyclonic" in decision.probable_cause.lower() or "meteorological" in decision.probable_cause.lower()
    assert "not flag as sensor fault" in decision.recommended_operator_action.lower()


def test_fusion_uncertain_on_ambiguous_or_missing_buddy(fusion_engine):
    """Isolated single-station ML alert with no buddy data and no plausibility violation must be UNCERTAIN."""
    decision = fusion_engine.fuse(
        timestamp="2016-05-10 18:00:00",
        station_id="AWS-MAITRI-89514",
        temperature=-18.0,
        pressure=975.0,
        humidity=50.0,
        qc_result=None,
        iforest_score=0.82,  # IForest flags it
        iforest_flag=True,
        lstm_mse=0.15,  # LSTM does not see anomaly
        lstm_flag=False,
        spatial_result=SpatialCheckResult(
            target_station_id="AWS-MAITRI-89514",
            timestamp="2016-05-10 18:00:00",
            buddy_station_id=None,
            buddy_distance_km=None,
            buddy_temperature=None,
            buddy_pressure=None,
            buddy_humidity=None,
            temp_difference=None,
            pressure_difference_adjusted=None,
            humidity_difference=None,
            spatial_agreement=None,
            spatial_evidence_score=0.0,
            spatial_status="UNAVAILABLE",
            reasons=["No buddy data"],
        ),
        dew_point=-23.0,
    )

    assert decision.classification == DecisionClassification.UNCERTAIN
    assert decision.calibrated_confidence is None  # Must never claim confidence when uncertain!
    assert "review" in decision.recommended_operator_action.lower()
