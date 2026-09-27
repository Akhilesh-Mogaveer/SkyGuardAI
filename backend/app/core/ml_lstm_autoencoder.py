"""TensorFlow/Keras LSTM Autoencoder Anomaly Detection Engine for SkyGuard AI.

Integrated from finalized notebook SkyGuardAI_cleaned_final.ipynb:
- 24-hour sequence windowing over T, P, RH parameters.
- StandardScaler fitted on notebook baseline partition.
- Pre-trained Keras LSTM Autoencoder model loaded via tf.keras.models.load_model.
- Empirically derived anomaly threshold (0.07097852191878912).
"""

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler

from backend.app.config import settings

logger = logging.getLogger("skyguard.lstm_autoencoder")

DEFAULT_MODEL_PATH = settings.DATA_DIR / "models" / "lstm_autoencoder.keras"
DEFAULT_SCALER_PATH = settings.DATA_DIR / "models" / "lstm_scaler.joblib"
DEFAULT_THRESH_PATH = settings.DATA_DIR / "models" / "lstm_threshold.joblib"
DEFAULT_META_PATH = settings.DATA_DIR / "models" / "lstm_metadata.json"


@dataclass
class LSTMConfig:
    """Hyperparameters and configuration for the LSTM Autoencoder."""

    window_size: int = 24  # 24 consecutive hourly timesteps
    input_dim: int = 3  # Temperature, Pressure, Relative Humidity
    threshold: float = 0.07097852191878912
    target_columns: List[str] = field(
        default_factory=lambda: ["TEMPERATURE", "PRESSURE", "HUMIDITY"]
    )


def create_continuous_sequences(
    df: pd.DataFrame,
    window_size: int = 24,
    target_columns: Optional[List[str]] = None,
    max_gap_hours: float = settings.MAX_STEP_RATE_GAP_HOURS,
) -> Tuple[np.ndarray, List[pd.Timestamp], List[int]]:
    """Generates multivariate sliding sequence windows strictly within continuous segments."""
    cols = list(target_columns or ["TEMPERATURE", "PRESSURE", "HUMIDITY"])
    work = df.copy()

    # Normalize column names
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

    if "segment_id" not in work.columns:
        dt = work["TIMESTAMP"].diff().dt.total_seconds() / 3600.0
        work["segment_id"] = (dt > max_gap_hours).cumsum().astype(int)

    sequences: List[np.ndarray] = []
    target_timestamps: List[pd.Timestamp] = []
    target_indices: List[int] = []

    for seg_id, seg_df in work.groupby("segment_id"):
        if len(seg_df) < window_size:
            continue

        data_vals = seg_df[cols].values
        ts_vals = seg_df["TIMESTAMP"].values
        idx_vals = seg_df.index.values

        for i in range(len(seg_df) - window_size + 1):
            window = data_vals[i : i + window_size]
            if np.isnan(window).any():
                continue

            sequences.append(window)
            target_timestamps.append(pd.Timestamp(ts_vals[i + window_size - 1]))
            target_indices.append(int(idx_vals[i + window_size - 1]))

    if not sequences:
        return np.empty((0, window_size, len(cols))), [], []

    return np.array(sequences, dtype=np.float32), target_timestamps, target_indices


