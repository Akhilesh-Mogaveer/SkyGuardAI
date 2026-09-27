"""Sensor Health Calculation Service for SkyGuard AI.

Calculates long-term sensor health scores and reliability metrics from historical observations:
- Configurable indicator weights: anomaly frequency, missing-data frequency, flatline frequency,
  repeated QC violations, and recent anomaly trend.
- Tracks trend momentum (comparing recent 24h window against baseline 30d window).
- Persists health evaluations into the `sensor_health` database schema.

STRICT DOMAIN INVARIANT:
The health score describes long-term sensor hardware reliability over time.
It MUST NOT automatically determine whether the current observation is faulty.
Observation classification is performed independently by the Evidence Fusion & Decision Engine.
"""

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from backend.app.config import settings
from backend.app.db.sensor_health_db import (
    SensorHealthDatabase,
    SensorHealthEntry,
    StationHealthSnapshot,
)

logger = logging.getLogger("skyguard.sensor_health_service")


@dataclass
class HealthIndicatorConfig:
    """Configurable weights and penalties for sensor health indicators."""

    anomaly_frequency_weight: float = 30.0  # Max penalty for 100% anomaly rate
    missing_frequency_weight: float = 25.0  # Max penalty for missing observations
    flatline_frequency_weight: float = 20.0  # Max penalty for sensor flatlines
    qc_violation_weight: float = 15.0       # Max penalty for QC rule violations
    recent_trend_weight: float = 10.0        # Max penalty for worsening anomaly trend

    recent_window_hours: int = 24            # Short-term window for trend comparison
    baseline_window_hours: int = 720         # 30-day long-term baseline window


