"""16-Feature Isolation Forest Anomaly Detection Engine for SkyGuard AI.

Integrated from finalized notebook SkyGuardAI_cleaned_final.ipynb:
- 16 meteorological, dynamic, rolling, and temporal cyclic features.
- StandardScaler fitted on notebook baseline partition.
- Pre-trained Isolation Forest model serialized via joblib.
- Outputs decision scores, normalized [0, 1] anomaly evidence scores, and boolean anomaly flags.
"""

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from backend.app.config import settings

logger = logging.getLogger("skyguard.isolation_forest")

DEFAULT_MODEL_PATH = settings.DATA_DIR / "models" / "isolation_forest.joblib"
DEFAULT_SCALER_PATH = settings.DATA_DIR / "models" / "iforest_scaler.joblib"
DEFAULT_META_PATH = settings.DATA_DIR / "models" / "iforest_metadata.json"


@dataclass
class IForestConfig:
    """Configurable hyperparameters and 16-feature definitions from notebook."""

    contamination: float = 0.05
    n_estimators: int = 100
    random_state: int = 42

    feature_names: List[str] = field(
        default_factory=lambda: [
            "TEMPERATURE",
            "PRESSURE",
            "HUMIDITY",
            "TEMP_CHANGE",
            "PRESSURE_CHANGE",
            "HUMIDITY_CHANGE",
            "TEMP_ROLLING_MEAN_3H",
            "TEMP_ROLLING_STD_3H",
            "PRESSURE_ROLLING_MEAN_3H",
            "PRESSURE_ROLLING_STD_3H",
            "HUMIDITY_ROLLING_MEAN_3H",
            "HUMIDITY_ROLLING_STD_3H",
            "HOUR_SIN",
            "HOUR_COS",
            "DAY_SIN",
            "DAY_COS",
        ]
    )


def extract_iforest_features(
    df: pd.DataFrame,
    config: Optional[IForestConfig] = None,
) -> Tuple[pd.DataFrame, pd.Series]:
    """Extracts 16 meteorological, dynamic, rolling, and temporal cyclic features.

    Matches notebook SkyGuardAI_cleaned_final.ipynb feature extraction pipeline exactly.
    """
    cfg = config or IForestConfig()
    work = df.copy()

    # Standardize column naming to match notebook expectations
    if "temperature" in work.columns and "TEMPERATURE" not in work.columns:
        work["TEMPERATURE"] = work["temperature"]
    if "pressure" in work.columns and "PRESSURE" not in work.columns:
        work["PRESSURE"] = work["pressure"]
    if "relative_humidity" in work.columns and "HUMIDITY" not in work.columns:
        work["HUMIDITY"] = work["relative_humidity"]
    elif "humidity" in work.columns and "HUMIDITY" not in work.columns:
        work["HUMIDITY"] = work["humidity"]
    if "timestamp" in work.columns and "TIMESTAMP" not in work.columns:
        work["TIMESTAMP"] = work["timestamp"]

    work["TIMESTAMP"] = pd.to_datetime(work["TIMESTAMP"], utc=True)
    work = work.sort_values(by="TIMESTAMP").reset_index(drop=True)

    # Hourly differences
    work["TIME_DIFF"] = work["TIMESTAMP"].diff()
    work["TEMP_CHANGE"] = work["TEMPERATURE"].diff()
    work["PRESSURE_CHANGE"] = work["PRESSURE"].diff()
    work["HUMIDITY_CHANGE"] = work["HUMIDITY"].diff()

    # Step gap validation: reset difference if time gap > 1h
    valid_hour = work["TIME_DIFF"] == pd.Timedelta(hours=1)
    work.loc[~valid_hour, ["TEMP_CHANGE", "PRESSURE_CHANGE", "HUMIDITY_CHANGE"]] = np.nan

    work["TEMP_CHANGE"] = work["TEMP_CHANGE"].fillna(0.0)
    work["PRESSURE_CHANGE"] = work["PRESSURE_CHANGE"].fillna(0.0)
    work["HUMIDITY_CHANGE"] = work["HUMIDITY_CHANGE"].fillna(0.0)

    # 3-Hour Causal Rolling Statistics
    for var_short, source_col in [("TEMP", "TEMPERATURE"), ("PRESSURE", "PRESSURE"), ("HUMIDITY", "HUMIDITY")]:
        work[f"{var_short}_ROLLING_MEAN_3H"] = work[source_col].rolling(3, min_periods=1).mean()
        work[f"{var_short}_ROLLING_STD_3H"] = work[source_col].rolling(3, min_periods=1).std().fillna(0.0)

    # Temporal Cyclic Features
    work["HOUR"] = work["TIMESTAMP"].dt.hour
    work["DAY_OF_YEAR"] = work["TIMESTAMP"].dt.dayofyear

    work["HOUR_SIN"] = np.sin(2 * np.pi * work["HOUR"] / 24.0)
    work["HOUR_COS"] = np.cos(2 * np.pi * work["HOUR"] / 24.0)
    work["DAY_SIN"] = np.sin(2 * np.pi * work["DAY_OF_YEAR"] / 365.25)
    work["DAY_COS"] = np.cos(2 * np.pi * work["DAY_OF_YEAR"] / 365.25)

    features_df = work[cfg.feature_names].copy()
    valid_mask = ~features_df.isna().any(axis=1)

    return features_df, valid_mask