class AWSLSTMDetector:
    """Manages inference and serialization for Keras LSTM Autoencoders."""

    def __init__(
        self,
        config: Optional[LSTMConfig] = None,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        thresh_path: Optional[Path] = None,
        meta_path: Optional[Path] = None,
    ) -> None:
        self.config = config or LSTMConfig()
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.scaler_path = Path(scaler_path or DEFAULT_SCALER_PATH)
        self.thresh_path = Path(thresh_path or DEFAULT_THRESH_PATH)
        self.meta_path = Path(meta_path or DEFAULT_META_PATH)

        self.model: Any = None
        self.scaler: Optional[StandardScaler] = None
        self.anomaly_threshold: float = self.config.threshold
        self.is_fitted: bool = False

    def load(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        thresh_path: Optional[Path] = None,
        meta_path: Optional[Path] = None,
    ) -> "AWSLSTMDetector":
        """Loads Keras model, scaler, threshold, and metadata."""
        m_path = Path(model_path or self.model_path)
        s_path = Path(scaler_path or self.scaler_path)
        t_path = Path(thresh_path or self.thresh_path)
        met_path = Path(meta_path or self.meta_path)

        if not m_path.exists() or not s_path.exists():
            raise FileNotFoundError(f"Artifacts not found at {m_path} and {s_path}")

        self.model = tf.keras.models.load_model(m_path)
        self.scaler = joblib.load(s_path)

        if t_path.exists():
            self.anomaly_threshold = float(joblib.load(t_path))
            self.config.threshold = self.anomaly_threshold

        if met_path.exists():
            with open(met_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                self.config.window_size = meta.get("sequence_length", self.config.window_size)
                self.config.input_dim = meta.get("input_dim", self.config.input_dim)
                if "anomaly_threshold" in meta:
                    self.anomaly_threshold = float(meta["anomaly_threshold"])
                    self.config.threshold = self.anomaly_threshold

        self.is_fitted = True
        return self

    def compute_reconstruction_errors(
        self,
        X_seq: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Calculates reconstruction errors, calibrated anomaly scores, and flags."""
        if not self.is_fitted or self.model is None or self.scaler is None:
            self.load()

        if len(X_seq) == 0:
            return np.empty(0), np.empty((0, self.config.input_dim)), np.empty(0), np.empty(0, dtype=bool)

        # Keras model inference
        recon = self.model.predict(X_seq, verbose=0)

        diff = X_seq - recon
        overall_mse = np.mean(diff ** 2, axis=(1, 2))
        channel_mse = np.mean(diff ** 2, axis=1)

        anomaly_flags = overall_mse > self.anomaly_threshold

        denom = max(self.anomaly_threshold, 1e-6)
        calibrated_scores = 1.0 - np.exp(-np.log(2.0) * (overall_mse / denom))
        calibrated_scores = np.clip(calibrated_scores, 0.0, 1.0)

        return overall_mse, channel_mse, calibrated_scores, anomaly_flags

    def transform_dataframe(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Applies Keras LSTM Autoencoder inference across continuous sequences in a DataFrame."""
        orig_index = df.index
        work = df.copy().reset_index(drop=True)
        work["lstm_reconstruction_error"] = np.nan
        work["lstm_anomaly_score"] = np.nan
        work["lstm_anomaly_flag"] = False
        work["lstm_temp_error"] = np.nan
        work["lstm_press_error"] = np.nan
        work["lstm_hum_error"] = np.nan

        X_raw, timestamps, target_indices = create_continuous_sequences(
            work,
            window_size=self.config.window_size,
            target_columns=self.config.target_columns,
        )

        if len(X_raw) == 0:
            work.index = orig_index
            return work

        # Scale using pre-fitted StandardScaler
        n_seq, w_len, n_dim = X_raw.shape
        X_flat = X_raw.reshape(-1, n_dim)
        X_scaled_flat = self.scaler.transform(X_flat)
        X_scaled = X_scaled_flat.reshape(n_seq, w_len, n_dim)

        overall_mse, channel_mse, scores, flags = self.compute_reconstruction_errors(X_scaled)

        work.loc[target_indices, "lstm_reconstruction_error"] = overall_mse
        work.loc[target_indices, "lstm_anomaly_score"] = scores
        work.loc[target_indices, "lstm_anomaly_flag"] = flags
        work.loc[target_indices, "lstm_temp_error"] = channel_mse[:, 0]
        work.loc[target_indices, "lstm_press_error"] = channel_mse[:, 1]
        work.loc[target_indices, "lstm_hum_error"] = channel_mse[:, 2]

        work.index = orig_index
        return work

    def load_model(self, *args, **kwargs):
        return self.load(*args, **kwargs)


LSTMAutoencoderDetector = AWSLSTMDetector
