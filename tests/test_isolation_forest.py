"""Unit tests for 16-feature Isolation Forest anomaly detection engine.

Validates:
- 16-feature extraction and segment boundary handling.
- StandardScaler and pre-trained artifact loading from notebook.
- Anomaly score calibration to [0, 1].
- Model serialization and deserialization.
- Benchmark verification of 2016-09-09 17:00 spike detection.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backend.app.config import settings
from backend.app.core.ml_isolation_forest import (
    AWSIsolationForestDetector,
    IForestConfig,
    extract_iforest_features,
)


@pytest.fixture
def synthetic_aws_df() -> pd.DataFrame:
    """Generates 200 synthetic hourly AWS records."""
    np.random.seed(42)
    n = 200
    timestamps = pd.date_range("2015-01-01 00:00", periods=n, freq="h", tz="UTC")

    temps = -15.0 + np.sin(np.linspace(0, 10, n)) * 5.0 + np.random.normal(0, 0.5, n)
    pressures = 980.0 + np.cos(np.linspace(0, 5, n)) * 8.0 + np.random.normal(0, 0.3, n)
    humidities = 55.0 + np.sin(np.linspace(0, 8, n)) * 15.0 + np.random.normal(0, 1.0, n)
    humidities = np.clip(humidities, 20.0, 95.0)

    # Inject one obvious multivariate spike outlier at index 150
    temps[150] = 35.0  # Impossible Antarctic temperature
    humidities[150] = 99.0

    df = pd.DataFrame({
        "timestamp": timestamps,
        "temperature": temps,
        "pressure": pressures,
        "relative_humidity": humidities,
    })
    return df


def test_extract_iforest_features_shape_and_columns(synthetic_aws_df: pd.DataFrame):
    """Verifies that all 16 expected features are generated."""
    cfg = IForestConfig()
    features_df, valid_mask = extract_iforest_features(synthetic_aws_df, cfg)

    assert len(features_df) == len(synthetic_aws_df)
    assert len(features_df.columns) == 16
    assert set(cfg.feature_names) == set(features_df.columns)
    assert valid_mask.sum() > 150


def test_feature_extraction_respects_segments():
    """Verifies that step differences and rolling stats reset across gap-induced segments."""
    ts = pd.to_datetime([
        "2015-01-01 00:00:00+00:00",
        "2015-01-01 01:00:00+00:00",
        "2015-01-01 02:00:00+00:00",
        "2015-01-01 07:00:00+00:00",  # Gap of 5h
        "2015-01-01 08:00:00+00:00",
    ])
    df = pd.DataFrame({
        "timestamp": ts,
        "temperature": [10.0, 11.0, 12.0, 25.0, 26.0],
        "pressure": [1000.0, 1000.5, 1001.0, 990.0, 990.5],
        "relative_humidity": [50.0, 52.0, 54.0, 70.0, 72.0],
    })
    features_df, _ = extract_iforest_features(df)

    assert features_df.loc[3, "TEMP_CHANGE"] == 0.0


def test_detector_loading_and_predict(synthetic_aws_df: pd.DataFrame):
    """Verifies loading pre-trained 16-feature model and score bounds."""
    detector = AWSIsolationForestDetector()
    detector.load()

    assert detector.is_fitted is True

    res_df = detector.transform_dataframe(synthetic_aws_df)
    assert "iforest_decision_score" in res_df.columns
    assert "iforest_anomaly_score" in res_df.columns
    assert "iforest_anomaly_flag" in res_df.columns

    scores = res_df["iforest_anomaly_score"].dropna()
    assert (scores >= 0.0).all()
    assert (scores <= 1.0).all()

    spike_score = res_df.loc[150, "iforest_anomaly_score"]
    assert spike_score > 0.5
    assert bool(res_df.loc[150, "iforest_anomaly_flag"]) is True


def test_known_real_anomaly_isolation_forest_detection():
    """Validates Isolation Forest detection on real 2016-09-09 17:00 target anomaly."""
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
        pytest.skip("Target timestamp not found in CSV.")

    idx = target_matches.index[0]
    slice_df = df.iloc[max(0, idx-50):idx+1].copy()

    detector = AWSIsolationForestDetector()
    detector.load()

    test_res = detector.transform_dataframe(slice_df)
    target_row = test_res[test_res["TIMESTAMP"] == target_ts].iloc[0]

    assert bool(target_row["iforest_anomaly_flag"]) is True
    assert target_row["iforest_anomaly_score"] > 0.50
