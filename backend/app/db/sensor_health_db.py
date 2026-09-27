"""Database Schema & Persistence Layer for Sensor Health Monitoring.

Manages SQLite storage for long-term sensor health records, parameter indicators,
trend metrics, and operational alerts:
- Tables: `sensor_health_logs` and `station_health_summary_logs`
- Supports time-series queries for historical health charts and FastAPI endpoints.
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from backend.app.config import settings

logger = logging.getLogger("skyguard.sensor_health_db")

DEFAULT_DB_PATH = settings.DATA_DIR / "sensor_health.db"


@dataclass
class SensorHealthEntry:
    """Schema for individual parameter health evaluation record."""

    id: Optional[int]
    timestamp: str
    station_id: str
    parameter_name: str
    health_index: float  # 0.0 to 100.0%
    status: str  # "HEALTHY", "DEGRADING", "MAINTENANCE_REQUIRED", "FAILED"
    anomaly_frequency: float  # [0, 1]
    missing_frequency: float  # [0, 1]
    flatline_frequency: float  # [0, 1]
    qc_violation_rate: float  # [0, 1]
    recent_anomaly_trend: float  # Recent 24h rate vs 30d baseline (-1.0 to +1.0)
    evaluation_window_hours: int
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "station_id": self.station_id,
            "parameter_name": self.parameter_name,
            "health_index": round(self.health_index, 1),
            "status": self.status,
            "indicators": {
                "anomaly_frequency": round(self.anomaly_frequency, 4),
                "missing_frequency": round(self.missing_frequency, 4),
                "flatline_frequency": round(self.flatline_frequency, 4),
                "qc_violation_rate": round(self.qc_violation_rate, 4),
                "recent_anomaly_trend": round(self.recent_anomaly_trend, 4),
            },
            "evaluation_window_hours": self.evaluation_window_hours,
            "created_at": self.created_at,
        }


@dataclass
class StationHealthSnapshot:
    """Schema for consolidated station health record."""

    id: Optional[int]
    timestamp: str
    station_id: str
    overall_health_index: float
    overall_status: str  # "OPERATIONAL", "DEGRADED", "CRITICAL_ATTENTION"
    parameter_scores: Dict[str, float]
    active_alerts: List[str]
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "station_id": self.station_id,
            "overall_health_index": round(self.overall_health_index, 1),
            "overall_status": self.overall_status,
            "parameter_scores": {k: round(v, 1) for k, v in self.parameter_scores.items()},
            "active_alerts": self.active_alerts,
            "created_at": self.created_at,
        }


class SensorHealthDatabase:
    """SQLite database connector and manager for sensor health records."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Creates table schemas if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_health_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    parameter_name TEXT NOT NULL,
                    health_index REAL NOT NULL,
                    status TEXT NOT NULL,
                    anomaly_frequency REAL NOT NULL,
                    missing_frequency REAL NOT NULL,
                    flatline_frequency REAL NOT NULL,
                    qc_violation_rate REAL NOT NULL,
                    recent_anomaly_trend REAL NOT NULL,
                    evaluation_window_hours INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS station_health_summary_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    overall_health_index REAL NOT NULL,
                    overall_status TEXT NOT NULL,
                    parameter_scores TEXT NOT NULL,
                    active_alerts TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Indexes for fast time-series lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sensor_param_ts ON sensor_health_logs (station_id, parameter_name, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_station_ts ON station_health_summary_logs (station_id, timestamp)")
            conn.commit()

    def insert_parameter_health(self, entry: SensorHealthEntry) -> int:
        """Inserts a parameter health record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sensor_health_logs (
                    timestamp, station_id, parameter_name, health_index, status,
                    anomaly_frequency, missing_frequency, flatline_frequency,
                    qc_violation_rate, recent_anomaly_trend, evaluation_window_hours, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.timestamp,
                    entry.station_id,
                    entry.parameter_name,
                    entry.health_index,
                    entry.status,
                    entry.anomaly_frequency,
                    entry.missing_frequency,
                    entry.flatline_frequency,
                    entry.qc_violation_rate,
                    entry.recent_anomaly_trend,
                    entry.evaluation_window_hours,
                    entry.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def insert_station_snapshot(self, snapshot: StationHealthSnapshot) -> int:
        """Inserts a consolidated station health snapshot."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO station_health_summary_logs (
                    timestamp, station_id, overall_health_index, overall_status,
                    parameter_scores, active_alerts, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.timestamp,
                    snapshot.station_id,
                    snapshot.overall_health_index,
                    snapshot.overall_status,
                    json.dumps(snapshot.parameter_scores),
                    json.dumps(snapshot.active_alerts),
                    snapshot.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def fetch_latest_station_snapshot(self, station_id: str) -> Optional[StationHealthSnapshot]:
        """Fetches the most recent health snapshot for a station."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM station_health_summary_logs
                WHERE station_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (station_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return StationHealthSnapshot(
                id=row["id"],
                timestamp=row["timestamp"],
                station_id=row["station_id"],
                overall_health_index=row["overall_health_index"],
                overall_status=row["overall_status"],
                parameter_scores=json.loads(row["parameter_scores"]),
                active_alerts=json.loads(row["active_alerts"]),
                created_at=row["created_at"],
            )

    def fetch_parameter_health_history(
        self, station_id: str, parameter_name: str, limit: int = 100
    ) -> List[SensorHealthEntry]:
        """Fetches time-series historical records for a parameter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM sensor_health_logs
                WHERE station_id = ? AND parameter_name = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (station_id, parameter_name, limit),
            )
            rows = cursor.fetchall()
            return [
                SensorHealthEntry(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    station_id=row["station_id"],
                    parameter_name=row["parameter_name"],
                    health_index=row["health_index"],
                    status=row["status"],
                    anomaly_frequency=row["anomaly_frequency"],
                    missing_frequency=row["missing_frequency"],
                    flatline_frequency=row["flatline_frequency"],
                    qc_violation_rate=row["qc_violation_rate"],
                    recent_anomaly_trend=row["recent_anomaly_trend"],
                    evaluation_window_hours=row["evaluation_window_hours"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
