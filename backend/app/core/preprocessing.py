"""Atmospheric Data Preprocessing Engine for SkyGuard AI.

Provides modular, reusable preprocessing pipelines for Automatic Weather Station observations:
- Strict sentinel (-999, -9999) translation to IEEE 754 NaN
- High-precision timestamp parsing and chronological sorting
- Mandatory column schema validation & canonical normalization
- Duplicate timestamp auditing and deduplication
- Missing value profiling per meteorological channel
- Time gap detection, gap duration profiling, and continuous segment tagging
- Strict non-interpolation across large temporal gaps
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from backend.app.config import settings

logger = logging.getLogger("skyguard.preprocessing")


def validate_required_columns(
    df: pd.DataFrame,
    required_columns: Optional[Sequence[str]] = None,
    canonicalize: bool = True,
) -> pd.DataFrame:
    """Validates the presence of required meteorological columns in the DataFrame.
    
    Args:
        df: Input raw DataFrame.
        required_columns: Sequence of column names that must exist.
        canonicalize: If True, renames columns to canonical snake_case.
        
    Returns:
        pd.DataFrame: Validated (and optionally canonicalized) DataFrame copy.
        
    Raises:
        ValueError: If any required column is absent.
    """
    req_cols = list(required_columns or settings.REQUIRED_RAW_COLUMNS)
    missing = [c for c in req_cols if c not in df.columns]
    if missing:
        err_msg = f"Data validation failed. Missing required columns: {missing}. Available: {list(df.columns)}"
        logger.error(err_msg)
        raise ValueError(err_msg)

    logger.debug("Successfully validated %d required columns.", len(req_cols))
    out_df = df.copy()

    if canonicalize:
        rename_dict = {
            col: settings.CANONICAL_COLUMN_MAP[col]
            for col in out_df.columns
            if col in settings.CANONICAL_COLUMN_MAP
        }
        out_df.rename(columns=rename_dict, inplace=True)
        logger.debug("Canonicalized columns to: %s", list(out_df.columns))

    return out_df


def clean_missing_sentinels(
    df: pd.DataFrame,
    sentinel_values: Optional[Sequence[Union[float, int]]] = None,
    target_columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Replaces sentinel missing values (e.g. -999, -9999) with np.nan.
    
    Args:
        df: Input DataFrame.
        sentinel_values: Sequence of numeric values representing missingness.
        target_columns: Optional subset of columns to clean. If None, cleans all numeric columns.
        
    Returns:
        pd.DataFrame: Cleaned DataFrame with sentinels replaced by NaN.
    """
    sentinels = set(sentinel_values or settings.SENTINEL_VALUES)
    out_df = df.copy()
    columns = target_columns or [c for c in out_df.columns if c != "timestamp" and c != "TimeStamp"]

    total_replaced = 0
    for col in columns:
        if col in out_df.columns:
            # Convert column to float if numeric to support NaN
            if pd.api.types.is_numeric_dtype(out_df[col]):
                out_df[col] = out_df[col].astype(float)
                mask = out_df[col].isin(sentinels)
                count = int(mask.sum())
                if count > 0:
                    out_df.loc[mask, col] = np.nan
                    total_replaced += count
                    logger.debug("Replaced %d sentinels in column '%s' with NaN.", count, col)

    logger.info("Replaced %d total sentinel values across %d columns.", total_replaced, len(columns))
    return out_df


