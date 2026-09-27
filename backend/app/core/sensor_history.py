"""Sensor Historical Health Tracking Engine for SkyGuard AI.

Maintains running historical statistics, reliability metrics, and operational
health index for each meteorological sensor (Temperature, Pressure, Humidity):
- Tracks recent fault/suspect frequency over multiple rolling time windows (24h, 7d, 30d).
- Monitors sensor noise variance and high-frequency jitter.
- Tracks CUSUM (cumulative sum) mean drift for gradual sensor calibration drift.
- Calculates an interpretable composite Sensor Health Index (0% to 100%).
- Provides degradation flags and alerts before full sensor failure occurs.
"""

from collections import deque
from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Union
import numpy as np

logger = logging.getLogger("skyguard.sensor_history")


@dataclass
class ParameterHealthRecord:
    """Historical health status for an individual sensor parameter (e.g. temperature)."""

    parameter_name: str
    total_observations: int = 0
    clean_observations: int = 0
    suspect_observations: int = 0
    missing_observations: int = 0

    # Rolling error frequencies
    error_rate_24h: float = 0.0
    error_rate_7d: float = 0.0
    error_rate_30d: float = 0.0

    # Degradation metrics
    noise_variance: float = 0.0
    cusum_drift_score: float = 0.0
    consecutive_flatlines: int = 0

    # Composite health score: 100.0 (pristine) -> 0.0 (defunct/failed)
    health_index: float = 100.0
    status: str = "HEALTHY"  # "HEALTHY", "DEGRADING", "MAINTENANCE_REQUIRED", "FAILED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "total_observations": self.total_observations,
            "clean_observations": self.clean_observations,
            "suspect_observations": self.suspect_observations,
            "missing_observations": self.missing_observations,
            "error_rate_24h": round(self.error_rate_24h, 4),
            "error_rate_7d": round(self.error_rate_7d, 4),
            "error_rate_30d": round(self.error_rate_30d, 4),
            "noise_variance": round(self.noise_variance, 4),
            "cusum_drift_score": round(self.cusum_drift_score, 4),
            "consecutive_flatlines": self.consecutive_flatlines,
            "health_index": round(self.health_index, 1),
            "status": self.status,
        }


@dataclass
class StationHealthSummary:
    """Consolidated historical health assessment for an Automatic Weather Station."""

    station_id: str
    overall_health_index: float  # 0 to 100%
    overall_status: str  # "OPERATIONAL", "DEGRADED", "CRITICAL_ATTENTION"
    parameters: Dict[str, ParameterHealthRecord] = field(default_factory=dict)
    active_alerts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "station_id": self.station_id,
            "overall_health_index": round(self.overall_health_index, 1),
            "overall_status": self.overall_status,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "active_alerts": self.active_alerts,
        }


