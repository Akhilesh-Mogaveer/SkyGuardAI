"""Unit tests for the preprocessing engine."""

import numpy as np
import pandas as pd
import pytest

from backend.app.core.preprocessing import (
    clean_missing_sentinels,
    compute_parameter_statistics,
    detect_duplicate_timestamps,
    detect_missing_values,
    detect_time_gaps,
    identify_continuous_segments,
    interpolate_small_gaps,
    parse_timestamps,
    preprocess_aws_dataframe,
    sort_chronologically,
    validate_required_columns,
)


@pytest.fixture
def raw_sample_df() -> pd.DataFrame:
    """Provides a synthetic raw DataFrame mirroring the IMD AWS schema."""
    return pd.DataFrame({
        "TimeStamp": [
            "1/1/2015 0:00",
            "1/1/2015 1:00",
            "1/1/2015 2:00",
            "1/1/2015 5:00",  # 3-hour gap
            "1/1/2015 6:00",
        ],
        "Air Temperature": [-10.5, -11.0, -999, -12.5, -13.0],
        "Air Pressure": [985.2, 984.8, 984.5, -999, 983.9],
        "Wind Speed": [15, 18, 16, 20, 22],
        "Wind Direction": [180, 190, 185, 200, 210],
        "Relative Humidity": [60, -999, 65, 70, -999],
    })


def test_validate_required_columns_success(raw_sample_df: pd.DataFrame):
    """Verifies that complete column schemas validate and canonicalize."""
    out = validate_required_columns(raw_sample_df, canonicalize=True)
    expected_cols = {"timestamp", "temperature", "pressure", "wind_speed", "wind_direction", "relative_humidity"}
    assert expected_cols.issubset(set(out.columns))


def test_validate_required_columns_failure():
    """Verifies that missing mandatory columns raise ValueError."""
    bad_df = pd.DataFrame({"TimeStamp": ["1/1/2015 0:00"], "Air Temperature": [5.0]})
    with pytest.raises(ValueError, match="Missing required columns"):
        validate_required_columns(bad_df)


def test_clean_missing_sentinels(raw_sample_df: pd.DataFrame):
    """Verifies that -999 values are cleanly replaced with np.nan."""
    canon_df = validate_required_columns(raw_sample_df, canonicalize=True)
    cleaned = clean_missing_sentinels(canon_df)

    assert np.isnan(cleaned.loc[2, "temperature"])
    assert np.isnan(cleaned.loc[3, "pressure"])
    assert np.isnan(cleaned.loc[1, "relative_humidity"])
    assert np.isnan(cleaned.loc[4, "relative_humidity"])
    assert cleaned.loc[0, "temperature"] == -10.5


def test_parse_timestamps_and_sort():
    """Verifies timestamp parsing and chronological ordering."""
    df = pd.DataFrame({
        "timestamp": ["1/1/2015 3:00", "1/1/2015 0:00", "1/1/2015 1:00"],
        "val": [3, 0, 1],
    })
    parsed = parse_timestamps(df, timestamp_col="timestamp")
    assert pd.api.types.is_datetime64_any_dtype(parsed["timestamp"])

    sorted_df = sort_chronologically(parsed, timestamp_col="timestamp")
    assert sorted_df["val"].tolist() == [0, 1, 3]


def test_detect_duplicate_timestamps():
    """Verifies detection and handling of duplicate timestamps."""
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2015-01-01 00:00", "2015-01-01 01:00", "2015-01-01 01:00", "2015-01-01 02:00"]),
        "temp": [1.0, 2.0, 2.5, 3.0],
    })
    dup_count, dup_rows, dedup_df = detect_duplicate_timestamps(df, timestamp_col="timestamp")
    assert dup_count == 1
    assert len(dup_rows) == 2  # both instances of 01:00 returned in dup_rows
    assert len(dedup_df) == 3


def test_detect_missing_values():
    """Verifies missing value counts and percentage metrics."""
    df = pd.DataFrame({
        "timestamp": pd.date_range("2015-01-01", periods=5, freq="h"),
        "temperature": [1.0, np.nan, np.nan, 2.0, 3.0],
        "pressure": [1000.0, 1001.0, 1002.0, 1003.0, 1004.0],
    })
    profile = detect_missing_values(df)
    assert profile["temperature"]["missing_count"] == 2
    assert profile["temperature"]["missing_pct"] == 40.0
    assert profile["temperature"]["max_consecutive_missing"] == 2
    assert profile["pressure"]["missing_count"] == 0


