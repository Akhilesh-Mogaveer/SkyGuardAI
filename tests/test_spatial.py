"""Unit and integration tests for Spatial Cross-Validation engine."""

import pytest
from backend.app.core.spatial import SpatialValidator, StationMetadata, haversine_distance_km


def test_haversine_distance_maitri_to_novolazarevskaya():
    """Maitri (-70.767, 11.733) to Novolazarevskaya (-70.776, 11.832) is ~4-12 km."""
    dist = haversine_distance_km(-70.767, 11.733, -70.776, 11.832)
    assert 3.0 <= dist <= 6.0  # Precise great-circle distance is ~3.7 km


def test_spatial_elevation_pressure_adjustment():
    """Pressure adjustment from 117m (Maitri) to 102m (Novo) should increase pressure (~1.8 hPa)."""
    validator = SpatialValidator()
    # At lower elevation (102m vs 117m), pressure is higher
    p_adj = validator.adjust_pressure_for_elevation(950.0, from_elevation_m=117.0, to_elevation_m=102.0)
    assert p_adj > 950.0
    assert round(p_adj - 950.0, 2) == pytest.approx(1.79, rel=0.1)


def test_spatial_validation_concordant_weather_event():
    """When genuine companion observations are provided and both stations show concordant readings -> Spatial Agreement True."""
    validator = SpatialValidator()
    result = validator.validate_observation(
        timestamp="2016-08-01 12:00:00",
        target_temp=-28.0,
        target_pressure=960.0,
        target_humidity=65.0,
        buddy_data={"station_id": "AWS-NOVO-89512", "temperature": -27.5, "pressure": 961.5, "humidity": 68.0},
    )
    assert result.spatial_agreement is True
    assert result.spatial_status == "NORMAL_CONSISTENT"
    assert result.spatial_evidence_score > 0.5


def test_spatial_validation_known_fault_spike_discordance():
    """When genuine companion observations are provided and target diverges strongly -> Isolated Discordance."""
    validator = SpatialValidator()
    result = validator.validate_observation(
        timestamp="2016-09-09 17:00:00",
        target_temp=41.6,
        target_pressure=946.0,
        target_humidity=100.0,
        buddy_data={"station_id": "AWS-NOVO-89512", "temperature": -22.0, "pressure": 947.0, "humidity": 45.0},
    )
    assert result.spatial_agreement is False
    assert result.spatial_status == "ISOLATED_DISCORDANCE"
    assert result.spatial_evidence_score == -1.0
    assert any("diverges" in r for r in result.reasons)


def test_spatial_validation_single_station_no_buddy_data():
    """When no neighboring station data is provided (buddy_data=None), spatial status is UNAVAILABLE with 0.0 score."""
    validator = SpatialValidator()
    result = validator.validate_observation(
        timestamp="2016-09-09 17:00:00",
        target_temp=41.6,
        target_pressure=946.0,
        target_humidity=100.0,
        buddy_data=None,
    )
    assert result.spatial_agreement is None
    assert result.spatial_status == "UNAVAILABLE"
    assert result.spatial_evidence_score == 0.0
    assert result.buddy_temperature is None
    assert "unavailable" in result.reasons[0].lower()