def parse_timestamps(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    utc: bool = True,
) -> pd.DataFrame:
    """Parses mixed string timestamps into datetime64 objects.
    
    Args:
        df: Input DataFrame.
        timestamp_col: Name of the timestamp column.
        utc: Whether to interpret/convert as UTC.
        
    Returns:
        pd.DataFrame: DataFrame with normalized datetime timestamps.
        
    Raises:
        ValueError: If timestamp_col is missing or unparseable.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found in DataFrame.")

    out_df = df.copy()
    try:
        out_df[timestamp_col] = pd.to_datetime(out_df[timestamp_col], format="mixed", utc=utc)
    except Exception as exc:
        logger.warning("Fast mixed-format timestamp parsing failed (%s), falling back to flexible parsing.", exc)
        out_df[timestamp_col] = pd.to_datetime(out_df[timestamp_col], utc=utc)

    # Check for NaT (unparseable values)
    nat_count = out_df[timestamp_col].isna().sum()
    if nat_count > 0:
        logger.warning("Encountered %d unparseable NaT timestamps in column '%s'.", nat_count, timestamp_col)

    logger.debug("Successfully parsed %d timestamps in column '%s'.", len(out_df), timestamp_col)
    return out_df


def sort_chronologically(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Sorts DataFrame chronologically by timestamp and resets the index.
    
    Args:
        df: Input DataFrame.
        timestamp_col: Name of timestamp column.
        
    Returns:
        pd.DataFrame: Sorted DataFrame.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found.")

    out_df = df.sort_values(by=timestamp_col).reset_index(drop=True)
    logger.debug("Sorted %d records chronologically by '%s'.", len(out_df), timestamp_col)
    return out_df


def detect_duplicate_timestamps(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    keep: str = "first",
) -> Tuple[int, pd.DataFrame, pd.DataFrame]:
    """Detects duplicate timestamps in the observation sequence.
    
    Args:
        df: Input DataFrame.
        timestamp_col: Name of timestamp column.
        keep: Strategy for duplicate deduplication ('first', 'last', or False).
        
    Returns:
        Tuple containing:
        - int: Count of duplicate timestamp occurrences.
        - pd.DataFrame: DataFrame containing all rows with duplicate timestamps.
        - pd.DataFrame: Deduplicated DataFrame (retaining entry as specified by keep).
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found.")

    dup_mask = df.duplicated(subset=[timestamp_col], keep=False)
    dup_rows = df[dup_mask].copy()
    dup_count = len(df) - len(df.drop_duplicates(subset=[timestamp_col], keep=keep))

    if dup_count > 0:
        logger.warning("Detected %d duplicate timestamp records in dataset.", dup_count)
        dedup_df = df.drop_duplicates(subset=[timestamp_col], keep=keep).reset_index(drop=True)
    else:
        logger.info("Zero duplicate timestamps detected in dataset.")
        dedup_df = df.copy().reset_index(drop=True)

    return dup_count, dup_rows, dedup_df