def test_detect_time_gaps():
    """Verifies detection of time gaps and gap duration calculation."""
    timestamps = pd.to_datetime([
        "2015-01-01 00:00",
        "2015-01-01 01:00",  # 1 hr step (normal)
        "2015-01-01 05:00",  # 4 hr gap (> 1 hr)
        "2015-01-01 06:00",  # 1 hr step (normal)
        "2015-01-02 06:00",  # 24 hr gap (> 1 hr)
    ])
    df = pd.DataFrame({"timestamp": timestamps, "val": range(5)})

    total_gaps, gaps_df, gap_stats = detect_time_gaps(df, nominal_freq_hours=1.0)
    assert total_gaps == 2
    assert len(gaps_df) == 2
    assert gaps_df.iloc[0]["duration_hours"] == 4.0
    assert gaps_df.iloc[0]["missing_steps"] == 3
    assert gaps_df.iloc[1]["duration_hours"] == 24.0
    assert gap_stats["max_gap_hours"] == 24.0


def test_identify_continuous_segments():
    """Verifies that continuous segments are labeled properly for LSTM windowing."""
    timestamps = pd.to_datetime([
        "2015-01-01 00:00",
        "2015-01-01 01:00",
        "2015-01-01 02:00",  # Segment 0 (3 steps)
        "2015-01-01 06:00",  # Gap of 4h -> Segment 1 begins
        "2015-01-01 07:00",  # Segment 1
    ])
    df = pd.DataFrame({"timestamp": timestamps, "val": range(5)})
    segmented = identify_continuous_segments(df, max_step_hours=1.0)

    assert "segment_id" in segmented.columns
    assert segmented["segment_id"].tolist() == [0, 0, 0, 1, 1]


def test_strict_non_interpolation_across_large_gaps():
    """CRITICAL REQUIREMENT: Verify values across large gaps are NEVER interpolated."""
    # Create sequence with 1-hour NaN gap (should fill if limit=2) and 5-hour NaN gap (must NOT fill)
    timestamps = pd.date_range("2015-01-01", periods=10, freq="h")
    temps = [
        10.0,
        np.nan,  # 1 isolated NaN (small gap -> eligible)
        12.0,
        np.nan,  # Start of 4 consecutive NaNs (large gap > 2)
        np.nan,
        np.nan,
        np.nan,
        20.0,
        21.0,
        22.0,
    ]
    df = pd.DataFrame({"timestamp": timestamps, "temperature": temps})

    # Apply small gap interpolation with strict limit of 2 steps
    interpolated = interpolate_small_gaps(df, max_gap_hours=2.0, target_columns=["temperature"])

    # Index 1 was an isolated 1-hour gap -> should be linearly interpolated
    assert not np.isnan(interpolated.loc[1, "temperature"])
    assert interpolated.loc[1, "temperature"] == pytest.approx(11.0)
    assert interpolated.loc[1, "is_interpolated"] is True or interpolated.loc[1, "is_interpolated"] == 1

    # Indices 5 and 6 are beyond the 2-step limit -> MUST REMAIN NaN
    assert np.isnan(interpolated.loc[5, "temperature"])
    assert np.isnan(interpolated.loc[6, "temperature"])


def test_compute_parameter_statistics():
    """Verifies computation of min, max, mean, std, quartiles."""
    df = pd.DataFrame({
        "temperature": [10.0, 20.0, 30.0, 40.0, 50.0],
        "pressure": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
    })
    stats = compute_parameter_statistics(df, parameters=["temperature", "pressure"])
    assert stats["temperature"]["min"] == 10.0
    assert stats["temperature"]["max"] == 50.0
    assert stats["temperature"]["median"] == 30.0
    assert stats["pressure"]["std"] == 0.0


def test_full_preprocessing_pipeline_integration(raw_sample_df: pd.DataFrame):
    """Verifies end-to-end preprocess_aws_dataframe function."""
    cleaned_df, audit = preprocess_aws_dataframe(raw_sample_df, interpolate_small=False)

    assert len(cleaned_df) == 5
    assert "timestamp" in cleaned_df.columns
    assert "temperature" in cleaned_df.columns
    assert "segment_id" in cleaned_df.columns
    assert audit["duplicate_timestamps"] == 0
    assert audit["total_gaps"] == 1  # 1/1/2015 2:00 to 5:00 is a 3h gap
    assert audit["continuous_segments_count"] == 2
