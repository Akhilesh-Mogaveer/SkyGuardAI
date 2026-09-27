"""Rule-Based Quality Control (QC) Engine for SkyGuard AI.

Implements WMO-compliant, reusable QC detectors:
1. Physical plausibility (climatological & gross physical bounds)
2. Sudden temperature changes (hourly step rate test)
3. Sudden pressure changes (hourly barometric tendency test)
4. Sudden humidity changes (hourly psychrometric step test)
5. Flatline / frozen sensor detection (persistence test)
6. Missing observation detection (sentinel/NaN auditing)
7. Communication / time gap detection

Core Design Principles:
- Preserves all observations; never deletes suspicious or faulty records.
- Generates granular boolean flags and human-readable audit reasons.
- Objective flagging: Marks records as 'PASSED', 'SUSPECT', 'MISSING', or 'GAP'
  without classifying them as sensor faults (leaving definitive attribution to evidence fusion).
- Never calculates hourly step rates across discontinuous time gaps.
- Full threshold configurability via QCConfig.
- Outputs structured metadata adhering to the exact QC result schema.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from backend.app.config import settings

logger = logging.getLogger("skyguard.baseline_qc")


@dataclass
class QCConfig:
    """Configurable thresholds for Rule-Based Quality Control."""

    # Physical plausibility limits
    temp_min: float = settings.TEMP_MIN_CELSIUS
    temp_max: float = settings.TEMP_MAX_CELSIUS
    pressure_min: float = settings.PRESSURE_MIN_HPA
    pressure_max: float = settings.PRESSURE_MAX_HPA
    humidity_min: float = settings.HUMIDITY_MIN_PCT
    humidity_max: float = settings.HUMIDITY_MAX_PCT

    # Sudden change / spike thresholds (maximum allowable change per hour)
    temp_spike_max_hourly: float = settings.TEMP_SPIKE_MAX_HOURLY_C
    pressure_spike_max_hourly: float = settings.PRESSURE_SPIKE_MAX_HOURLY_HPA
    humidity_spike_max_hourly: float = settings.HUMIDITY_SPIKE_MAX_HOURLY_PCT

    # Persistence / flatline thresholds
    flatline_min_consecutive_hours: int = settings.FLATLINE_MIN_CONSECUTIVE_HOURS
    flatline_tolerance: float = settings.FLATLINE_TOLERANCE

    # Time gap thresholds
    nominal_freq_hours: float = settings.NOMINAL_SAMPLING_HOURS
    max_step_rate_gap_hours: float = settings.MAX_STEP_RATE_GAP_HOURS


@dataclass
class QCResult:
    """Structured QC Result Schema for an individual AWS observation.
    
    Contains all required fields and boolean anomaly flags.
    """

    timestamp: Union[str, datetime, pd.Timestamp]
    station_id: str
    temperature: Optional[float]
    pressure: Optional[float]
    humidity: Optional[float]
    qc_flag: str  # "PASSED", "SUSPECT", "MISSING", "GAP"
    qc_reasons: List[str] = field(default_factory=list)
    temperature_spike: bool = False
    pressure_spike: bool = False
    humidity_spike: bool = False
    temperature_flatline: bool = False
    pressure_flatline: bool = False
    humidity_flatline: bool = False
    missing_flag: bool = False
    gap_flag: bool = False

    def __post_init__(self) -> None:
        self.temperature_spike = bool(self.temperature_spike)
        self.pressure_spike = bool(self.pressure_spike)
        self.humidity_spike = bool(self.humidity_spike)
        self.temperature_flatline = bool(self.temperature_flatline)
        self.pressure_flatline = bool(self.pressure_flatline)
        self.humidity_flatline = bool(self.humidity_flatline)
        self.missing_flag = bool(self.missing_flag)
        self.gap_flag = bool(self.gap_flag)

    def to_dict(self) -> Dict[str, Any]:
        """Converts QC result to standard dictionary."""
        d = asdict(self)
        if isinstance(self.timestamp, (datetime, pd.Timestamp)):
            d["timestamp"] = self.timestamp.isoformat()
        return d


# ==============================================================================
# 1. Physical Plausibility Detector
# ==============================================================================

def check_physical_plausibility(
    val: Optional[float],
    min_val: float,
    max_val: float,
    param_name: str,
) -> Tuple[bool, Optional[str]]:
    """Checks whether a meteorological parameter falls within physical plausible limits.
    
    Returns:
        Tuple[bool, Optional[str]]: (is_plausible, reason_if_invalid)
    """
    if val is None or np.isnan(val):
        return True, None  # Missing values handled by missing detector

    if val < min_val:
        reason = f"{param_name}_plausibility_violation: {val:.2f} < {min_val:.2f}"
        return False, reason
    if val > max_val:
        reason = f"{param_name}_plausibility_violation: {val:.2f} > {max_val:.2f}"
        return False, reason

    return True, None


# ==============================================================================
# 2-4. Sudden Change / Spike Detectors (Rate of Change)
# ==============================================================================

def check_rate_of_change(
    curr_val: Optional[float],
    prev_val: Optional[float],
    time_diff_hours: Optional[float],
    max_rate_per_hour: float,
    param_name: str,
    max_allowed_gap_hours: float = settings.MAX_STEP_RATE_GAP_HOURS,
) -> Tuple[bool, Optional[str], Optional[float]]:
    """Evaluates the rate of change between consecutive readings.
    
    CRITICAL RULE:
    Does NOT calculate hourly changes across time gaps (> max_allowed_gap_hours).
    
    Returns:
        Tuple[bool, Optional[str], Optional[float]]:
            - bool: True if spike threshold exceeded.
            - Optional[str]: Explanation reason if triggered.
            - Optional[float]: Calculated hourly rate (|delta| / dt), or None if uncomputable.
    """
    if curr_val is None or prev_val is None:
        return False, None, None

    if np.isnan(curr_val) or np.isnan(prev_val):
        return False, None, None

    if time_diff_hours is None or time_diff_hours <= 0:
        return False, None, None

    # Enforce non-calculation across time gaps
    if time_diff_hours > max_allowed_gap_hours:
        logger.debug(
            "Skipping rate-of-change calculation for %s across gap of %.2f hrs (> %.2f hrs limit)",
            param_name,
            time_diff_hours,
            max_allowed_gap_hours,
        )
        return False, None, None

    delta = abs(curr_val - prev_val)
    hourly_rate = delta / time_diff_hours

    if hourly_rate > max_rate_per_hour:
        reason = (
            f"{param_name}_spike: step rate of {hourly_rate:.2f}/hr exceeded "
            f"threshold of {max_rate_per_hour:.2f}/hr (delta={delta:.2f} in {time_diff_hours:.1f}h)"
        )
        return True, reason, round(hourly_rate, 3)

    return False, None, round(hourly_rate, 3)


# ==============================================================================
# 5. Flatline / Frozen Sensor Detector (Persistence Test)
# ==============================================================================

def check_flatline_series(
    series: pd.Series,
    timestamps: pd.Series,
    min_consecutive_hours: int = 4,
    tolerance: float = 1e-4,
    max_gap_hours: float = settings.MAX_STEP_RATE_GAP_HOURS,
) -> pd.Series:
    """Vectorized persistence check across a series.
    
    A flatline occurs when a sensor outputs the same value (within tolerance) for
    at least min_consecutive_hours without any intervening gap or NaN.
    
    Returns:
        pd.Series: Boolean Series where True indicates the observation is part of a flatline.
    """
    is_na = series.isna()
    diff_val = series.diff().abs()
    diff_time = timestamps.diff().dt.total_seconds() / 3600.0

    # A step is constant if value diff <= tolerance AND time diff <= max_gap_hours AND not NaN
    is_constant_step = (diff_val <= tolerance) & (diff_time <= max_gap_hours) & (~is_na)

    # Count consecutive constant steps
    # Any break in constant steps resets the block
    block_id = (~is_constant_step).cumsum()
    consecutive_counts = is_constant_step.groupby(block_id).cumsum()

    # Consecutive steps of N means N+1 consecutive readings
    # We want at least min_consecutive_hours, so consecutive_counts >= (min_consecutive_hours - 1)
    target_count = min_consecutive_hours - 1
    is_flatline_tail = consecutive_counts >= target_count

    # Backpropagate flatline flag to earlier observations in the same flatline block
    # For every block where any observation meets target_count, mark all constant observations in that block
    blocks_with_flatline = block_id[is_flatline_tail].unique()
    is_flatline = block_id.isin(blocks_with_flatline) & (~is_na)

    # The very first element of a constant block is also part of the flatline
    # so we shift the constant step backward by 1
    shift_next = is_constant_step.shift(-1, fill_value=False)
    is_flatline = (is_flatline | shift_next) & is_flatline

    return is_flatline.fillna(False)


# ==============================================================================
# 6. Missing Observation Detector
# ==============================================================================

def check_missing_observation(
    temperature: Optional[float],
    pressure: Optional[float],
    humidity: Optional[float],
) -> Tuple[bool, List[str]]:
    """Checks for NaN or absent values among primary channels.
    
    Returns:
        Tuple[bool, List[str]]: (is_missing, list_of_missing_channel_reasons)
    """
    missing_channels = []
    if temperature is None or np.isnan(temperature):
        missing_channels.append("temperature_missing")
    if pressure is None or np.isnan(pressure):
        missing_channels.append("pressure_missing")
    if humidity is None or np.isnan(humidity):
        missing_channels.append("humidity_missing")

    return (len(missing_channels) > 0), missing_channels


# ==============================================================================
# 7. Time Gap Detector
# ==============================================================================

def check_time_gap(
    time_diff_hours: Optional[float],
    nominal_hours: float = 1.0,
) -> Tuple[bool, Optional[str]]:
    """Checks if the observation follows an unexpected time gap (> nominal interval).
    
    Returns:
        Tuple[bool, Optional[str]]: (is_gap, reason)
    """
    if time_diff_hours is None:
        return False, None

    if time_diff_hours > nominal_hours:
        reason = f"time_gap_detected: {time_diff_hours:.1f} hrs since previous observation (> {nominal_hours:.1f} hrs)"
        return True, reason

    return False, None


# ==============================================================================
# Comprehensive Rule-Based Quality Control Pipeline
# ==============================================================================

class RuleBasedQC:
    """Orchestrates comprehensive rule-based quality control on AWS observations.
    
    Can process full historical DataFrames or stream observations one-by-one.
    """

    def __init__(
        self,
        config: Optional[QCConfig] = None,
        station_id: str = settings.DEFAULT_STATION_ID,
    ) -> None:
        self.config = config or QCConfig()
        self.station_id = station_id

    def process_observation(
        self,
        timestamp: Union[str, datetime, pd.Timestamp],
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        prev_observation: Optional[Dict[str, Any]] = None,
        flatline_flags: Optional[Dict[str, bool]] = None,
    ) -> QCResult:
        """Applies all 7 QC detectors to a single observation record."""
        ts = pd.to_datetime(timestamp, utc=True)
        reasons: List[str] = []

        # 1. Missing Observation Check
        is_missing, missing_reasons = check_missing_observation(temperature, pressure, humidity)
        reasons.extend(missing_reasons)

        # 2. Communication / Time Gap Check
        time_diff_hours = None
        is_gap = False
        if prev_observation and "timestamp" in prev_observation:
            prev_ts = pd.to_datetime(prev_observation["timestamp"], utc=True)
            time_diff_hours = (ts - prev_ts).total_seconds() / 3600.0
            is_gap, gap_reason = check_time_gap(time_diff_hours, nominal_hours=self.config.nominal_freq_hours)
            if is_gap and gap_reason:
                reasons.append(gap_reason)

        # 3. Physical Plausibility Checks
        temp_ok, temp_reason = check_physical_plausibility(
            temperature, self.config.temp_min, self.config.temp_max, "temperature"
        )
        if not temp_ok and temp_reason:
            reasons.append(temp_reason)

        press_ok, press_reason = check_physical_plausibility(
            pressure, self.config.pressure_min, self.config.pressure_max, "pressure"
        )
        if not press_ok and press_reason:
            reasons.append(press_reason)

        hum_ok, hum_reason = check_physical_plausibility(
            humidity, self.config.humidity_min, self.config.humidity_max, "humidity"
        )
        if not hum_ok and hum_reason:
            reasons.append(hum_reason)

        # 4. Sudden Change / Spike Checks (never across large gaps)
        prev_temp = prev_observation.get("temperature") if prev_observation else None
        temp_spike, temp_spike_reason, _ = check_rate_of_change(
            temperature,
            prev_temp,
            time_diff_hours,
            self.config.temp_spike_max_hourly,
            "temperature",
            max_allowed_gap_hours=self.config.max_step_rate_gap_hours,
        )
        if temp_spike and temp_spike_reason:
            reasons.append(temp_spike_reason)

        prev_press = prev_observation.get("pressure") if prev_observation else None
        press_spike, press_spike_reason, _ = check_rate_of_change(
            pressure,
            prev_press,
            time_diff_hours,
            self.config.pressure_spike_max_hourly,
            "pressure",
            max_allowed_gap_hours=self.config.max_step_rate_gap_hours,
        )
        if press_spike and press_spike_reason:
            reasons.append(press_spike_reason)

        prev_hum = prev_observation.get("humidity") if prev_observation else None
        hum_spike, hum_spike_reason, _ = check_rate_of_change(
            humidity,
            prev_hum,
            time_diff_hours,
            self.config.humidity_spike_max_hourly,
            "humidity",
            max_allowed_gap_hours=self.config.max_step_rate_gap_hours,
        )
        if hum_spike and hum_spike_reason:
            reasons.append(hum_spike_reason)

        # 5. Flatline Flags (supplied externally or from series processor)
        temp_flat = bool(flatline_flags.get("temperature", False)) if flatline_flags else False
        press_flat = bool(flatline_flags.get("pressure", False)) if flatline_flags else False
        hum_flat = bool(flatline_flags.get("humidity", False)) if flatline_flags else False

        if temp_flat:
            reasons.append("temperature_flatline: persistent identical readings")
        if press_flat:
            reasons.append("pressure_flatline: persistent identical readings")
        if hum_flat:
            reasons.append("humidity_flatline: persistent identical readings")

        # Determine overall QC Flag (without calling it a sensor fault)
        any_anomalous_rule = (
            not temp_ok
            or not press_ok
            or not hum_ok
            or temp_spike
            or press_spike
            or hum_spike
            or temp_flat
            or press_flat
            or hum_flat
        )

        if any_anomalous_rule:
            qc_flag = "SUSPECT"
        elif is_missing:
            qc_flag = "MISSING"
        elif is_gap:
            qc_flag = "GAP"
        else:
            qc_flag = "PASSED"

        return QCResult(
            timestamp=ts,
            station_id=self.station_id,
            temperature=temperature,
            pressure=pressure,
            humidity=humidity,
            qc_flag=qc_flag,
            qc_reasons=reasons,
            temperature_spike=temp_spike,
            pressure_spike=press_spike,
            humidity_spike=hum_spike,
            temperature_flatline=temp_flat,
            pressure_flatline=press_flat,
            humidity_flatline=hum_flat,
            missing_flag=is_missing,
            gap_flag=is_gap,
        )

    def process_dataframe(
        self,
        df: pd.DataFrame,
        station_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Applies comprehensive Rule-Based QC across an entire historical DataFrame.
        
        Preserves all original observations and returns a DataFrame adhering strictly
        to the required QC result schema.
        
        Args:
            df: Cleaned AWS DataFrame with columns: timestamp, temperature, pressure,
                and relative_humidity (or humidity).
            station_id: Station identifier.
            
        Returns:
            pd.DataFrame: DataFrame containing every observation with all structured QC columns.
        """
        stat_id = station_id or self.station_id
        logger.info("Executing Rule-Based Quality Control for %d observations...", len(df))

        # Ensure required canonical columns
        work_df = df.copy()
        if "relative_humidity" in work_df.columns and "humidity" not in work_df.columns:
            work_df["humidity"] = work_df["relative_humidity"]

        work_df["timestamp"] = pd.to_datetime(work_df["timestamp"], utc=True)
        work_df = work_df.sort_values(by="timestamp").reset_index(drop=True)

        # 1. Compute vectorized flatlines
        logger.debug("Evaluating flatline persistence across time series...")
        t_flat = check_flatline_series(
            work_df["temperature"],
            work_df["timestamp"],
            min_consecutive_hours=self.config.flatline_min_consecutive_hours,
            tolerance=self.config.flatline_tolerance,
            max_gap_hours=self.config.max_step_rate_gap_hours,
        )
        p_flat = check_flatline_series(
            work_df["pressure"],
            work_df["timestamp"],
            min_consecutive_hours=self.config.flatline_min_consecutive_hours,
            tolerance=self.config.flatline_tolerance,
            max_gap_hours=self.config.max_step_rate_gap_hours,
        )
        h_flat = check_flatline_series(
            work_df["humidity"],
            work_df["timestamp"],
            min_consecutive_hours=self.config.flatline_min_consecutive_hours,
            tolerance=self.config.flatline_tolerance,
            max_gap_hours=self.config.max_step_rate_gap_hours,
        )

        qc_results: List[Dict[str, Any]] = []
        prev_obs: Optional[Dict[str, Any]] = None

        for idx, row in work_df.iterrows():
            curr_flatlines = {
                "temperature": bool(t_flat.iloc[idx]),
                "pressure": bool(p_flat.iloc[idx]),
                "humidity": bool(h_flat.iloc[idx]),
            }

            temp_val = float(row["temperature"]) if pd.notna(row["temperature"]) else None
            press_val = float(row["pressure"]) if pd.notna(row["pressure"]) else None
            hum_val = float(row["humidity"]) if pd.notna(row["humidity"]) else None

            res = self.process_observation(
                timestamp=row["timestamp"],
                temperature=temp_val,
                pressure=press_val,
                humidity=hum_val,
                prev_observation=prev_obs,
                flatline_flags=curr_flatlines,
            )

            qc_results.append(res.to_dict())

            prev_obs = {
                "timestamp": row["timestamp"],
                "temperature": temp_val,
                "pressure": press_val,
                "humidity": hum_val,
            }

        qc_df = pd.DataFrame(qc_results)
        logger.info(
            "QC Completed. Flag Distribution: %s",
            qc_df["qc_flag"].value_counts().to_dict(),
        )
        return qc_df


BaselineQCChecker = RuleBasedQC