class ParameterHistoryTracker:
    """Tracks state and rolling metrics for a single sensor parameter."""

    def __init__(
        self,
        parameter_name: str,
        window_24h: int = 24,
        window_7d: int = 168,
        window_30d: int = 720,
        cusum_threshold: float = 5.0,
        drift_slack: float = 0.5,
    ) -> None:
        self.parameter_name = parameter_name
        self.window_24h = window_24h
        self.window_7d = window_7d
        self.window_30d = window_30d
        self.cusum_threshold = cusum_threshold
        self.drift_slack = drift_slack

        # Rolling ring buffers of boolean quality status: True = error/suspect, False = clean
        self._history_24h: deque = deque(maxlen=window_24h)
        self._history_7d: deque = deque(maxlen=window_7d)
        self._history_30d: deque = deque(maxlen=window_30d)

        # Buffer of numerical differences for variance/jitter tracking
        self._diff_buffer: deque = deque(maxlen=window_24h)
        self._last_val: Optional[float] = None

        # Cumulative counters
        self.total_observations: int = 0
        self.clean_observations: int = 0
        self.suspect_observations: int = 0
        self.missing_observations: int = 0
        self.consecutive_flatlines: int = 0

        # CUSUM positive and negative accumulators for drift detection
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0
        self._rolling_mean: float = 0.0
        self._rolling_std: float = 1.0

    def update(
        self,
        value: Optional[float],
        is_suspect: bool = False,
        is_missing: bool = False,
        is_flatline: bool = False,
    ) -> ParameterHealthRecord:
        """Updates tracker with a new hourly observation."""
        self.total_observations += 1

        is_error = is_suspect or is_missing

        if is_missing:
            self.missing_observations += 1
        elif is_suspect:
            self.suspect_observations += 1
        else:
            self.clean_observations += 1

        if is_flatline:
            self.consecutive_flatlines += 1
        else:
            self.consecutive_flatlines = 0

        # Update rolling boolean history
        self._history_24h.append(is_error)
        self._history_7d.append(is_error)
        self._history_30d.append(is_error)

        # Update noise and variance tracking
        if value is not None:
            if self._last_val is not None:
                step = value - self._last_val
                self._diff_buffer.append(step)

                # Update CUSUM if clean
                if not is_suspect:
                    z = step / max(self._rolling_std, 0.1)
                    self._cusum_pos = max(0.0, self._cusum_pos + z - self.drift_slack)
                    self._cusum_neg = max(0.0, self._cusum_neg - z - self.drift_slack)
            self._last_val = value

        # Compute error rates
        err_24h = sum(self._history_24h) / max(len(self._history_24h), 1)
        err_7d = sum(self._history_7d) / max(len(self._history_7d), 1)
        err_30d = sum(self._history_30d) / max(len(self._history_30d), 1)

        # Compute variance of high-frequency steps
        variance = float(np.var(self._diff_buffer)) if len(self._diff_buffer) > 2 else 0.0

        # Compute CUSUM drift score
        cusum_drift = max(self._cusum_pos, self._cusum_neg)

        # Calculate composite health index (100 down to 0)
        # Weighting: 24h error rate (40%), 7d error rate (30%), 30d error rate (15%), CUSUM / flatline (15%)
        penalty = 0.0
        penalty += (err_24h * 40.0)
        penalty += (err_7d * 30.0)
        penalty += (err_30d * 15.0)

        if self.consecutive_flatlines > 3:
            penalty += min(20.0, self.consecutive_flatlines * 3.0)

        if cusum_drift > self.cusum_threshold:
            penalty += min(15.0, (cusum_drift - self.cusum_threshold) * 2.0)

        health_index = max(0.0, min(100.0, 100.0 - penalty))

        # Status categorization
        if health_index >= 85.0:
            status = "HEALTHY"
        elif health_index >= 60.0:
            status = "DEGRADING"
        elif health_index >= 30.0:
            status = "MAINTENANCE_REQUIRED"
        else:
            status = "FAILED"

        return ParameterHealthRecord(
            parameter_name=self.parameter_name,
            total_observations=self.total_observations,
            clean_observations=self.clean_observations,
            suspect_observations=self.suspect_observations,
            missing_observations=self.missing_observations,
            error_rate_24h=err_24h,
            error_rate_7d=err_7d,
            error_rate_30d=err_30d,
            noise_variance=variance,
            cusum_drift_score=cusum_drift,
            consecutive_flatlines=self.consecutive_flatlines,
            health_index=health_index,
            status=status,
        )


