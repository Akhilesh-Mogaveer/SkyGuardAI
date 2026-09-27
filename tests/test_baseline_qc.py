"""Unit tests for Rule-Based Quality Control (QC) Engine.

Validates all 7 QC detectors, schema compliance, strict gap rules, and runs
targeted benchmarks on real-world anomalies from the IMD Maitri dataset,
specifically including the known 2016-09-09 17:00 event (+41.6°C spike).
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backend.app.config import settings
from backend.app.core.baseline_qc import (
    QCConfig,
    QCResult,
    RuleBasedQC,
    check_flatline_series,
    check_missing_observation,
    check_physical_plausibility,
    check_rate_of_change,
    check_time_gap,
)


@pytest.fixture
def default_qc() -> RuleBasedQC:
    """Fixture providing RuleBasedQC with default Antarctic thresholds."""
    return RuleBasedQC()


# ==============================================================================
# 1. Physical Plausibility Tests
# ==============================================================================

def test_physical_plausibility_valid():
    """Valid meteorological values must pass plausibility checks."""
    is_ok, reason = check_physical_plausibility(-15.0, -60.0, 25.0, "temperature")
    assert is_ok is True
    assert reason is None

    is_ok, reason = check_physical_plausibility(980.0, 850.0, 1080.0, "pressure")
    assert is_ok is True
    assert reason is None


def test_physical_plausibility_violations():
    """Unrealistic extremes must trigger plausibility violations."""
    # Antarctic record high is +9.5°C; 41.6°C is physically impossible
    is_ok, reason = check_physical_plausibility(41.6, -60.0, 25.0, "temperature")
    assert is_ok is False
    assert "temperature_plausibility_violation" in reason
    assert "41.60 > 25.00" in reason

    # Pressure below deep cyclone bounds
    is_ok, reason = check_physical_plausibility(820.0, 850.0, 1080.0, "pressure")
    assert is_ok is False
    assert "pressure_plausibility_violation" in reason


# ==============================================================================
# 2-4. Sudden Change / Spike Rate of Change Tests
# ==============================================================================

def test_rate_of_change_normal():
    """Normal hourly variation must not trigger a spike."""
    is_spike, reason, rate = check_rate_of_change(
        curr_val=-12.0,
        prev_val=-11.0,
        time_diff_hours=1.0,
        max_rate_per_hour=8.0,
        param_name="temperature",
    )
    assert is_spike is False
    assert reason is None
    assert rate == 1.0


def test_rate_of_change_spike_detected():
    """Sudden jump exceeding hourly threshold must trigger a spike flag."""
    # 2016-09-09 17:00 spike: -22.2°C -> 41.6°C (+63.8°C jump in 1 hr)
    is_spike, reason, rate = check_rate_of_change(
        curr_val=41.6,
        prev_val=-22.2,
        time_diff_hours=1.0,
        max_rate_per_hour=8.0,
        param_name="temperature",
    )
    assert is_spike is True
    assert "temperature_spike" in reason
    assert rate == 63.8


def test_never_calculate_spike_across_time_gaps():
    """CRITICAL REQUIREMENT: Rate of change must NEVER be computed across large gaps."""
    # Jump of 20°C, but across a 5-hour communication gap
    is_spike, reason, rate = check_rate_of_change(
        curr_val=5.0,
        prev_val=-15.0,
        time_diff_hours=5.0,
        max_rate_per_hour=8.0,
        param_name="temperature",
        max_allowed_gap_hours=1.5,
    )
    # Must NOT trigger spike because the interval is discontinuous (> 1.5 hrs)
    assert is_spike is False
    assert reason is None
    assert rate is None


# ==============================================================================
# 5. Flatline / Frozen Sensor Tests
# ==============================================================================

def test_check_flatline_series():
    """Tests detection of persistent identical sensor values across consecutive hours."""
    timestamps = pd.date_range("2015-01-01 00:00", periods=8, freq="h")
    # 4 consecutive identical readings of -10.0 at indices 2, 3, 4, 5
    temps = pd.Series([-5.0, -8.0, -10.0, -10.0, -10.0, -10.0, -9.0, -7.0])
    ts_series = pd.Series(timestamps)

    flatline_flags = check_flatline_series(
        temps,
        ts_series,
        min_consecutive_hours=4,
        tolerance=1e-4,
    )

    assert not flatline_flags.iloc[0]
    assert not flatline_flags.iloc[1]
    assert bool(flatline_flags.iloc[2]) is True
    assert bool(flatline_flags.iloc[3]) is True
    assert bool(flatline_flags.iloc[4]) is True
    assert bool(flatline_flags.iloc[5]) is True
    assert not flatline_flags.iloc[6]


# ==============================================================================
# 6-7. Missing & Time Gap Tests
# ==============================================================================

def test_check_missing_observation():
    """Detects missing/NaN channels and lists reasons."""
    is_missing, reasons = check_missing_observation(-10.0, None, 60.0)
    assert is_missing is True
    assert "pressure_missing" in reasons


def test_check_time_gap():
    """Detects when an observation follows a discontinuous interval."""
    is_gap, reason = check_time_gap(time_diff_hours=3.0, nominal_hours=1.0)
    assert is_gap is True
    assert "time_gap_detected" in reason


# ==============================================================================
# Schema Compliance & Rule-Based QC Pipeline Tests
# ==============================================================================

def test_qc_result_schema_fields(default_qc: RuleBasedQC):
    """Verifies that all 15 required QC schema fields are populated."""
    res = default_qc.process_observation(
        timestamp="2016-09-09 17:00:00+00:00",
        temperature=41.6,
        pressure=946.7,
        humidity=100.0,
        prev_observation={
            "timestamp": "2016-09-09 16:00:00+00:00",
            "temperature": -22.2,
            "pressure": 946.5,
            "humidity": 39.0,
        },
    )

    d = res.to_dict()
    required_keys = [
        "timestamp",
        "station_id",
        "temperature",
        "pressure",
        "humidity",
        "qc_flag",
        "qc_reasons",
        "temperature_spike",
        "pressure_spike",
        "humidity_spike",
        "temperature_flatline",
        "pressure_flatline",
        "humidity_flatline",
        "missing_flag",
        "gap_flag",
    ]
    for key in required_keys:
        assert key in d, f"Missing required QC schema field: {key}"

    # Verify flags do not classify as sensor fault
    assert d["qc_flag"] in ["PASSED", "SUSPECT", "MISSING", "GAP"]


# ==============================================================================
# TARGETED REAL DATASET TEST: 2016-09-09 17:00 Anomaly
# ==============================================================================

def test_known_anomaly_2016_09_09_17_00(default_qc: RuleBasedQC):
    """SPECIFIC TEST REQUIREMENT:
    Tests the observation at 2016-09-09 17:00 where temperature is 41.6°C
    and the previous temperature is -22.2°C.
    """
    cleaned_parquet = settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet"
    if not cleaned_parquet.exists():
        pytest.skip("Processed dataset not yet generated.")

    df = pd.read_parquet(cleaned_parquet)
    target_ts = pd.to_datetime("2016-09-09 17:00", utc=True)

    # Extract 6-hour window around the target anomaly
    window = df[
        (df["timestamp"] >= target_ts - pd.Timedelta(hours=3))
        & (df["timestamp"] <= target_ts + pd.Timedelta(hours=3))
    ].copy()

    # Process through Rule-Based QC
    qc_df = default_qc.process_dataframe(window)

    # Locate the target observation at 17:00
    target_row = qc_df[qc_df["timestamp"] == target_ts.isoformat()].iloc[0]

    # Verify input values
    assert target_row["temperature"] == pytest.approx(41.6)

    # Verify previous row (16:00)
    prev_row = qc_df[qc_df["timestamp"] == (target_ts - pd.Timedelta(hours=1)).isoformat()].iloc[0]
    assert prev_row["temperature"] == pytest.approx(-22.2)

    # 1. Temperature spike flag must be True (63.8°C / hr jump)
    assert bool(target_row["temperature_spike"]) is True

    # 2. Humidity spike flag must be True (jump from 39% to 100%)
    assert bool(target_row["humidity_spike"]) is True

    # 3. Overall QC flag must be SUSPECT (NOT classified as sensor fault)
    assert target_row["qc_flag"] == "SUSPECT"

    # 4. Reasons must cite both plausibility and temperature spike
    reasons_str = " ".join(target_row["qc_reasons"])
    assert "temperature_spike" in reasons_str
    assert "temperature_plausibility_violation" in reasons_str
    assert "41.60 > 25.00" in reasons_str

    # Verify the previous normal row at 16:00
    assert bool(prev_row["temperature_spike"]) is False
    assert prev_row["qc_flag"] == "PASSED"
