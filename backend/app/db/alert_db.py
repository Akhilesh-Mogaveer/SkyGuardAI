"""Database Schema & Persistence Layer for Observations and Operational Alerts.

Manages SQLite storage for all processed AWS observations and anomaly alerts:
- Table: `observations_log`
- Ensures every observation processed by the pipeline, single ingestion API, or replay is stored permanently in SQLite.
"""

from dataclasses import dataclass
import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import settings
from backend.app.core.evidence_fusion import get_maintenance_action, get_maintenance_status

logger = logging.getLogger("skyguard.alert_db")

DEFAULT_ALERT_DB_PATH = settings.DATA_DIR / "observations_alerts.db"


class AlertDatabase:
    """SQLite database manager for storing all observations and alerts."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_ALERT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _normalize_maintenance_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Apply current maintenance policy to both new and legacy alert payloads."""
        decision = payload.get("decision")
        if not isinstance(decision, dict):
            decision = {}
            payload["decision"] = decision

        severity = decision.get("severity", payload.get("severity", "NONE"))
        classification = decision.get(
            "classification",
            payload.get("final_classification", payload.get("classification", "NORMAL")),
        )
        root_cause = decision.get(
            "probable_cause",
            decision.get(
                "primary_root_cause",
                payload.get("primary_root_cause", payload.get("root_cause", "")),
            ),
        )
        status = get_maintenance_status(severity, classification, root_cause)
        action = get_maintenance_action(
            root_cause,
            decision.get("recommended_operator_action", payload.get("recommended_operator_action", "")),
        )
        decision["maintenance_status"] = status
        decision["maintenance_action"] = action
        payload["maintenance_status"] = status
        payload["maintenance_action"] = action
        return payload

    def init_db(self) -> None:
        """Creates table schemas if they do not exist and applies migrations."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS observations_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    temperature REAL,
                    pressure REAL,
                    humidity REAL,
                    classification TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    observed_value REAL,
                    estimated_value REAL,
                    recovery_status TEXT,
                    recovery_method TEXT,
                    previous_observation_timestamp TEXT,
                    next_observation_timestamp TEXT,
                    alert_key TEXT,
                    parameter TEXT,
                    anomaly_type TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Migrate existing SQLite table if columns are missing
            migration_cols = [
                ("observed_value", "REAL"),
                ("estimated_value", "REAL"),
                ("recovery_status", "TEXT"),
                ("recovery_method", "TEXT"),
                ("previous_observation_timestamp", "TEXT"),
                ("next_observation_timestamp", "TEXT"),
                ("alert_key", "TEXT"),
                ("parameter", "TEXT"),
                ("anomaly_type", "TEXT"),
            ]
            for col_name, col_type in migration_cols:
                try:
                    cursor.execute(f"ALTER TABLE observations_log ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

            # Indexes for fast lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations_log (station_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_obs_class ON observations_log (classification, severity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_key ON observations_log (alert_key) WHERE alert_key IS NOT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_parameter ON observations_log (parameter)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_key ON observations_log (alert_key) WHERE alert_key IS NOT NULL")
            conn.commit()

    @staticmethod
    def _normalize_timestamp(ts: Any) -> str:
        """Standardizes timestamps into a consistent UTC string representation."""
        if not ts:
            return ""
        try:
            parsed = pd.to_datetime(ts, utc=True)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts).strip()

    @classmethod
    def _alert_identity(cls, res_dict: Dict[str, Any]) -> Tuple[str, str, str, str]:
        decision = res_dict.get("decision", {}) or {}
        qc = res_dict.get("qc_result", {}) or {}
        station_id = str(res_dict.get("station_id", settings.DEFAULT_STATION_ID)).strip()
        raw_ts = str(res_dict.get("timestamp", ""))
        timestamp = cls._normalize_timestamp(raw_ts)

        parameter = str(
            decision.get("primary_parameter")
            or res_dict.get("primary_parameter")
            or res_dict.get("parameter")
            or ("temperature" if qc.get("temperature_spike") or qc.get("temperature_flatline") else "")
            or ("pressure" if qc.get("pressure_spike") or qc.get("pressure_flatline") else "")
            or ("humidity" if qc.get("humidity_spike") or qc.get("humidity_flatline") else "observation")
        ).strip().lower()

        anomaly_type = str(
            decision.get("primary_root_cause")
            or decision.get("probable_cause")
            or res_dict.get("primary_root_cause")
            or res_dict.get("anomaly_type")
            or decision.get("classification")
            or res_dict.get("final_classification", "NORMAL")
        ).strip().lower()

        alert_key = f"{station_id}|{timestamp}|{parameter}|{anomaly_type}"
        return alert_key, parameter, anomaly_type, station_id

    def init_db(self) -> None:
        """Creates table schemas if they do not exist, applies migrations, and deduplicates legacy records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS observations_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    temperature REAL,
                    pressure REAL,
                    humidity REAL,
                    classification TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    observed_value REAL,
                    estimated_value REAL,
                    recovery_status TEXT,
                    recovery_method TEXT,
                    previous_observation_timestamp TEXT,
                    next_observation_timestamp TEXT,
                    alert_key TEXT,
                    parameter TEXT,
                    anomaly_type TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Migrate existing SQLite table if columns are missing
            migration_cols = [
                ("observed_value", "REAL"),
                ("estimated_value", "REAL"),
                ("recovery_status", "TEXT"),
                ("recovery_method", "TEXT"),
                ("previous_observation_timestamp", "TEXT"),
                ("next_observation_timestamp", "TEXT"),
                ("alert_key", "TEXT"),
                ("parameter", "TEXT"),
                ("anomaly_type", "TEXT"),
            ]
            for col_name, col_type in migration_cols:
                try:
                    cursor.execute(f"ALTER TABLE observations_log ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

            # Drop unique index temporarily to allow backfill and cleanup safely
            cursor.execute("DROP INDEX IF EXISTS uq_alert_key")

            # Backfill alert_key for existing NULL rows
            cursor.execute("SELECT id, timestamp, station_id, parameter, anomaly_type, classification, payload_json FROM observations_log WHERE alert_key IS NULL OR alert_key = ''")
            null_rows = cursor.fetchall()
            for r in null_rows:
                try:
                    p_dict = json.loads(r["payload_json"]) if r["payload_json"] else {}
                except Exception:
                    p_dict = {}
                if not p_dict.get("station_id"):
                    p_dict["station_id"] = r["station_id"]
                if not p_dict.get("timestamp"):
                    p_dict["timestamp"] = r["timestamp"]
                if r["parameter"] and not p_dict.get("parameter"):
                    p_dict["parameter"] = r["parameter"]
                if r["anomaly_type"] and not p_dict.get("anomaly_type"):
                    p_dict["anomaly_type"] = r["anomaly_type"]
                if r["classification"] and not p_dict.get("classification"):
                    p_dict["classification"] = r["classification"]

                ak, param, atype, st = self._alert_identity(p_dict)
                cursor.execute("UPDATE observations_log SET alert_key = ?, parameter = ?, anomaly_type = ? WHERE id = ?", (ak, param, atype, r["id"]))

            # Deduplicate existing rows in observations_log keeping row with MIN(id) for each alert_key
            cursor.execute(
                """
                DELETE FROM observations_log
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM observations_log
                    WHERE alert_key IS NOT NULL AND alert_key != ''
                    GROUP BY alert_key
                )
                """
            )

            # Indexes for fast lookups & unique constraint on alert_key
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations_log (station_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_obs_class ON observations_log (classification, severity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_key ON observations_log (alert_key) WHERE alert_key IS NOT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_parameter ON observations_log (parameter)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_key ON observations_log (alert_key) WHERE alert_key IS NOT NULL")
            conn.commit()

    def insert_observation(self, res_dict: Dict[str, Any]) -> int:
        """Stores an observation and reuses an existing row for the same alert identity."""
        alert_key, parameter, anomaly_type, station_id = self._alert_identity(res_dict)
        timestamp = str(res_dict.get("timestamp", ""))

        temperature = res_dict.get("temperature")
        pressure = res_dict.get("pressure")
        humidity = res_dict.get("humidity")

        decision = res_dict.get("decision", {}) or {}
        classification = str(decision.get("classification", res_dict.get("final_classification", "NORMAL")))
        severity = str(decision.get("severity", res_dict.get("severity", "NONE")))

        observed_value = res_dict.get("observed_value", temperature)
        estimated_value = res_dict.get("estimated_value")
        recovery_status = res_dict.get("recovery_status", "UNAVAILABLE")
        recovery_method = res_dict.get("recovery_method")
        previous_observation_timestamp = res_dict.get("previous_observation_timestamp")
        next_observation_timestamp = res_dict.get("next_observation_timestamp")

        res_dict["alert_key"] = alert_key
        payload_json = json.dumps(res_dict)
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO observations_log (
                    timestamp, station_id, temperature, pressure, humidity,
                    classification, severity, observed_value, estimated_value,
                    recovery_status, recovery_method, previous_observation_timestamp,
                    next_observation_timestamp, alert_key, parameter, anomaly_type,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    station_id,
                    temperature,
                    pressure,
                    humidity,
                    classification,
                    severity,
                    observed_value,
                    estimated_value,
                    recovery_status,
                    recovery_method,
                    previous_observation_timestamp,
                    next_observation_timestamp,
                    alert_key,
                    parameter,
                    anomaly_type,
                    payload_json,
                    created_at,
                ),
            )
            if cursor.rowcount == 0:
                # Row with this alert_key already existed. Fetch existing ID and update payload.
                cursor.execute("SELECT id FROM observations_log WHERE alert_key = ?", (alert_key,))
                existing = cursor.fetchone()
                existing_id = int(existing["id"]) if existing else None
                if existing_id:
                    res_dict["db_id"] = existing_id
                    res_dict["alert_id"] = str(existing_id)
                    updated_payload_json = json.dumps(res_dict)
                    cursor.execute(
                        """
                        UPDATE observations_log
                        SET payload_json = ?, classification = ?, severity = ?, temperature = ?,
                            pressure = ?, humidity = ?, observed_value = ?, estimated_value = ?,
                            recovery_status = ?, recovery_method = ?, parameter = ?, anomaly_type = ?
                        WHERE alert_key = ?
                        """,
                        (
                            updated_payload_json,
                            classification,
                            severity,
                            temperature,
                            pressure,
                            humidity,
                            observed_value,
                            estimated_value,
                            recovery_status,
                            recovery_method,
                            parameter,
                            anomaly_type,
                            alert_key,
                        ),
                    )
                    conn.commit()
                    return existing_id

            last_id = int(cursor.lastrowid)
            res_dict["db_id"] = last_id
            res_dict["alert_id"] = str(last_id)
            # Re-update payload_json to store the assigned db_id and alert_id
            cursor.execute("UPDATE observations_log SET payload_json = ? WHERE id = ?", (json.dumps(res_dict), last_id))
            conn.commit()
            return last_id

    @staticmethod
    def _append_filters(
        query: str,
        params: List[Any],
        severity: Optional[str] = None,
        classification: Optional[str] = None,
        station_id: Optional[str] = None,
        parameter: Optional[str] = None,
        time_range: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        if classification:
            query += " AND classification = ?"
            params.append(classification.upper())
        if severity:
            query += " AND severity = ?"
            params.append(severity.upper())
        if station_id:
            query += " AND station_id = ?"
            params.append(station_id)
        if parameter:
            query += " AND LOWER(COALESCE(parameter, '')) = ?"
            params.append(parameter.lower())
        if time_range in {"24H", "7D"}:
            modifier = "-24 hours" if time_range == "24H" else "-7 days"
            query += " AND datetime(timestamp) >= datetime('now', ?)"
            params.append(modifier)
        return query, params

    def fetch_anomalies_page(
        self,
        page: int = 1,
        page_size: int = 10,
        severity: Optional[str] = None,
        classification: Optional[str] = None,
        station_id: Optional[str] = None,
        parameter: Optional[str] = None,
        time_range: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns one database page of anomalies plus total and severity counts."""
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        where = " WHERE classification != 'NORMAL'"
        params: List[Any] = []
        where, params = self._append_filters(where, params, severity, classification, station_id, parameter, time_range)

        with self.get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS total FROM observations_log{where}", params).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT id, created_at, payload_json FROM observations_log{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
            items = []
            for row in rows:
                try:
                    item = json.loads(row["payload_json"])
                    item = self._normalize_maintenance_fields(item)
                    item["db_id"] = row["id"]
                    item["alert_id"] = str(row["id"])
                    item["created_at"] = row["created_at"]
                    items.append(item)
                except (TypeError, json.JSONDecodeError):
                    continue

            counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
            count_rows = conn.execute(
                "SELECT severity, COUNT(*) AS count FROM observations_log WHERE classification != 'NORMAL' GROUP BY severity"
            ).fetchall()
            for row in count_rows:
                if row["severity"] in counts:
                    counts[row["severity"]] = row["count"]

        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "counts": counts,
        }

    def fetch_observation_by_id(self, alert_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT id, created_at, payload_json FROM observations_log WHERE id = ?",
                (alert_id,),
            ).fetchone()
        if not row:
            return None
        item = json.loads(row["payload_json"])
        item = self._normalize_maintenance_fields(item)
        item["db_id"] = row["id"]
        item["alert_id"] = str(row["id"])
        item["created_at"] = row["created_at"]
        return item

    def fetch_anomalies(
        self,
        limit: int = 2000,
        severity: Optional[str] = None,
        classification: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches stored non-NORMAL anomalies."""
        query = "SELECT id, created_at, payload_json FROM observations_log WHERE classification != 'NORMAL'"
        params: List[Any] = []

        if classification and isinstance(classification, str):
            query += " AND classification = ?"
            params.append(classification.upper())
        if severity and isinstance(severity, str):
            query += " AND severity = ?"
            params.append(severity.upper())

        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit) if isinstance(limit, (int, float)) else 2000)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                try:
                    obj = json.loads(r["payload_json"])
                    obj = self._normalize_maintenance_fields(obj)
                    obj["db_id"] = r["id"]
                    obj["alert_id"] = str(r["id"])
                    obj["created_at"] = r["created_at"]
                    results.append(obj)
                except Exception:
                    pass
            return results

    def fetch_observations(
        self,
        limit: int = 2000,
        classification: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches all stored observations."""
        query = "SELECT id, created_at, payload_json FROM observations_log"
        params: List[Any] = []

        if classification and isinstance(classification, str):
            query += " WHERE classification = ?"
            params.append(classification.upper())

        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit) if isinstance(limit, (int, float)) else 2000)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                try:
                    obj = json.loads(r["payload_json"])
                    obj = self._normalize_maintenance_fields(obj)
                    obj["db_id"] = r["id"]
                    obj["alert_id"] = str(r["id"])
                    obj["created_at"] = r["created_at"]
                    results.append(obj)
                except Exception:
                    pass
            return results

    def clear_observations(self) -> int:
        """Clears all stored observations and alerts from the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM observations_log")
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count


# Global singleton instance
alert_db = AlertDatabase()
