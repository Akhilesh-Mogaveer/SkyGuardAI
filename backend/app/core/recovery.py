"""Temporal & Spatial Data Recovery Estimator for SkyGuard AI.

Calculates estimated replacement values for anomalous or flagged meteorological parameters:
- Uses chronological neighboring observations (t-1 hour and t+1 hour) for linear/temporal interpolation.
- Preserves raw observation values without overwrite.
- Calculates recovery availability, method, and neighbor timestamps.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


PARAMETER_ALIASES = {
    "temperature": {"temperature", "air temperature", "temp"},
    "pressure": {"pressure", "air pressure", "barometric pressure", "press"},
    "humidity": {"humidity", "relative humidity", "relative_humidity", "rh"},
}

UNIT_BY_PARAMETER = {
    "temperature": "°C",
    "pressure": "hPa",
    "humidity": "%",
}


def _normalise_parameter_name(parameter_name: Optional[str]) -> Optional[str]:
    if parameter_name is None:
        return None
    candidate = str(parameter_name).strip().lower()
    for canonical, aliases in PARAMETER_ALIASES.items():
        if candidate == canonical or candidate in aliases:
            return canonical
    return None


def _parameter_column_name(dataset_df: pd.DataFrame, parameter_name: str) -> Optional[str]:
    canonical = _normalise_parameter_name(parameter_name)
    if canonical is None:
        return None

    aliases = {
        "temperature": ["temperature", "air temperature", "temp", "TEMPERATURE", "Air Temperature"],
        "pressure": ["pressure", "air pressure", "barometric pressure", "press", "PRESSURE", "Air Pressure"],
        "humidity": ["humidity", "relative humidity", "relative_humidity", "RH", "Relative Humidity"],
    }

    candidates = aliases.get(canonical, [canonical])
    for column in dataset_df.columns:
        if str(column).strip().lower() in {str(item).strip().lower() for item in candidates}:
            return column
    return canonical


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(value_float) or np.isinf(value_float):
        return None
    return value_float


def _timestamp_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        return str(value)
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class RecoveryEstimationResult:
    observed_value: Optional[float]
    estimated_value: Optional[float]
    recovery_parameter: Optional[str]
    recovery_status: str  # "AVAILABLE", "UNAVAILABLE", or "NOT_APPLICABLE"
    recovery_method: Optional[str]
    previous_observation_timestamp: Optional[str]
    next_observation_timestamp: Optional[str]
    message: str = ""
    unit: Optional[str] = None
    available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        estimated = round(self.estimated_value, 2) if self.estimated_value is not None else None
        return {
            "parameter": self.recovery_parameter,
            "recovery_parameter": self.recovery_parameter,
            "observed_value": self.observed_value,
            "observedValue": self.observed_value,
            "estimated_value": estimated,
            "estimatedValue": estimated,
            "unit": self.unit,
            "method": self.recovery_method,
            "recovery_method": self.recovery_method,
            "previous_timestamp": self.previous_observation_timestamp,
            "previous_observation_timestamp": self.previous_observation_timestamp,
            "next_timestamp": self.next_observation_timestamp,
            "next_observation_timestamp": self.next_observation_timestamp,
            "available": self.available or self.recovery_status == "AVAILABLE",
            "recovery_status": self.recovery_status,
            "message": self.message,
        }


class DataRecoveryEstimator:
    """Estimates replacement values for anomalous observations from historical/chronological context."""

    def estimate_recovery(
        self,
        timestamp: str,
        observed_value: Optional[float],
        parameter_name: str = "temperature",
        is_flagged: bool = True,
        dataset_df: Optional[pd.DataFrame] = None,
        recent_buffer: Optional[Any] = None,
    ) -> RecoveryEstimationResult:
        """Computes recovery estimation from dataset context or rolling observation history."""
        recovery_parameter = _normalise_parameter_name(parameter_name) or "temperature"
        unit = UNIT_BY_PARAMETER.get(recovery_parameter, "°C")

        if observed_value is None or not is_flagged:
            return RecoveryEstimationResult(
                observed_value=float(observed_value) if observed_value is not None else None,
                estimated_value=None,
                recovery_parameter=recovery_parameter,
                recovery_status="NOT_APPLICABLE",
                recovery_method=None,
                previous_observation_timestamp=None,
                next_observation_timestamp=None,
                message="Recovery not applicable — parameter is not flagged as anomalous." if is_flagged else "Recovery not applicable — observation is normal.",
                unit=unit,
                available=False,
            )

        if dataset_df is not None and not dataset_df.empty:
            try:
                dataset = dataset_df.copy()
                if "parsed_ts" not in dataset.columns:
                    ts_col = "timestamp" if "timestamp" in dataset.columns else ("TimeStamp" if "TimeStamp" in dataset.columns else dataset.columns[0])
                    dataset["parsed_ts"] = pd.to_datetime(dataset[ts_col], utc=True)

                target_ts = pd.to_datetime(timestamp, utc=True)
                matches = dataset[dataset["parsed_ts"] == target_ts]
                if matches.empty:
                    ts_str_short = target_ts.strftime("%Y-%m-%d %H:%M")
                    matches = dataset[dataset["parsed_ts"].dt.strftime("%Y-%m-%d %H:%M") == ts_str_short]

                if not matches.empty:
                    idx = matches.index[0]
                    if 0 < idx < len(dataset) - 1:
                        prev_row = dataset.iloc[idx - 1]
                        next_row = dataset.iloc[idx + 1]
                        col_name = _parameter_column_name(dataset, recovery_parameter)

                        prev_val = _coerce_float(prev_row.get(col_name, prev_row.get(recovery_parameter, None)))
                        next_val = _coerce_float(next_row.get(col_name, next_row.get(recovery_parameter, None)))

                        if prev_val is None or next_val is None:
                            return RecoveryEstimationResult(
                                observed_value=float(observed_value),
                                estimated_value=None,
                                recovery_parameter=recovery_parameter,
                                recovery_status="NOT_APPLICABLE",
                                recovery_method=None,
                                previous_observation_timestamp=None,
                                next_observation_timestamp=None,
                                message="Recovery not applicable — valid temporal neighbors are unavailable for this observation.",
                                unit=unit,
                                available=False,
                            )

                        if prev_val <= -100 or next_val <= -100:
                            return RecoveryEstimationResult(
                                observed_value=float(observed_value),
                                estimated_value=None,
                                recovery_parameter=recovery_parameter,
                                recovery_status="NOT_APPLICABLE",
                                recovery_method=None,
                                previous_observation_timestamp=None,
                                next_observation_timestamp=None,
                                message="Recovery not applicable — neighbor values are invalid for this parameter.",
                                unit=unit,
                                available=False,
                            )

                        prev_ts = _timestamp_to_iso(prev_row.get("parsed_ts", prev_row.get("timestamp", prev_row.get("TimeStamp"))))
                        next_ts = _timestamp_to_iso(next_row.get("parsed_ts", next_row.get("timestamp", next_row.get("TimeStamp"))))
                        estimated_value = (prev_val + next_val) / 2.0
                        return RecoveryEstimationResult(
                            observed_value=float(observed_value),
                            estimated_value=float(estimated_value),
                            recovery_parameter=recovery_parameter,
                            recovery_status="AVAILABLE",
                            recovery_method="Temporal neighbor interpolation",
                            previous_observation_timestamp=prev_ts,
                            next_observation_timestamp=next_ts,
                            message="Recovery computed successfully via linear temporal neighbor interpolation.",
                            unit=unit,
                            available=True,
                        )
            except Exception:
                pass

        return RecoveryEstimationResult(
            observed_value=float(observed_value),
            estimated_value=None,
            recovery_parameter=recovery_parameter,
            recovery_status="NOT_APPLICABLE",
            recovery_method=None,
            previous_observation_timestamp=None,
            next_observation_timestamp=None,
            message="Recovery not applicable — valid temporal neighbors are unavailable for this observation.",
            unit=unit,
            available=False,
        )