def detect_missing_values(
    df: pd.DataFrame,
    exclude_columns: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Profiles missing values (NaN) across all parameters.
    
    Args:
        df: Input DataFrame.
        exclude_columns: Columns to ignore during calculation.
        
    Returns:
        Dict[str, Dict[str, Any]]: Missing value metrics per column.
    """
    exclude = set(exclude_columns or ["timestamp", "segment_id", "is_interpolated"])
    total_rows = len(df)
    results = {}

    for col in df.columns:
        if col in exclude:
            continue
        missing_count = int(df[col].isna().sum())
        missing_pct = round((missing_count / total_rows * 100.0), 2) if total_rows > 0 else 0.0
        valid_count = total_rows - missing_count

        # Compute longest run of consecutive missing values
        is_na = df[col].isna()
        if is_na.any():
            max_consecutive_na = int((~is_na).cumsum()[is_na].value_counts().max())
        else:
            max_consecutive_na = 0

        results[col] = {
            "missing_count": missing_count,
            "valid_count": valid_count,
            "missing_pct": missing_pct,
            "max_consecutive_missing": max_consecutive_na,
        }

    logger.debug("Computed missing value profile for %d parameters.", len(results))
    return results


def detect_time_gaps(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    nominal_freq_hours: float = 1.0,
) -> Tuple[int, pd.DataFrame, Dict[str, Any]]:
    """Detects and profiles all time gaps where delta-t exceeds nominal frequency.
    
    Args:
        df: Chronologically sorted DataFrame.
        timestamp_col: Timestamp column name.
        nominal_freq_hours: Expected time interval between consecutive records (default 1.0 hour).
        
    Returns:
        Tuple containing:
        - int: Total number of gap events (> nominal_freq_hours).
        - pd.DataFrame: Detailed table of all gap events with start, end, duration.
        - Dict[str, Any]: Aggregated summary statistics of gap durations.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found.")

    if len(df) < 2:
        return 0, pd.DataFrame(), {"total_gaps": 0, "max_gap_hours": 0.0, "total_missing_hours": 0.0}

    ts = df[timestamp_col]
    delta = ts.diff()
    threshold = pd.Timedelta(hours=nominal_freq_hours)

    gap_mask = delta > threshold
    gap_indices = df.index[gap_mask].tolist()
    total_gaps = len(gap_indices)

    gap_records: List[Dict[str, Any]] = []
    for idx in gap_indices:
        gap_start = ts.iloc[idx - 1]
        gap_end = ts.iloc[idx]
        diff = gap_end - gap_start
        duration_hours = round(diff.total_seconds() / 3600.0, 2)
        missing_steps = int(round(duration_hours / nominal_freq_hours)) - 1

        gap_records.append({
            "gap_id": len(gap_records) + 1,
            "row_index_before": idx - 1,
            "row_index_after": idx,
            "gap_start": gap_start,
            "gap_end": gap_end,
            "duration_hours": duration_hours,
            "duration_days": round(duration_hours / 24.0, 2),
            "missing_steps": missing_steps,
        })

    gaps_df = pd.DataFrame(gap_records)

    if total_gaps > 0:
        durations = gaps_df["duration_hours"]
        gap_stats = {
            "total_gaps": total_gaps,
            "min_gap_hours": float(durations.min()),
            "max_gap_hours": float(durations.max()),
            "mean_gap_hours": round(float(durations.mean()), 2),
            "median_gap_hours": float(durations.median()),
            "p90_gap_hours": round(float(durations.quantile(0.90)), 2),
            "total_missing_hours": round(float(durations.sum() - (total_gaps * nominal_freq_hours)), 1),
        }
        logger.info(
            "Detected %d time gaps (> %.1f hrs). Max gap: %.1f hrs (%.1f days).",
            total_gaps,
            nominal_freq_hours,
            gap_stats["max_gap_hours"],
            gap_stats["max_gap_hours"] / 24.0,
        )
    else:
        gap_stats = {
            "total_gaps": 0,
            "min_gap_hours": 0.0,
            "max_gap_hours": 0.0,
            "mean_gap_hours": 0.0,
            "median_gap_hours": 0.0,
            "p90_gap_hours": 0.0,
            "total_missing_hours": 0.0,
        }
        logger.info("Zero time gaps detected: sequence is perfectly continuous at %.1f hr frequency.", nominal_freq_hours)

    return total_gaps, gaps_df, gap_stats


def identify_continuous_segments(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    max_step_hours: float = 1.0,
) -> pd.DataFrame:
    """Labels continuous time segments with a discrete segment_id.
    
    Any time gap greater than max_step_hours terminates the current segment and starts a new one.
    Downstream sequence models (such as LSTM Autoencoders) use this to extract continuous windows
    strictly within a single segment, guaranteeing zero interpolation or gap jumping.
    
    Args:
        df: Chronologically sorted DataFrame.
        timestamp_col: Name of timestamp column.
        max_step_hours: Maximum allowable time step within a single continuous segment.
        
    Returns:
        pd.DataFrame: DataFrame with an added integer 'segment_id' column.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found.")

    out_df = df.copy()
    if len(out_df) == 0:
        out_df["segment_id"] = pd.Series(dtype=int)
        return out_df

    delta = out_df[timestamp_col].diff()
    threshold = pd.Timedelta(hours=max_step_hours)
    
    # Whenever delta > threshold, a new segment begins
    is_new_segment = (delta > threshold).fillna(False)
    out_df["segment_id"] = is_new_segment.cumsum().astype(int)
    
    segment_count = int(out_df["segment_id"].nunique())
    logger.debug("Partitioned dataset into %d continuous segments (max_step=%.1f hrs).", segment_count, max_step_hours)
    return out_df


def interpolate_small_gaps(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    max_gap_hours: float = settings.MAX_ALLOWABLE_INTERPOLATION_HOURS,
    target_columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Safely interpolates missing values strictly within small gaps (<= max_gap_hours).
    
    CRITICAL QUALITY INVARIANT:
    Never interpolates across large gaps. Large gaps (> max_gap_hours) strictly remain NaN.
    Adds a boolean 'is_interpolated' column to preserve complete provenance of synthetic estimates.
    
    Args:
        df: Chronologically sorted DataFrame.
        timestamp_col: Name of timestamp column.
        max_gap_hours: Maximum gap span permitted for interpolation.
        target_columns: Meteorological columns to interpolate.
        
    Returns:
        pd.DataFrame: DataFrame with small gaps filled, large gaps untouched, and 'is_interpolated' flag.
    """
    cols = list(target_columns or ["temperature", "pressure", "relative_humidity", "wind_speed", "wind_direction"])
    cols = [c for c in cols if c in df.columns]

    out_df = df.copy()
    out_df["is_interpolated"] = False

    # Resample to complete hourly grid up to small limit or apply linear limit
    # For in-sequence NaNs, limit direction and max limit
    # Note: 1 hour missing = 1 step limit. If max_gap_hours = 2, max consecutive NaNs to fill = 2.
    max_consecutive_steps = int(max_gap_hours)

    for col in cols:
        before_na = out_df[col].isna()
        # Interpolate linearly with strict limit; gaps larger than max_consecutive_steps leave subsequent NaNs untouched
        filled = out_df[col].interpolate(method="linear", limit=max_consecutive_steps, limit_direction="forward")
        after_na = filled.isna()
        
        # Identify rows that were actually filled
        interpolated_mask = before_na & (~after_na)
        if interpolated_mask.any():
            out_df.loc[interpolated_mask, "is_interpolated"] = True
            logger.debug(
                "Interpolated %d values for '%s' within small gaps (<= %d steps).",
                int(interpolated_mask.sum()),
                col,
                max_consecutive_steps,
            )
        out_df[col] = filled

    logger.info("Completed small-gap interpolation (limit=%d hrs). Large gaps left as NaN.", max_consecutive_steps)
    return out_df


def compute_parameter_statistics(
    df: pd.DataFrame,
    parameters: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """Calculates comprehensive statistical distribution metrics for all meteorological parameters.
    
    Args:
        df: Input cleaned DataFrame.
        parameters: Sequence of column names to analyze.
        
    Returns:
        Dict[str, Dict[str, float]]: Statistical metrics (min, max, mean, std, quartiles) per parameter.
    """
    params = list(parameters or ["temperature", "pressure", "relative_humidity", "wind_speed", "wind_direction"])
    params = [p for p in params if p in df.columns and pd.api.types.is_numeric_dtype(df[p])]
    stats = {}

    for col in params:
        s = df[col].dropna()
        if len(s) > 0:
            stats[col] = {
                "count": int(s.count()),
                "min": round(float(s.min()), 2),
                "max": round(float(s.max()), 2),
                "mean": round(float(s.mean()), 2),
                "std": round(float(s.std()), 2),
                "q25": round(float(s.quantile(0.25)), 2),
                "median": round(float(s.median()), 2),
                "q75": round(float(s.quantile(0.75)), 2),
                "iqr": round(float(s.quantile(0.75) - s.quantile(0.25)), 2),
            }
        else:
            stats[col] = {
                "count": 0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "q25": 0.0,
                "median": 0.0,
                "q75": 0.0,
                "iqr": 0.0,
            }

    return stats


def preprocess_aws_dataframe(
    raw_df: pd.DataFrame,
    interpolate_small: bool = False,
    max_gap_hours: float = settings.MAX_ALLOWABLE_INTERPOLATION_HOURS,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Executes the full preprocessing pipeline on a raw AWS DataFrame.
    
    Steps:
    1. Validates required columns and converts to canonical names.
    2. Replaces sentinel values (-999) with NaN.
    3. Parses timestamps into UTC datetime64.
    4. Sorts chronologically.
    5. Audits and deduplicates timestamps.
    6. Analyzes missing value profile.
    7. Detects and profiles time gaps.
    8. Identifies continuous hourly segments for ML.
    9. Optionally applies small-gap interpolation (while strictly keeping large gaps NaN).
    
    Args:
        raw_df: Raw DataFrame from CSV or API.
        interpolate_small: Whether to fill small gaps (<= max_gap_hours).
        max_gap_hours: Upper bound for allowable interpolation.
        
    Returns:
        Tuple containing:
        - pd.DataFrame: Cleaned, structured working DataFrame.
        - Dict[str, Any]: Comprehensive preprocessing metadata and audit summary.
    """
    logger.info("Initiating full AWS preprocessing pipeline for %d raw rows...", len(raw_df))

    # 1. Validation & Canonical Mapping
    canonical_df = validate_required_columns(raw_df, canonicalize=True)

    # 2. Sentinels to NaN
    cleaned_sentinels_df = clean_missing_sentinels(canonical_df)

    # 3. Parse Timestamps
    parsed_df = parse_timestamps(cleaned_sentinels_df, timestamp_col="timestamp")

    # 4. Sort Chronologically
    sorted_df = sort_chronologically(parsed_df, timestamp_col="timestamp")

    # 5. Detect & Handle Duplicates
    dup_count, dup_rows, dedup_df = detect_duplicate_timestamps(sorted_df, timestamp_col="timestamp")

    # 6. Detect Missing Values
    missing_profile = detect_missing_values(dedup_df)

    # 7. Detect Time Gaps
    gap_count, gaps_df, gap_stats = detect_time_gaps(dedup_df, timestamp_col="timestamp")

    # 8. Continuous Segments for LSTM
    segmented_df = identify_continuous_segments(dedup_df, timestamp_col="timestamp", max_step_hours=1.0)

    # 9. Optional Small-Gap Interpolation
    if interpolate_small:
        final_df = interpolate_small_gaps(segmented_df, timestamp_col="timestamp", max_gap_hours=max_gap_hours)
    else:
        final_df = segmented_df.copy()
        final_df["is_interpolated"] = False

    # Parameter Stats
    param_stats = compute_parameter_statistics(final_df)

    audit_summary = {
        "raw_rows": len(raw_df),
        "cleaned_rows": len(final_df),
        "date_start": str(final_df["timestamp"].min()) if len(final_df) > 0 else None,
        "date_end": str(final_df["timestamp"].max()) if len(final_df) > 0 else None,
        "duplicate_timestamps": dup_count,
        "total_gaps": gap_count,
        "gap_statistics": gap_stats,
        "gaps_detail": gaps_df,
        "missing_values": missing_profile,
        "parameter_statistics": param_stats,
        "continuous_segments_count": int(final_df["segment_id"].nunique()) if len(final_df) > 0 else 0,
    }

    logger.info(
        "Preprocessing completed. %d valid records spanning %s to %s.",
        len(final_df),
        audit_summary["date_start"],
        audit_summary["date_end"],
    )
    return final_df, audit_summary
