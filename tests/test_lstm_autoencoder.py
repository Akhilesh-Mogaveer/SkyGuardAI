"""Unit tests for the Keras LSTM Autoencoder anomaly detection engine.

Validates:
- Strict continuous sequence generation (never crossing time gaps).
- Keras model inference and output dimensions.
- Saved threshold (0.07097852191878912) and sequence length 24.
- Artifact loading from data/models/.
- Benchmark verification of the 2016-09-09 17:00 spike anomaly.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backend.app.config import settings
from backend.app.core.ml_lstm_autoencoder import (
    AWSLSTMDetector,
    LSTMConfig,
    create_continuous_sequences,
)


@pytest.fixture
def synthetic_hourly_stream() -> pd.DataFrame:
    """Generates 120 continuous hourly synthetic observations."""
    np.random.seed(42)
    n = 120
    ts = pd.date_range("2015-01-01 00:00:00", periods=n, freq="h", tz="UTC")

    t = -10.0 + np.sin(np.linspace(0, 10, n)) * 5.0
    p = 980.0 + np.cos(np.linspace(0, 5, n)) * 10.0
    rh = 50.0 + np.sin(np.linspace(0, 8, n)) * 20.0

    return pd.DataFrame({
        "timestamp": ts,
        "temperature": t,
        "pressure": p,
        "relative_humidity": rh,
        "qc_flag": ["PASSED"] * n,
    })


def test_create_continuous_sequences_shape(synthetic_hourly_stream: pd.DataFrame):
    """Verifies that sliding window sequence generation yields correct tensor dimensions."""
    window_size = 24
    X_seq, timestamps, indices = create_continuous_sequences(
        synthetic_hourly_stream,
        window_size=window_size,
    )

    expected_count = len(synthetic_hourly_stream) - window_size + 1
    assert len(X_seq) == expected_count
    assert X_seq.shape == (expected_count, window_size, 3)
    assert len(timestamps) == expected_count
    assert len(indices) == expected_count


def test_sequences_never_cross_time_gaps():
    """CRITICAL REQUIREMENT: Sequences must NEVER be created across time gaps."""
    # 15 hours continuous, then 10 hour gap, then 15 hours continuous
    ts1 = pd.date_range("2015-01-01 00:00:00", periods=15, freq="h", tz="UTC")
    ts2 = pd.date_range("2015-01-02 01:00:00", periods=15, freq="h", tz="UTC")

    df1 = pd.DataFrame({"timestamp": ts1, "temperature": 0.0, "pressure": 1000.0, "relative_humidity": 50.0})
    df2 = pd.DataFrame({"timestamp": ts2, "temperature": 0.0, "pressure": 1000.0, "relative_humidity": 50.0})
    df = pd.concat([df1, df2]).reset_index(drop=True)

    # Window size of 20 hours
    X_seq, _, _ = create_continuous_sequences(df, window_size=20)
    assert len(X_seq) == 0

    # Window size of 10 hours
    X_seq10, timestamps10, _ = create_continuous_sequences(df, window_size=10)
    assert len(X_seq10) == 12


def test_keras_detector_loading_and_transform(synthetic_hourly_stream: pd.DataFrame):
    """Verifies loading pre-trained notebook Keras model and executing transform_dataframe."""
    detector = AWSLSTMDetector()
    detector.load()

    assert detector.is_fitted is True
    assert detector.anomaly_threshold == pytest.approx(0.07097852191878912)

    res_df = detector.transform_dataframe(synthetic_hourly_stream)
    assert "lstm_reconstruction_error" in res_df.columns
    assert "lstm_anomaly_score" in res_df.columns
    assert "lstm_anomaly_flag" in res_df.columns
    assert "lstm_temp_error" in res_df.columns


def test_known_anomaly_lstm_reconstruction_spike():
    """Validates that the 2016-09-09 17:00 spike causes a massive reconstruction error jump (> threshold)."""
    raw_csv = settings.DATA_DIR / "raw" / "imd_maitri.csv"
    if not raw_csv.exists():
        pytest.skip("IMD Maitri raw dataset not found.")

    df = pd.read_csv(raw_csv)
    df.columns = [c.upper() for c in df.columns]
    df.rename(columns={
        "AIR TEMPERATURE": "TEMPERATURE",
        "AIR PRESSURE": "PRESSURE",
        "RELATIVE HUMIDITY": "HUMIDITY"
    }, inplace=True)

    df["TIMESTAMP"] = pd.to_datetime(df["TIMESTAMP"], errors="coerce", utc=True)
    df = df.sort_values(by="TIMESTAMP").reset_index(drop=True)

    target_ts = pd.to_datetime("2016-09-09 17:00:00+00:00", utc=True)
    target_matches = df[df["TIMESTAMP"] == target_ts]
    if target_matches.empty:
        pytest.skip("Target timestamp 2016-09-09 17:00 not found in CSV.")

    idx = target_matches.index[0]
    slice_df = df.iloc[max(0, idx-50):idx+1].copy()

    detector = AWSLSTMDetector()
    detector.load()

    res = detector.transform_dataframe(slice_df)
    target_row = res[res["TIMESTAMP"] == target_ts]

    assert not target_row.empty
    r = target_row.iloc[0]
    assert r["lstm_reconstruction_error"] > detector.anomaly_threshold
    assert r["lstm_anomaly_flag"] is True or r["lstm_anomaly_flag"] == 1
