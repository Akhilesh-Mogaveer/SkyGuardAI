"""Configuration settings for SkyGuard AI.

Provides directory paths, meteorological constraints, gap thresholds,
and column definitions used throughout the ingestion and QC pipeline.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Settings:
    """Application configuration parameters."""

    # Base filesystem paths
    BASE_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent)
    DATA_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "data")
    RAW_DATA_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "data" / "raw")
    PROCESSED_DATA_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "data" / "processed"
    )
    DEFAULT_RAW_CSV: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "imd_maitri_skyguard.csv"
    )

    # Station Metadata
    DEFAULT_STATION_ID: str = "AWS-MAITRI-89514"
    DEFAULT_STATION_NAME: str = "Maitri Station, Antarctica"
    STATION_LATITUDE: float = -70.767
    STATION_LONGITUDE: float = 11.733
    STATION_ELEVATION_M: float = 117.0

    # Companion / Spatial Buddy Stations
    BUDDY_STATIONS: Tuple[Tuple[str, str, float, float, float], ...] = (
        ("AWS-NOVO-89512", "Novolazarevskaya Station", -70.776, 11.832, 102.0),
        ("AWS-DG-89510", "Dakshin Gangotri Ice Shelf", -70.092, 12.000, 35.0),
    )

    # Ingestion & Missing Value Parameters
    SENTINEL_VALUES: Tuple[float, ...] = (-999.0, -999, -9999.0, -9999)
    NOMINAL_SAMPLING_HOURS: float = 1.0
    MAX_ALLOWABLE_INTERPOLATION_HOURS: float = 2.0  # Strict cap: never interpolate across gaps larger than this

    # Raw column names expected in incoming AWS logs
    RAW_TIMESTAMP_COL: str = "TimeStamp"
    RAW_TEMPERATURE_COL: str = "Air Temperature"
    RAW_PRESSURE_COL: str = "Air Pressure"
    RAW_WIND_SPEED_COL: str = "Wind Speed"
    RAW_WIND_DIR_COL: str = "Wind Direction"
    RAW_HUMIDITY_COL: str = "Relative Humidity"

    # Canonical snake_case names for internal pipeline processing
    CANONICAL_COLUMN_MAP: Dict[str, str] = field(
        default_factory=lambda: {
            "TimeStamp": "timestamp",
            "timestamp": "timestamp",
            "Air Temperature": "temperature",
            "temperature": "temperature",
            "Air Pressure": "pressure",
            "pressure": "pressure",
            "Wind Speed": "wind_speed",
            "wind_speed": "wind_speed",
            "Wind Direction": "wind_direction",
            "wind_direction": "wind_direction",
            "Relative Humidity": "relative_humidity",
            "relative_humidity": "relative_humidity",
        }
    )

    REQUIRED_RAW_COLUMNS: Tuple[str, ...] = (
        "TimeStamp",
        "Air Temperature",
        "Air Pressure",
        "Wind Speed",
        "Wind Direction",
        "Relative Humidity",
    )

    REQUIRED_CANONICAL_COLUMNS: Tuple[str, ...] = (
        "timestamp",
        "temperature",
        "pressure",
        "relative_humidity",
    )

    # Meteorological Plausibility Limits (WMO-8 Standard adjusted for Antarctic Oasis)
    TEMP_MIN_CELSIUS: float = -60.0
    TEMP_MAX_CELSIUS: float = 25.0
    PRESSURE_MIN_HPA: float = 850.0
    PRESSURE_MAX_HPA: float = 1080.0
    HUMIDITY_MIN_PCT: float = 2.0
    HUMIDITY_MAX_PCT: float = 100.0
    WIND_SPEED_MIN_KNOTS: float = 0.0
    WIND_SPEED_MAX_KNOTS: float = 200.0

    # Rate of Change / Sudden Spike Thresholds (WMO Guideline per hour)
    TEMP_SPIKE_MAX_HOURLY_C: float = 8.0
    PRESSURE_SPIKE_MAX_HOURLY_HPA: float = 6.0
    HUMIDITY_SPIKE_MAX_HOURLY_PCT: float = 30.0

    # Persistence / Flatline Thresholds
    FLATLINE_MIN_CONSECUTIVE_HOURS: int = 4
    FLATLINE_TOLERANCE: float = 1e-4

    # Temporal Gap Threshold for Rate of Change
    MAX_STEP_RATE_GAP_HOURS: float = 1.5


settings = Settings()