class AWSIsolationForestDetector:
    """Production Isolation Forest anomaly evidence generator for AWS observations."""

    def __init__(
        self,
        config: Optional[IForestConfig] = None,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        meta_path: Optional[Path] = None,
    ) -> None:
        self.config = config or IForestConfig()
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.scaler_path = Path(scaler_path or DEFAULT_SCALER_PATH)
        self.meta_path = Path(meta_path or DEFAULT_META_PATH)

        self.model: Optional[IsolationForest] = None
        self.scaler: Optional[StandardScaler] = None
        self.is_fitted: bool = False
        self.calibration_min_score: float = -0.5
        self.calibration_max_score: float = 0.5

    def fit(
        self,
        train_df: pd.DataFrame,
        save_artifacts: bool = True,
    ) -> "AWSIsolationForestDetector":
        """Fits StandardScaler and IsolationForest strictly on training partition."""
        features_df, valid_mask = extract_iforest_features(train_df, self.config)
        X_train_raw = features_df[valid_mask]

        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train_raw)

        self.model = IsolationForest(
            contamination=self.config.contamination,
            n_estimators=self.config.n_estimators,
            random_state=self.config.random_state,
            n_jobs=-1,
        )
        self.model.fit(X_train_scaled)
        self.is_fitted = True

        train_scores = self.model.decision_function(X_train_scaled)
        self.calibration_min_score = float(np.percentile(train_scores, 0.5))
        self.calibration_max_score = float(np.percentile(train_scores, 99.5))

        if save_artifacts:
            self.save()
        return self

    def predict_features(
        self,
        features_df: pd.DataFrame,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Runs inference on prepared 16-feature matrix."""
        if not self.is_fitted or self.model is None or self.scaler is None:
            self.load()

        X_scaled = self.scaler.transform(features_df)

        raw_scores = self.model.decision_function(X_scaled)
        preds = self.model.predict(X_scaled)
        anomaly_flags = preds == -1

        denom = max(self.calibration_max_score - self.calibration_min_score, 1e-6)
        norm_scores = (self.calibration_max_score - raw_scores) / denom
        norm_scores = np.clip(norm_scores, 0.0, 1.0)

        return raw_scores, norm_scores, anomaly_flags

    def transform_dataframe(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Applies Isolation Forest anomaly detection to a full DataFrame."""
        orig_index = df.index
        work = df.copy().reset_index(drop=True)
        features_df, valid_mask = extract_iforest_features(work, self.config)

        work["iforest_decision_score"] = np.nan
        work["iforest_anomaly_score"] = np.nan
        work["iforest_anomaly_flag"] = False
        work["iforest_valid_feature"] = valid_mask.values

        if valid_mask.any():
            valid_features = features_df[valid_mask]
            raw_scores, norm_scores, flags = self.predict_features(valid_features)

            work.loc[valid_mask.values, "iforest_decision_score"] = raw_scores
            work.loc[valid_mask.values, "iforest_anomaly_score"] = norm_scores
            work.loc[valid_mask.values, "iforest_anomaly_flag"] = flags

        work.index = orig_index
        return work

    def save(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        meta_path: Optional[Path] = None,
    ) -> Tuple[Path, Path, Path]:
        """Serializes model, scaler, and metadata artifacts."""
        m_path = Path(model_path or self.model_path)
        s_path = Path(scaler_path or self.scaler_path)
        met_path = Path(meta_path or self.meta_path)

        m_path.parent.mkdir(parents=True, exist_ok=True)

        joblib.dump(self.model, m_path)
        joblib.dump(self.scaler, s_path)

        metadata = {
            "model_type": "IsolationForest",
            "source": "SkyGuardAI_cleaned_final.ipynb",
            "is_fitted": self.is_fitted,
            "contamination": self.config.contamination,
            "n_estimators": self.config.n_estimators,
            "calibration_min_score": self.calibration_min_score,
            "calibration_max_score": self.calibration_max_score,
            "feature_names": self.config.feature_names,
            "scaler_type": "StandardScaler",
        }

        with open(met_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return m_path, s_path, met_path

    def load(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        meta_path: Optional[Path] = None,
    ) -> "AWSIsolationForestDetector":
        """Loads serialized model, scaler, and metadata artifacts from disk."""
        m_path = Path(model_path or self.model_path)
        s_path = Path(scaler_path or self.scaler_path)
        met_path = Path(meta_path or self.meta_path)

        if not m_path.exists() or not s_path.exists():
            raise FileNotFoundError(f"Artifacts not found at {m_path} and {s_path}")

        self.model = joblib.load(m_path)
        self.scaler = joblib.load(s_path)

        if met_path.exists():
            with open(met_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                self.calibration_min_score = meta.get("calibration_min_score", -0.5)
                self.calibration_max_score = meta.get("calibration_max_score", 0.5)
                self.config.contamination = meta.get("contamination", self.config.contamination)
                if "feature_names" in meta:
                    self.config.feature_names = meta["feature_names"]

        self.is_fitted = True
        return self

    def load_model(self, *args, **kwargs):
        return self.load(*args, **kwargs)


IsolationForestDetector = AWSIsolationForestDetector