class SensorHealthTracker:
    """Multi-parameter sensor health monitoring engine for an AWS station."""

    def __init__(self, station_id: str = "AWS-MAITRI-89514") -> None:
        self.station_id = station_id
        self.trackers: Dict[str, ParameterHistoryTracker] = {
            "temperature": ParameterHistoryTracker("temperature"),
            "pressure": ParameterHistoryTracker("pressure"),
            "humidity": ParameterHistoryTracker("humidity"),
        }

    def update_observation(
        self,
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        qc_reasons: Optional[List[str]] = None,
        is_missing: bool = False,
    ) -> StationHealthSummary:
        """Processes an incoming observation and updates health status across all sensors."""
        reasons = qc_reasons or []
        reasons_lower = [r.lower() for r in reasons]

        # Check parameter specific flags from reasons
        t_suspect = any("temp" in r or "temperature" in r for r in reasons_lower)
        p_suspect = any("press" in r or "pressure" in r for r in reasons_lower)
        h_suspect = any("humid" in r or "rh" in r for r in reasons_lower)

        t_flatline = any("temperature" in r and "flatline" in r for r in reasons_lower)
        p_flatline = any("pressure" in r and "flatline" in r for r in reasons_lower)
        h_flatline = any("humidity" in r and "flatline" in r for r in reasons_lower)

        # Update each tracker
        rec_t = self.trackers["temperature"].update(
            value=temperature,
            is_suspect=t_suspect,
            is_missing=temperature is None or is_missing,
            is_flatline=t_flatline,
        )
        rec_p = self.trackers["pressure"].update(
            value=pressure,
            is_suspect=p_suspect,
            is_missing=pressure is None or is_missing,
            is_flatline=p_flatline,
        )
        rec_h = self.trackers["humidity"].update(
            value=humidity,
            is_suspect=h_suspect,
            is_missing=humidity is None or is_missing,
            is_flatline=h_flatline,
        )

        param_records = {
            "temperature": rec_t,
            "pressure": rec_p,
            "humidity": rec_h,
        }

        # Overall health index is the minimum/weighted across primary parameters
        overall_health = (rec_t.health_index * 0.4 + rec_p.health_index * 0.4 + rec_h.health_index * 0.2)
        # If any single sensor has completely failed, station status degrades significantly
        min_health = min(rec_t.health_index, rec_p.health_index, rec_h.health_index)

        alerts = []
        for name, rec in param_records.items():
            if rec.status == "DEGRADING":
                alerts.append(f"Sensor [{name}] degrading (Health: {rec.health_index:.1f}%, 24h error rate: {rec.error_rate_24h*100:.1f}%)")
            elif rec.status == "MAINTENANCE_REQUIRED":
                alerts.append(f"Sensor [{name}] requires maintenance (Health: {rec.health_index:.1f}%)")
            elif rec.status == "FAILED":
                alerts.append(f"Sensor [{name}] has FAILED (Health: {rec.health_index:.1f}%)")

        if overall_health >= 80.0 and min_health >= 60.0:
            overall_status = "OPERATIONAL"
        elif overall_health >= 50.0 and min_health >= 30.0:
            overall_status = "DEGRADED"
        else:
            overall_status = "CRITICAL_ATTENTION"

        return StationHealthSummary(
            station_id=self.station_id,
            overall_health_index=overall_health,
            overall_status=overall_status,
            parameters=param_records,
            active_alerts=alerts,
        )

    def get_parameter_health(self, parameter_name: str) -> Optional[ParameterHealthRecord]:
        """Returns the current health status of a specific parameter."""
        tracker = self.trackers.get(parameter_name)
        if tracker is None:
            return None
        # Return record derived from current state
        err_24h = sum(tracker._history_24h) / max(len(tracker._history_24h), 1)
        err_7d = sum(tracker._history_7d) / max(len(tracker._history_7d), 1)
        err_30d = sum(tracker._history_30d) / max(len(tracker._history_30d), 1)
        variance = float(np.var(tracker._diff_buffer)) if len(tracker._diff_buffer) > 2 else 0.0
        cusum_drift = max(tracker._cusum_pos, tracker._cusum_neg)

        penalty = (err_24h * 40.0) + (err_7d * 30.0) + (err_30d * 15.0)
        if tracker.consecutive_flatlines > 3:
            penalty += min(20.0, tracker.consecutive_flatlines * 3.0)
        if cusum_drift > tracker.cusum_threshold:
            penalty += min(15.0, (cusum_drift - tracker.cusum_threshold) * 2.0)

        health_index = max(0.0, min(100.0, 100.0 - penalty))

        if health_index >= 85.0:
            status = "HEALTHY"
        elif health_index >= 60.0:
            status = "DEGRADING"
        elif health_index >= 30.0:
            status = "MAINTENANCE_REQUIRED"
        else:
            status = "FAILED"

        return ParameterHealthRecord(
            parameter_name=parameter_name,
            total_observations=tracker.total_observations,
            clean_observations=tracker.clean_observations,
            suspect_observations=tracker.suspect_observations,
            missing_observations=tracker.missing_observations,
            error_rate_24h=err_24h,
            error_rate_7d=err_7d,
            error_rate_30d=err_30d,
            noise_variance=variance,
            cusum_drift_score=cusum_drift,
            consecutive_flatlines=tracker.consecutive_flatlines,
            health_index=health_index,
            status=status,
        )