class SensorHealthCalculationService:
    """Service for computing long-term sensor reliability metrics and health scores."""

    def __init__(
        self,
        config: Optional[HealthIndicatorConfig] = None,
        db: Optional[SensorHealthDatabase] = None,
    ) -> None:
        self.config = config or HealthIndicatorConfig()
        self.db = db or SensorHealthDatabase()

    def calculate_parameter_health(
        self,
        station_id: str,
        parameter_name: str,
        df_history: pd.DataFrame,
        timestamp: str,
    ) -> SensorHealthEntry:
        """Calculates long-term health metrics for a single sensor parameter over historical DataFrame.
        
        Expected DataFrame columns (if present):
        - 'timestamp' or DatetimeIndex
        - '{parameter_name}' (raw value)
        - '{parameter_name}_qc_flag' or 'qc_flag'
        - '{parameter_name}_anomaly' or 'anomaly_flag'
        - '{parameter_name}_flatline'
        """
        if df_history.empty:
            return SensorHealthEntry(
                id=None,
                timestamp=str(timestamp),
                station_id=station_id,
                parameter_name=parameter_name,
                health_index=100.0,
                status="HEALTHY",
                anomaly_frequency=0.0,
                missing_frequency=0.0,
                flatline_frequency=0.0,
                qc_violation_rate=0.0,
                recent_anomaly_trend=0.0,
                evaluation_window_hours=self.config.baseline_window_hours,
            )

        n_obs = len(df_history)

        # 1. Missing data frequency
        val_col = parameter_name if parameter_name in df_history.columns else None
        if val_col:
            missing_count = df_history[val_col].isna().sum()
        else:
            missing_count = 0
        missing_freq = float(missing_count / max(n_obs, 1))

        # 2. QC Violation Rate
        qc_col = f"{parameter_name}_qc_flag" if f"{parameter_name}_qc_flag" in df_history.columns else "qc_flag"
        if qc_col in df_history.columns:
            qc_violations = (df_history[qc_col] == "SUSPECT").sum()
        else:
            qc_violations = 0
        qc_rate = float(qc_violations / max(n_obs, 1))

        # 3. Flatline frequency
        flat_col = f"{parameter_name}_flatline" if f"{parameter_name}_flatline" in df_history.columns else None
        if flat_col and flat_col in df_history.columns:
            flatline_count = df_history[flat_col].astype(bool).sum()
        else:
            flatline_count = 0
        flatline_freq = float(flatline_count / max(n_obs, 1))

        # 4. Anomaly frequency over long-term window
        anom_col = f"{parameter_name}_anomaly" if f"{parameter_name}_anomaly" in df_history.columns else "anomaly_flag"
        if anom_col in df_history.columns:
            anom_count = df_history[anom_col].astype(bool).sum()
        else:
            anom_count = 0
        anomaly_freq = float(anom_count / max(n_obs, 1))

        # 5. Recent Anomaly Trend (Comparing recent 24h window vs baseline)
        if anom_col in df_history.columns and n_obs >= self.config.recent_window_hours:
            recent_24h_df = df_history.iloc[-self.config.recent_window_hours:]
            recent_anom_rate = float(recent_24h_df[anom_col].astype(bool).sum() / len(recent_24h_df))
            trend = round(recent_anom_rate - anomaly_freq, 4)
        else:
            trend = 0.0

        # 6. Composite Health Index Calculation
        # Penalty is weighted sum of indicator frequencies
        penalty = 0.0
        penalty += anomaly_freq * self.config.anomaly_frequency_weight
        penalty += missing_freq * self.config.missing_frequency_weight
        penalty += flatline_freq * self.config.flatline_frequency_weight
        penalty += qc_rate * self.config.qc_violation_weight

        # Only penalize positive trend (worsening anomaly momentum)
        if trend > 0:
            penalty += trend * self.config.recent_trend_weight

        health_index = float(np.clip(100.0 - penalty, 0.0, 100.0))

        # Categorize operational health status
        if health_index >= 85.0:
            status = "HEALTHY"
        elif health_index >= 65.0:
            status = "DEGRADING"
        elif health_index >= 35.0:
            status = "MAINTENANCE_REQUIRED"
        else:
            status = "FAILED"

        entry = SensorHealthEntry(
            id=None,
            timestamp=str(timestamp),
            station_id=station_id,
            parameter_name=parameter_name,
            health_index=health_index,
            status=status,
            anomaly_frequency=anomaly_freq,
            missing_frequency=missing_freq,
            flatline_frequency=flatline_freq,
            qc_violation_rate=qc_rate,
            recent_anomaly_trend=trend,
            evaluation_window_hours=n_obs,
        )

        # Save record into SQLite DB
        self.db.insert_parameter_health(entry)
        return entry

    def evaluate_station_health(
        self,
        station_id: str,
        df_history: pd.DataFrame,
        timestamp: str,
        parameters: Optional[List[str]] = None,
    ) -> StationHealthSnapshot:
        """Evaluates overall station health across parameters and persists snapshot."""
        params = parameters or ["temperature", "pressure", "humidity"]
        param_entries: Dict[str, SensorHealthEntry] = {}
        scores: Dict[str, float] = {}
        alerts: List[str] = []

        for p in params:
            entry = self.calculate_parameter_health(station_id, p, df_history, timestamp)
            param_entries[p] = entry
            scores[p] = entry.health_index

            if entry.status == "DEGRADING":
                alerts.append(f"Sensor [{p}] health degrading (Health: {entry.health_index:.1f}%, Trend: {entry.recent_anomaly_trend:+.2f})")
            elif entry.status == "MAINTENANCE_REQUIRED":
                alerts.append(f"Sensor [{p}] MAINTENANCE REQUIRED (Health: {entry.health_index:.1f}%)")
            elif entry.status == "FAILED":
                alerts.append(f"Sensor [{p}] FAILED (Health: {entry.health_index:.1f}%)")

        overall_health = float(np.mean(list(scores.values())))
        min_health = float(np.min(list(scores.values())))

        if overall_health >= 80.0 and min_health >= 60.0:
            overall_status = "OPERATIONAL"
        elif overall_health >= 50.0 and min_health >= 30.0:
            overall_status = "DEGRADED"
        else:
            overall_status = "CRITICAL_ATTENTION"

        snapshot = StationHealthSnapshot(
            id=None,
            timestamp=str(timestamp),
            station_id=station_id,
            overall_health_index=overall_health,
            overall_status=overall_status,
            parameter_scores=scores,
            active_alerts=alerts,
        )

        self.db.insert_station_snapshot(snapshot)
        return snapshot
